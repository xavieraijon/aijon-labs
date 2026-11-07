"""Tests for the deploy-app scripts (no network, no Docker: the API is mocked)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "deploy-app" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analyze  # noqa: E402
import coolify  # noqa: E402
import prepare  # noqa: E402

# ------------------------------------------------------------------ helpers


def make(root: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


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


# ------------------------------------------------------------------ coolify.py


def test_mask_hides_passwords_and_tokens():
    assert coolify.mask("postgres://u:secret@db:5432/x") == "postgres://u:****@db:5432/x"
    assert "abc123" not in coolify.mask("Authorization: Bearer abc123")


def test_domain_check(config, monkeypatch):
    monkeypatch.setattr(coolify, "_apps", lambda: [{"fqdn": "https://shop.example.org"}])
    check = lambda h: coolify.cmd_domain_check(argparse.Namespace(host=h))  # noqa: E731
    assert check("blog")["available"] is True
    assert check("blog")["host"] == "blog.example.org"
    assert check("shop")["available"] is False           # in use
    assert check("hooks")["available"] is False          # reserved
    assert check("Bad_Name")["available"] is False       # invalid
    assert check("something.other.com")["available"] is False


def test_env_push_marks_public_and_secret(config, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(coolify, "_set_env",
                        lambda app, k, v, secret: calls.append((k, v, secret)) or {"key": k, "action": "created"})
    f = make(tmp_path, {"vars.env": "# comment\nDATABASE_URL=postgres://a:b@c/d\nexport NEXT_PUBLIC_URL='https://x'\n\n"})
    r = coolify.cmd_env_push(argparse.Namespace(app="app-uuid", file=str(f / "vars.env")))
    assert r["ok"]
    assert ("DATABASE_URL", "postgres://a:b@c/d", True) in calls
    assert ("NEXT_PUBLIC_URL", "https://x", False) in calls
    assert "postgres://a:b@c/d" not in json.dumps(r)     # values never appear in the output


def test_destructive_commands_require_confirmation(config):
    with pytest.raises(coolify.Error):
        coolify.cmd_decommission(argparse.Namespace(app="x", confirmed=False, with_db=False, with_project=False))
    with pytest.raises(coolify.Error):
        coolify.cmd_rollback(argparse.Namespace(app="x", confirmed=False, image=None))
    with pytest.raises(coolify.Error):
        coolify.cmd_env_delete(argparse.Namespace(app="x", key="A", confirmed=False))


def test_registry_resolves_names(config):
    coolify.save_to_registry("shop", {"app_uuid": "u-123"})
    assert coolify.resolve_app("shop") == "u-123"
    assert coolify.resolve_app("other-uuid") == "other-uuid"


def test_decommission_waits_before_deleting_the_project(config, monkeypatch):
    """The project is deleted only once the app and the database are gone (otherwise leftovers stay on the server)."""
    coolify.save_to_registry("x", {"app_uuid": "a1", "db_uuid": "d1", "project_uuid": "p1"})
    calls, remaining = [], {"/applications/a1": 2, "/databases/d1": 1}

    def fake_api(method, path, body=None, query=None):
        calls.append((method, path))
        if method == "GET":
            if remaining[path] == 0:
                raise coolify.Error("HTTP 404 on GET")
            remaining[path] -= 1
        return {}

    monkeypatch.setattr(coolify, "api", fake_api)
    monkeypatch.setattr(coolify.time, "sleep", lambda s: None)
    r = coolify.cmd_decommission(argparse.Namespace(app="x", confirmed=True, with_db=True, with_project=True))
    assert r["deleted"]["project"] == "p1"
    delete_project = calls.index(("DELETE", "/projects/p1"))
    assert ("GET", "/applications/a1") in calls[:delete_project]
    assert ("GET", "/databases/d1") in calls[:delete_project]


def test_token_sources(config, monkeypatch):
    monkeypatch.setenv("COOLIFY_TOKEN", "from-env")
    assert coolify.token() == "from-env"
    monkeypatch.delenv("COOLIFY_TOKEN")
    (config / "token").write_text("from-file\n")
    assert coolify.token() == "from-file"


def test_legacy_config_is_migrated(tmp_path, monkeypatch):
    legacy, new = tmp_path / "coolify-deploy", tmp_path / "coolify-ops"
    legacy.mkdir()
    (legacy / "config.json").write_text(json.dumps({"url": "u", "dominio_base": "ex.org", "carpeta_proyectos": "~/P",
                                                    "limites_defecto": {"cpus": "1", "memoria": "256m"}}))
    (legacy / "apps.json").write_text(json.dumps({"shop": {"app_uuid": "a", "proyecto_uuid": "p", "dominio": "d"}}))
    monkeypatch.delenv("COOLIFY_OPS_HOME", raising=False)
    monkeypatch.setattr(coolify, "LEGACY_DIR", legacy)
    monkeypatch.setattr(coolify, "CONFIG_DIR", new)
    monkeypatch.setattr(coolify, "CONFIG", new / "config.json")
    monkeypatch.setattr(coolify, "REGISTRY", new / "apps.json")
    cfg = coolify.config()
    assert cfg["base_domain"] == "ex.org" and cfg["projects_dir"] == "~/P"
    assert cfg["default_limits"] == {"cpus": "1", "memory": "256m"}
    assert coolify.registry()["shop"] == {"app_uuid": "a", "project_uuid": "p", "domain": "d"}


# ------------------------------------------------------------------ analyze.py


def test_fastapi(tmp_path):
    make(tmp_path, {"requirements.txt": "fastapi\npsycopg[binary]\n",
                    "main.py": "import os\nfrom fastapi import FastAPI\napp = FastAPI()\nos.getenv('DATABASE_URL')\n"})
    r = analyze.analyze(tmp_path)
    assert r["deployable"]
    assert r["stack"]["template"] == "python-fastapi"
    assert r["stack"]["module"] == "main:app"
    assert "postgresql" in r["databases"]
    assert "DATABASE_URL" in r["env_vars"]["in_code"]


def test_old_angular_uses_node_16(tmp_path):
    make(tmp_path, {
        "package.json": json.dumps({"dependencies": {"@angular/core": "~13.0.0"}, "scripts": {"build": "ng build"}}),
        "package-lock.json": "{}",
        "angular.json": json.dumps({"projects": {"shop": {"architect": {"build": {
            "builder": "@angular-devkit/build-angular:browser", "options": {"outputPath": "dist/shop"}}}}}}),
    })
    s = analyze.analyze(tmp_path)["stack"]
    assert (s["template"], s["node_version"], s["build_dir"], s["port"]) == ("spa-nginx", "16", "dist/shop", 80)


def test_modern_angular_outputs_to_browser(tmp_path):
    make(tmp_path, {
        "package.json": json.dumps({"dependencies": {"@angular/core": "^19.0.0"}}),
        "angular.json": json.dumps({"projects": {"web": {"architect": {"build": {
            "builder": "@angular/build:application", "options": {"outputPath": "dist/web"}}}}}}),
    })
    assert analyze.analyze(tmp_path)["stack"]["build_dir"] == "dist/web/browser"


def test_monorepo_blocks(tmp_path):
    make(tmp_path, {"nx.json": "{}", "package.json": json.dumps({"dependencies": {"@angular/core": "21"}})})
    r = analyze.analyze(tmp_path)
    assert not r["deployable"]
    assert any("monorepo" in b for b in r["blockers"])


def test_secrets_block_without_showing_values(tmp_path):
    secret = "ghp_" + "a" * 36
    make(tmp_path, {"index.html": "<h1>hi</h1>", ".env": "KEY=real-value\n", "config.js": f"const t = '{secret}'\n",
                    ".env.example": "KEY=\n"})
    r = analyze.analyze(tmp_path)
    kinds = {(s["file"], s["type"]) for s in r["secrets"]}
    assert (".env", "sensitive file") in kinds
    assert ("config.js", "GitHub token") in kinds
    assert not any(s["file"] == ".env.example" for s in r["secrets"])
    assert secret not in json.dumps(r)
    assert not r["deployable"]


def test_supabase_needs_no_own_postgres(tmp_path):
    make(tmp_path, {"package.json": json.dumps({"dependencies": {"next": "16", "@supabase/supabase-js": "2"}}),
                    "src/x.ts": "process.env.NEXT_PUBLIC_SUPABASE_URL"})
    r = analyze.analyze(tmp_path)
    assert r["stack"]["template"] == "nextjs"
    assert "postgresql" not in r["databases"]


def test_paid_services_without_login_warn(tmp_path):
    make(tmp_path, {"requirements.txt": "flask\nopenai\n",
                    "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
    r = analyze.analyze(tmp_path)
    assert r["stack"]["template"] == "python-flask"
    assert any("paid services" in w for w in r["warnings"])


def test_existing_dockerfile_keeps_its_port(tmp_path):
    make(tmp_path, {"requirements.txt": "fastapi\n", "main.py": "app = FastAPI()\n",
                    "Dockerfile": "FROM x\nEXPOSE 9000\n"})
    s = analyze.analyze(tmp_path)["stack"]
    assert s["existing_dockerfile"] and s["port"] == 9000 and s["template"] is None


# ------------------------------------------------------------------ prepare.py


def test_render_detects_missing_values():
    assert prepare.render("FROM node:{{NODE_VERSION}}", {"NODE_VERSION": "22"}) == "FROM node:22"
    with pytest.raises(ValueError):
        prepare.render("EXPOSE {{PORT}}", {})


def test_every_template_renders_with_default_values():
    v = prepare.values({"stack": {"port": 8000}}, {})
    for p in (SCRIPTS.parent / "templates").glob("*.Dockerfile"):
        assert "{{" not in prepare.render(p.read_text(), v), p.name


def test_bundled_example_is_deployable():
    example = Path(__file__).resolve().parents[3] / "examples" / "hello-fastapi"
    r = analyze.analyze(example)
    assert r["deployable"], r["blockers"]
    assert (r["stack"]["template"], r["stack"]["module"], r["stack"]["port"]) == ("python-fastapi", "main:app", 8000)
    assert not (example / "Dockerfile").exists()  # the skill must write it


def test_external_check_ignores_silent_nodes():
    import verify
    assert verify.external_ok({"in1": "200", "ir4": None, "rs1": "200"})   # a node that did not answer
    assert not verify.external_ok({"in1": "200", "de1": "502"})            # a node that saw an error
    assert verify.external_ok({"error": "check-host unavailable"})        # unverified, not failed


def _fake_delete_api(calls):
    """API that answers 404 right after DELETE, like Coolify does before its background cleanup runs."""
    def fake(method, path, body=None, query=None):
        calls.append((method, path))
        if method == "GET":
            raise coolify.Error("HTTP 404 on GET")
        return {}
    return fake


def test_decommission_waits_for_server_cleanup_not_for_404(config, monkeypatch):
    """Regression: the API says 404 immediately; the project may only go once the server has no leftovers."""
    coolify.write_json(coolify.CONFIG, {**coolify.read_json(coolify.CONFIG, {}), "ssh": "user@server"})
    coolify.save_to_registry("x", {"app_uuid": "a1", "db_uuid": "d1", "project_uuid": "p1"})
    calls, checks = [], iter([["container a1-123", "volume postgres-data-d1"], ["volume postgres-data-d1"], []])
    events = []
    monkeypatch.setattr(coolify, "api", _fake_delete_api(calls))
    monkeypatch.setattr(coolify, "_remote_leftovers", lambda target, uuids: events.append("check") or next(checks))
    monkeypatch.setattr(coolify.time, "sleep", lambda s: None)
    real_api = coolify.api
    monkeypatch.setattr(coolify, "api", lambda *a, **k: (events.append(a[:2]), real_api(*a, **k))[1])
    r = coolify.cmd_decommission(argparse.Namespace(app="x", confirmed=True, with_db=True, with_project=True))
    assert r["deleted"]["project"] == "p1" and "observed over ssh" in r["deleted"]["cleanup"]
    assert events.index(("DELETE", "/projects/p1")) > max(i for i, e in enumerate(events) if e == "check")


def test_decommission_keeps_project_if_cleanup_never_finishes(config, monkeypatch):
    coolify.write_json(coolify.CONFIG, {**coolify.read_json(coolify.CONFIG, {}), "ssh": "user@server"})
    coolify.save_to_registry("x", {"app_uuid": "a1", "project_uuid": "p1"})
    calls = []
    monkeypatch.setattr(coolify, "api", _fake_delete_api(calls))
    monkeypatch.setattr(coolify, "_remote_leftovers", lambda target, uuids: ["volume a1-data"])
    clock = iter(range(0, 10_000, 60))
    monkeypatch.setattr(coolify.time, "time", lambda: next(clock))
    monkeypatch.setattr(coolify.time, "sleep", lambda s: None)
    r = coolify.cmd_decommission(argparse.Namespace(app="x", confirmed=True, with_db=False, with_project=True))
    assert "project" not in r["deleted"] and "warning" in r["deleted"]
    assert ("DELETE", "/projects/p1") not in calls
