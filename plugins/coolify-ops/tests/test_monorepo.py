"""Repositories with several apps (phase 4): detection, app folders, commits and Coolify options."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "deploy-app" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analyze  # noqa: E402
import coolify  # noqa: E402
import repo  # noqa: E402

FASTAPI = {"requirements.txt": "fastapi\nuvicorn\n", "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"}
VITE = {"package.json": json.dumps({"scripts": {"build": "vite build"}, "devDependencies": {"vite": "^7"}}),
        "package-lock.json": "{}", "index.html": "<div id=app></div>", "src/main.js": "console.log(1)\n"}


def make(root: Path, files: dict) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


def under(prefix: str, files: dict) -> dict:
    return {f"{prefix}/{k}": v for k, v in files.items()}


def shop(root: Path) -> Path:
    return make(root / "shop", {**under("backend", FASTAPI), **under("frontend", VITE), "README.md": "# shop\n"})


@pytest.fixture
def git_repo(git_identity):
    def init(path: Path) -> Path:
        subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
        return path
    return init


# ---------------------------------------------------------------- detection

def test_backend_and_frontend_are_two_apps(tmp_path):
    r = analyze.analyze(shop(tmp_path))
    m = r["monorepo"]
    assert m["kind"] == "apps" and [a["path"] for a in m["apps"]] == ["backend", "frontend"]
    back, front = m["apps"]
    assert (back["template"], back["suggested_name"], back["deployable"]) == ("python-fastapi", "shop-backend", True)
    assert front["framework"] and front["suggested_name"] == "shop-frontend" and front["deployable"]
    assert not r["deployable"] and "deploy each from its folder" in " ".join(r["blockers"])


def test_folder_with_only_a_dockerfile_is_an_app(tmp_path):
    root = make(tmp_path, {"api/Dockerfile": "FROM golang\nEXPOSE 8080\n", "api/go.mod": "module api\n",
                           **under("web", VITE)})
    assert [a["path"] for a in analyze.analyze(root)["monorepo"]["apps"]] == ["api", "web"]


@pytest.mark.parametrize("extra", [
    {"e2e/package.json": "{}", "infra/package.json": "{}"},                  # helper folders
    {"client/package.json": json.dumps({"scripts": {"build": "react-scripts build"}})},  # MERN: one folder
    {"templates/index.html": "<h1>x</h1>", "static/index.html": "x"},        # build inputs, not apps
    {"docker/php/Dockerfile": "FROM php\n", "docker/nginx/Dockerfile": "FROM nginx\n"},
])
def test_root_app_with_helper_folders_stays_a_single_app(tmp_path, extra):
    root = make(tmp_path, {"package.json": json.dumps({"dependencies": {"express": "^4"}, "scripts": {"start": "node s.js"}}),
                           "package-lock.json": "{}", "s.js": "require('express')().listen(3000)\n", **extra})
    r = analyze.analyze(root)
    assert "monorepo" not in r, r.get("monorepo")


def test_root_app_plus_several_app_folders_is_blocked(tmp_path):
    root = make(tmp_path, {**FASTAPI, **under("client", VITE), **under("admin", VITE)})
    r = analyze.analyze(root)
    assert r["monorepo"]["kind"] == "mixed" and "move the root app into its own folder" in " ".join(r["blockers"])


def test_index_html_in_sources_is_not_an_app(tmp_path):
    root = make(tmp_path, {**under("api", FASTAPI), "web/package.json": json.dumps({"scripts": {"build": "ng build"}}),
                           "web/src/index.html": "<app-root>", "site/index.html": "<h1>x</h1>"})
    assert [a["path"] for a in analyze.analyze(root)["monorepo"]["apps"]] == ["api", "site", "web"]


# ---------------------------------------------------------------- workspaces and compose

@pytest.mark.parametrize("files", [
    {"package.json": json.dumps({"workspaces": ["apps/*"]})},
    {"turbo.json": "{}"},
    {"pnpm-workspace.yaml": "packages:\n  - 'apps/*'\n  - \"packages/*\" # libs\n"},
    {"pnpm-workspace.yaml": "packages: [\"apps/*\", 'libs/*']\n"},
    {"pyproject.toml": "[project]\nname='x'\n[tool.uv.workspace]\nmembers=['apps/*']\n"},
])
def test_workspaces_are_blocked(tmp_path, files):
    r = analyze.analyze(make(tmp_path, {**files, **under("apps/web", VITE)}))
    assert r["monorepo"]["kind"] == "workspaces" and not r["deployable"]


@pytest.mark.parametrize("text", ["onlyBuiltDependencies:\n  - esbuild\n", "packages:\n  - '.'\n"])
def test_pnpm_settings_file_is_not_a_workspace(tmp_path, text):
    r = analyze.analyze(make(tmp_path, {**VITE, "pnpm-workspace.yaml": text}))
    assert "monorepo" not in r and r["deployable"], r["blockers"]


def test_workspace_member_analysed_directly_is_blocked(tmp_path, git_repo):
    root = git_repo(make(tmp_path / "mono", {"turbo.json": "{}", **under("apps/web", VITE)}))
    r = analyze.analyze(root / "apps" / "web")
    assert r["monorepo"]["kind"] == "workspaces" and not r["deployable"]


def test_compose_build_folders_are_apps(tmp_path):
    compose = "services:\n  api:\n    build: ./api\n  web:\n    build:\n      context: ./web\n  db:\n    image: postgres\n"
    root = make(tmp_path, {"compose.yaml": compose, "api/main.go": "package main\n", **under("web", VITE)})
    assert [a["path"] for a in analyze.analyze(root)["monorepo"]["apps"]] == ["api", "web"]


def test_one_service_compose_and_image_only_services_do_not_block(tmp_path):
    compose = "services:\n  app:\n    build: .\n  db:\n    image: postgres\n  cache:\n    image: valkey\n"
    r = analyze.analyze(make(tmp_path, {**VITE, "docker-compose.yml": compose}))
    assert "monorepo" not in r and r["deployable"], r["blockers"]


def test_sail_build_context_in_vendor_is_not_an_app():
    sail = "services:\n    laravel.test:\n        build:\n            context: ./vendor/laravel/sail/runtimes/8.4\n"
    assert analyze.compose_builds(sail) == {"laravel.test": "vendor/laravel/sail/runtimes/8.4"}


# ---------------------------------------------------------------- app folder

def test_app_folder_inside_a_repository_has_git(tmp_path, git_repo):
    root = git_repo(shop(tmp_path))
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", "https://github.com/someone/shop.git"], check=True)
    r = analyze.analyze(root / "backend")
    g = r["git"]
    assert (g["remote"], g["root"], g["subdir"]) == ("someone/shop", str(root.resolve()), "backend/")
    assert r["suggested_name"] == "shop-backend" and r["deployable"], r["blockers"]
    assert {str(f.relative_to(root / "backend")) for f in analyze.project_files(root / "backend")} == set(FASTAPI)


def test_long_and_nested_names_are_cut(tmp_path, git_repo):
    root = git_repo(make(tmp_path / ("x" * 60), under("apps/web", VITE)))
    name = analyze.analyze(root / "apps" / "web")["suggested_name"]
    assert len(name) <= 63 and not name.endswith("-") and "/" not in name


def test_folder_name_coolify_rejects_is_blocked(tmp_path, git_repo):
    root = git_repo(make(tmp_path / "r", under("Web App", VITE)))
    assert "rename it" in " ".join(analyze.analyze(root / "Web App")["blockers"])


@pytest.mark.parametrize("files", [
    {"package.json": json.dumps({"dependencies": {"shared": "file:../shared"}})},
    {"package.json": json.dumps({"dependencies": {"shared": "../shared"}})},
    {"package.json": json.dumps({"dependencies": {"ui": "workspace:*"}})},
    {"requirements.txt": "fastapi\n-e ../lib\n", "main.py": "x"},
])
def test_imports_from_outside_the_folder_are_blocked(tmp_path, files):
    r = analyze.analyze(make(tmp_path / "app", files))
    assert "imports code from outside its folder" in " ".join(r["blockers"])


def test_siblings_without_git_warn_only_in_a_repository_like_parent(tmp_path):
    root = shop(tmp_path)
    assert any("holds other apps (frontend)" in w for w in analyze.analyze(root / "backend")["warnings"])
    (root / "README.md").unlink()  # a plain folder of projects
    assert not any("holds other apps" in w for w in analyze.analyze(root / "backend")["warnings"])


# ---------------------------------------------------------------- repo.py

def commit(path: Path, **kw):
    import argparse
    return repo.cmd_commit(argparse.Namespace(path=str(path), message="x", **{"all": False, "files": None, **kw}))


def test_commit_all_from_an_app_folder_scans_the_whole_repository(tmp_path, git_repo):
    root = git_repo(shop(tmp_path))
    make(root, {"frontend/config.js": "const k = 'ghp_" + "a" * 36 + "'\n"})
    r = commit(root / "backend", all=True)
    assert not r["ok"] and r["secrets"][0]["file"] == "frontend/config.js"


def test_commit_files_refuses_a_secret_already_staged_elsewhere(tmp_path, git_repo):
    root = git_repo(shop(tmp_path))
    make(root, {"frontend/config.js": "const k = 'ghp_" + "a" * 36 + "'\n", "backend/Dockerfile": "FROM python\n"})
    subprocess.run(["git", "-C", str(root), "add", "frontend/config.js"], check=True)
    r = commit(root / "backend", files=["Dockerfile"])
    assert not r["ok"] and r["secrets"][0]["file"] == "frontend/config.js"


def test_init_at_a_repository_with_several_apps_ignores_each_build_output(tmp_path, git_identity):
    import argparse
    root = shop(tmp_path)
    r = repo.cmd_init(argparse.Namespace(path=str(root)))
    assert r["ignored_build_output"] == ["frontend/dist/"]
    assert "frontend/dist/" in (root / ".gitignore").read_text()


# ---------------------------------------------------------------- coolify.py

def create_args(**kw):
    import argparse
    base = dict(project="p", repo="o/shop", branch="main", port="8000", domain="shop-backend", name="shop-backend",
                environment="production", cpus=None, memory=None, dockerfile=None, base_dir=None, watch_paths=None,
                no_autodeploy=False, env_domain=None)
    return argparse.Namespace(**{**base, **kw})


def fake_api(calls):
    def fake(method, path, body=None, query=None):
        calls.append((method, path, body))
        return [] if method == "GET" else {"uuid": "k" * 24}
    return fake


def test_create_app_sends_base_directory_and_watch_paths(config, monkeypatch):
    calls = []
    monkeypatch.setattr(coolify, "api", fake_api(calls))
    coolify.cmd_create_app(create_args(base_dir="/backend", watch_paths=["backend/**", "!backend/docs/**"]))
    body = next(b for m, p, b in calls if m == "POST")
    assert (body["base_directory"], body["watch_paths"]) == ("/backend", "backend/**\n!backend/docs/**")
    assert coolify.registry()["shop-backend"]["base_dir"] == "/backend"


@pytest.mark.parametrize("kw", [{"base_dir": "/Web App"}, {"base_dir": "/../x"}, {"base_dir": "backend"},
                                {"watch_paths": ["a;b"]}, {"watch_paths": ["../x/**"]}, {"dockerfile": "/a b"}])
def test_bad_paths_are_rejected_before_any_call(config, monkeypatch, kw):
    calls = []
    monkeypatch.setattr(coolify, "api", fake_api(calls))
    with pytest.raises(coolify.Error, match="Invalid paths"):
        coolify.cmd_create_app(create_args(**kw))
    assert calls == []


def test_decommission_keeps_a_project_other_apps_still_use(config, monkeypatch):
    import argparse
    coolify.save_to_registry("shop-backend", {"app_uuid": "a" * 24, "project_uuid": "p1"})
    coolify.save_to_registry("shop-frontend", {"app_uuid": "b" * 24, "project_uuid": "p1"})
    deleted = []
    monkeypatch.setattr(coolify, "api", lambda m, p, body=None, query=None: deleted.append(p) if m == "DELETE" else {})
    monkeypatch.setattr(coolify, "_wait_until_gone", lambda p: True)
    monkeypatch.setattr(coolify, "_wait_for_cleanup", lambda uuids: (True, "watched"))
    args = dict(confirmed=True, with_db=False, with_project=True)
    r = coolify.cmd_decommission(argparse.Namespace(app="shop-backend", **args))
    assert "/projects/p1" not in deleted and "shop-frontend" in r["deleted"]["project_kept"]
    r = coolify.cmd_decommission(argparse.Namespace(app="shop-frontend", **args))
    assert "/projects/p1" in deleted and r["deleted"]["project"] == "p1"


def test_state_of_an_app_folder_without_git_warns_about_the_parent(tmp_path):
    import argparse
    r = repo.cmd_state(argparse.Namespace(path=str(shop(tmp_path) / "backend")))
    assert not r["is_repo"] and "holds other apps (frontend)" in r["parent_warning"]


def test_state_reports_the_repository_root(tmp_path, git_repo):
    import argparse
    root = git_repo(shop(tmp_path))
    assert repo.cmd_state(argparse.Namespace(path=str(root / "backend")))["root"] == str(root.resolve())


def test_a_repository_at_the_home_folder_blocks(tmp_path, git_repo, monkeypatch):
    home = git_repo(tmp_path / "home")
    make(home, under("projects/site", VITE))
    monkeypatch.setattr(analyze.Path, "home", lambda: home)
    assert "at your home folder" in " ".join(analyze.analyze(home / "projects" / "site")["blockers"])


def test_no_parent_warning_in_the_home_folder(tmp_path, monkeypatch):
    root = shop(tmp_path)
    monkeypatch.setattr(analyze.Path, "home", lambda: root)
    assert analyze.parent_apps_warning(root / "backend") is None


def test_paths_spelled_with_another_case_work(tmp_path, git_repo):
    """On case-insensitive file systems (macOS) the user may type «personal» where git says «Personal»."""
    root = git_repo(shop(tmp_path / "Projects"))
    other = Path(str(root).replace("/Projects/", "/projects/"))
    if not other.exists():
        pytest.skip("case-sensitive file system")
    make(root, {"backend/Dockerfile": "FROM python\n"})
    assert commit(other / "backend", files=["Dockerfile"])["committed"]
    assert analyze.analyze(other / "backend")["git"]["subdir"] == "backend/"
