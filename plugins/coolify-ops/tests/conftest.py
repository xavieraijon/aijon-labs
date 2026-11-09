"""Fixtures shared by every test file."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "deploy-app" / "scripts"))

import coolify  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real HTTP request from a test is a bug: fail at once instead of waiting for DNS or a timeout."""
    def blocked(*_a, **_k):
        raise AssertionError("tests must not touch the network: mock coolify.api / coolify._apps")
    monkeypatch.setattr(coolify.urllib.request, "urlopen", blocked)


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch, tmp_path):
    """git never reads the user's configuration nor finds a repository above the test's folder."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


@pytest.fixture
def git_identity(monkeypatch):
    """Local git in tmp_path without reading the user's git configuration."""
    for var, value in {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.org",
                       "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.org",
                       "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(var, value)


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Isolated configuration in a temporary folder."""
    monkeypatch.setenv("COOLIFY_OPS_HOME", str(tmp_path))
    monkeypatch.setattr(coolify, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(coolify, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(coolify, "REGISTRY", tmp_path / "apps.json")
    monkeypatch.setattr(coolify, "TOKEN_FILE", tmp_path / "token")
    coolify.write_json(coolify.CONFIG, {"url": "http://coolify.test:8000", "base_domain": "example.org",
                                        "server_uuid": "srv", "github_app_uuid": "gh",
                                        "reserved_subdomains": ["hooks"]})
    return tmp_path
