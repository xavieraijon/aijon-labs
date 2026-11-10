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
import repo  # noqa: E402
import verify  # noqa: E402

# ------------------------------------------------------------------ helpers

APP_UUID = "k" * 24  # shaped like a Coolify uuid


def make(root: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


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
                        lambda app, k, v, secret, **_: calls.append((k, v, secret)) or {"key": k, "action": "created"})
    f = make(tmp_path, {"vars.env": "# comment\nDATABASE_URL=postgres://a:b@c/d\nexport NEXT_PUBLIC_URL='https://x'\n\n"})
    r = coolify.cmd_env_push(argparse.Namespace(app=APP_UUID, file=str(f / "vars.env"), only=None))
    assert r["ok"]
    assert ("DATABASE_URL", "postgres://a:b@c/d", True) in calls
    assert ("NEXT_PUBLIC_URL", "https://x", False) in calls
    assert "postgres://a:b@c/d" not in json.dumps(r)     # values never appear in the output


def test_destructive_commands_require_confirmation(config):
    with pytest.raises(coolify.Error):
        coolify.cmd_decommission(argparse.Namespace(app="x", confirmed=False, with_db=False, with_project=False))
    with pytest.raises(coolify.Error):
        coolify.cmd_rollback(argparse.Namespace(app=APP_UUID, confirmed=False, image="def"))
    with pytest.raises(coolify.Error):
        coolify.cmd_env_delete(argparse.Namespace(app="x", key="A", confirmed=False))


def test_env_push_never_uploads_empty_values(config, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(coolify, "_set_env",
                        lambda app, k, v, secret, **_: calls.append(k) or {"key": k, "action": "updated"})
    f = make(tmp_path, {"vars.env": "DATABASE_URL=\nAPI_KEY=''\nSTRIPE_KEY=sk_test_x\n"})
    r = coolify.cmd_env_push(argparse.Namespace(app=APP_UUID, file=str(f / "vars.env"), only=None))
    assert calls == ["STRIPE_KEY"]                       # DATABASE_URL set by create-postgres stays intact
    assert r["skipped_empty"] == ["DATABASE_URL", "API_KEY"]


def test_env_template_creates_private_file_and_keeps_values(config):
    secrets = config / "secrets" / "shop.env"
    r = coolify.cmd_env_template(argparse.Namespace(app="shop", keys=["API_KEY", "MAIL_FROM"]))
    assert r["added"] == ["API_KEY", "MAIL_FROM"] and r["empty"] == ["API_KEY", "MAIL_FROM"]
    assert secrets.stat().st_mode & 0o777 == 0o600 and secrets.parent.stat().st_mode & 0o777 == 0o700
    secrets.write_text("API_KEY=filled-in\nMAIL_FROM=\n")
    r = coolify.cmd_env_template(argparse.Namespace(app="shop", keys=["API_KEY", "SENTRY_DSN"]))
    assert r["added"] == ["SENTRY_DSN"] and r["already_present"] == ["API_KEY"]
    assert "API_KEY=filled-in" in secrets.read_text()   # existing values are never touched
    assert "filled-in" not in json.dumps(r)
    with pytest.raises(coolify.Error):
        coolify.cmd_env_template(argparse.Namespace(app="../x", keys=["A"]))
    with pytest.raises(coolify.Error):
        coolify.cmd_env_template(argparse.Namespace(app="shop", keys=["BAD-NAME"]))


def test_registry_resolves_names(config, monkeypatch):
    coolify.save_to_registry("shop", {"app_uuid": "u-123"})
    assert coolify.resolve_app("shop") == "u-123"
    assert coolify.resolve_app(APP_UUID) == APP_UUID      # uuids pass through without an API call


def test_names_missing_from_the_registry_are_looked_up_on_the_server(config, monkeypatch):
    monkeypatch.setattr(coolify, "_apps", lambda: [{"name": "blog", "uuid": APP_UUID},
                                                   {"name": "twin", "uuid": "a" * 24}, {"name": "twin", "uuid": "b" * 24}])
    assert coolify.resolve_app("blog") == APP_UUID
    with pytest.raises(coolify.Error, match="No app named"):
        coolify.resolve_app("ghost")
    with pytest.raises(coolify.Error, match="Several apps"):
        coolify.resolve_app("twin")


def test_rollback_lists_without_confirmation_and_sends_commit(config, monkeypatch):
    calls = []

    def fake_api(method, path, body=None, query=None):
        calls.append((method, path, body))
        if method == "GET":
            return {"current": "abc", "images": [{"tag": "abc", "is_current": True}, {"tag": "def", "is_current": False}]}
        return {"message": "queued", "deployment_uuid": "dep-1"}
    monkeypatch.setattr(coolify, "api", fake_api)
    listed = coolify.cmd_rollback(argparse.Namespace(app=APP_UUID, confirmed=False, image=None))
    assert listed["current"] == "abc" and len(listed["images"]) == 2
    done = coolify.cmd_rollback(argparse.Namespace(app=APP_UUID, confirmed=True, image="def"))
    assert calls[-1] == ("POST", f"/applications/{APP_UUID}/rollback", {"commit": "def"})   # Coolify 4.6 accepts only «commit»
    assert done["deployment_uuid"] == "dep-1"


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
    monkeypatch.setattr(coolify, "_configs", lambda db: [])
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
    assert any("workspaces (nx.json)" in b for b in r["blockers"])


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


def test_own_dockerfile_makes_an_untemplated_framework_deployable(tmp_path):
    make(tmp_path, {"requirements.txt": "django\n", "Dockerfile": "FROM x\nEXPOSE 8000\n"})
    r = analyze.analyze(tmp_path)
    assert r["deployable"] and "warning_framework" not in r["stack"]
    assert any("own Dockerfile is used as is" in w for w in r["warnings"])
    make(tmp_path / "plain", {"requirements.txt": "django\n"})
    assert not analyze.analyze(tmp_path / "plain")["deployable"]     # without a Dockerfile it still stops


def test_databases_other_than_postgres_block(tmp_path):
    make(tmp_path, {"package.json": json.dumps({"dependencies": {"express": "4", "mongoose": "8", "pg": "8"}})})
    r = analyze.analyze(tmp_path)
    assert set(r["databases"]) == {"postgresql", "mongodb"}
    assert not r["deployable"] and any("mongodb" in b and "only PostgreSQL" in b for b in r["blockers"])


# ------------------------------------------------------------------ prepare.py


def test_render_detects_missing_values():
    assert prepare.render("FROM node:{{NODE_VERSION}}", {"NODE_VERSION": "22"}) == "FROM node:22"
    with pytest.raises(ValueError):
        prepare.render("EXPOSE {{PORT}}", {})


def test_prepare_declares_arg_for_build_time_variables(tmp_path, monkeypatch):
    make(tmp_path, {"package.json": json.dumps({"scripts": {"build": "vite build"}, "devDependencies": {"vite": "^6"}}),
                    "package-lock.json": "{}", "index.html": "<div></div>",
                    "src/main.js": "fetch(import.meta.env.VITE_API_URL)\n",
                    ".env.example": "VITE_API_URL=http://localhost\n"})
    analysis = analyze.analyze(tmp_path)
    assert analysis["build_time_candidates"] == ["VITE_API_URL"]
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(tmp_path)])
    prepare.main()
    assert (tmp_path / "Dockerfile").read_text().count("ARG VITE_API_URL") == 2  # once per stage (build, nginx)


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
    monkeypatch.setattr(coolify, "_configs", lambda db: [])
    monkeypatch.setattr(coolify, "_remove_app_images", lambda target, uuid: events.append(("images", uuid)) or 1)
    monkeypatch.setattr(coolify.time, "sleep", lambda s: None)
    real_api = coolify.api
    monkeypatch.setattr(coolify, "api", lambda *a, **k: (events.append(a[:2]), real_api(*a, **k))[1])
    r = coolify.cmd_decommission(argparse.Namespace(app="x", confirmed=True, with_db=True, with_project=True))
    assert r["deleted"]["project"] == "p1" and "observed over ssh" in r["deleted"]["cleanup"]
    assert events.index(("DELETE", "/projects/p1")) > max(i for i, e in enumerate(events) if e == "check")
    assert ("images", "a1") in events and r["deleted"]["images"] == 1


def test_decommission_keeps_project_if_cleanup_never_finishes(config, monkeypatch):
    coolify.write_json(coolify.CONFIG, {**coolify.read_json(coolify.CONFIG, {}), "ssh": "user@server"})
    coolify.save_to_registry("x", {"app_uuid": "a1", "project_uuid": "p1"})
    calls = []
    monkeypatch.setattr(coolify, "api", _fake_delete_api(calls))
    monkeypatch.setattr(coolify, "_remote_leftovers", lambda target, uuids: ["volume a1-data"])
    monkeypatch.setattr(coolify, "_remove_app_images", lambda *a: pytest.fail("images removed before cleanup"))
    clock = iter(range(0, 10_000, 60))
    monkeypatch.setattr(coolify.time, "time", lambda: next(clock))
    monkeypatch.setattr(coolify.time, "sleep", lambda s: None)
    r = coolify.cmd_decommission(argparse.Namespace(app="x", confirmed=True, with_db=False, with_project=True))
    assert "project" not in r["deleted"] and "warning" in r["deleted"]
    assert ("DELETE", "/projects/p1") not in calls


def test_remove_app_images_rejects_unsafe_uuids(monkeypatch):
    monkeypatch.setattr(coolify.subprocess, "run", lambda *a, **k: pytest.fail("ssh must not run"))
    for bad in ("x; rm -rf /", "UPPER", "a1", "$(id)", "abc def ghi jkl mno"):
        assert coolify._remove_app_images("user@server", bad) is None


# ------------------------------------------------------------------ coolify.py (0.2.1)


def test_env_push_only_uploads_the_named_keys(config, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(coolify, "_set_env", lambda app, k, v, secret, **_: calls.append(k) or {"key": k, "action": "created"})
    f = make(tmp_path, {"vars.env": "OLD_KEY=value-changed-in-the-panel-since\nSENTRY_DSN=https://k@sentry.example.org/1\n"})
    coolify.cmd_env_push(argparse.Namespace(app=APP_UUID, file=str(f / "vars.env"), only=["SENTRY_DSN"]))
    assert calls == ["SENTRY_DSN"]
    with pytest.raises(coolify.Error, match="Not in"):
        coolify.cmd_env_push(argparse.Namespace(app=APP_UUID, file=str(f / "vars.env"), only=["MISSING"]))


def test_protect_stores_the_password_locally_and_never_prints_it(config, monkeypatch):
    sent = []
    monkeypatch.setattr(coolify, "api", lambda method, path, body=None, query=None: sent.append(body) or {})
    coolify.save_to_registry("shop", {"app_uuid": APP_UUID})
    r = coolify.cmd_protect(argparse.Namespace(app="shop", user="admin", off=False))
    password = sent[0]["http_basic_auth_password"]
    assert sent[0]["is_http_basic_auth_enabled"] is True and len(password) <= 72      # Coolify's limit
    assert password not in json.dumps(r)
    creds = config / "secrets" / "shop.access"
    assert password in creds.read_text() and creds.stat().st_mode & 0o777 == 0o600
    coolify.cmd_protect(argparse.Namespace(app="shop", user="admin", off=True))
    assert sent[-1] == {"is_http_basic_auth_enabled": False}


def test_decommission_refuses_before_deleting_when_db_is_unknown(config, monkeypatch):
    calls = []
    monkeypatch.setattr(coolify, "api", lambda method, path, body=None, query=None: calls.append((method, path)) or {})
    with pytest.raises(coolify.Error, match="nothing was deleted"):
        coolify.cmd_decommission(argparse.Namespace(app=APP_UUID, confirmed=True, with_db=True, with_project=False))
    assert not [c for c in calls if c[0] == "DELETE"]


def test_decommission_finds_the_registry_entry_by_uuid(config, monkeypatch):
    coolify.save_to_registry("shop", {"app_uuid": APP_UUID, "db_uuid": "d" * 24, "project_uuid": "p" * 24})
    deleted = []
    monkeypatch.setattr(coolify, "api", lambda method, path, body=None, query=None:
                        deleted.append(path) if method == "DELETE" else {})
    monkeypatch.setattr(coolify, "_wait_until_gone", lambda path: True)
    monkeypatch.setattr(coolify, "_wait_for_cleanup", lambda uuids: (True, "watched"))
    coolify.cmd_decommission(argparse.Namespace(app=APP_UUID, confirmed=True, with_db=True, with_project=True))
    assert deleted == [f"/applications/{APP_UUID}", f"/databases/{'d' * 24}", f"/projects/{'p' * 24}"]
    assert "shop" not in coolify.registry()


def test_decommission_removes_the_apps_local_secrets(config, monkeypatch):
    coolify.save_to_registry("shop", {"app_uuid": APP_UUID})
    secrets = config / "secrets"
    secrets.mkdir()
    for name in ("shop.env", "shop.access", "blog.env"):
        (secrets / name).write_text("X=1\n")
    monkeypatch.setattr(coolify, "api", lambda method, path, body=None, query=None: {})
    monkeypatch.setattr(coolify, "_wait_until_gone", lambda path: True)
    monkeypatch.setattr(coolify, "_wait_for_cleanup", lambda uuids: (True, "watched"))
    r = coolify.cmd_decommission(argparse.Namespace(app="shop", confirmed=True, with_db=False, with_project=False))
    assert sorted(Path(f).name for f in r["deleted"]["local_files"]) == ["shop.access", "shop.env"]
    assert [f.name for f in secrets.iterdir()] == ["blog.env"]                     # other apps untouched


# ------------------------------------------------------------------ repo.py (local git only, no network)


def test_repo_init_commit_and_state_of_a_new_project(tmp_path, git_identity):
    make(tmp_path, {"package.json": "{}", "index.js": "x", "node_modules/a/i.js": "x", ".env": "SENDGRID_KEY=real\n"})
    ns = argparse.Namespace
    r = repo.cmd_init(ns(path=str(tmp_path)))
    assert r["created_gitignore"] and ".env" in (tmp_path / ".gitignore").read_text()
    assert repo.cmd_state(ns(path=str(tmp_path)))["to_push"] == []
    r = repo.cmd_commit(ns(path=str(tmp_path), message="initial commit", all=True, files=None))
    assert r["committed"]
    tracked = repo.git(tmp_path, "ls-files").splitlines()
    assert "index.js" in tracked and ".env" not in tracked and not any(t.startswith("node_modules") for t in tracked)
    state = repo.cmd_state(ns(path=str(tmp_path)))
    assert state["branch"] == "main" and not state["has_upstream"] and len(state["to_push"]) == 1   # no @{u} needed
    with pytest.raises(repo.Error):
        repo.cmd_init(ns(path=str(tmp_path)))                                        # already a repository


def test_repo_commit_refuses_secrets(tmp_path, git_identity):
    make(tmp_path, {"app.py": 'KEY = "sk_live_' + "a" * 24 + '"\n'})
    repo.cmd_init(argparse.Namespace(path=str(tmp_path)))
    r = repo.cmd_commit(argparse.Namespace(path=str(tmp_path), message="x", all=True, files=None))
    assert not r["ok"] and r["secrets"][0]["file"] == "app.py"
    assert not repo.git(tmp_path, "rev-parse", "--verify", "-q", "HEAD", check=False)  # nothing committed


def test_repo_script_has_no_push():
    sub = next(a for a in repo.parser()._actions if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == {"state", "init", "commit"}
    assert '"push"' not in Path(repo.__file__).read_text()                      # never calls git push


def test_repo_commit_only_the_given_files(tmp_path, git_identity):
    make(tmp_path, {"index.js": "x", "Dockerfile": "FROM x\n"})
    repo.cmd_init(argparse.Namespace(path=str(tmp_path)))
    r = repo.cmd_commit(argparse.Namespace(path=str(tmp_path), message="build", all=False, files=["Dockerfile"]))
    assert r["committed"] and repo.git(tmp_path, "ls-files").splitlines() == ["Dockerfile"]
    with pytest.raises(repo.Error, match="not found"):
        repo.cmd_commit(argparse.Namespace(path=str(tmp_path), message="x", all=False, files=["nginx.conf"]))


def test_repo_state_never_prints_credentials_in_the_remote(tmp_path, git_identity):
    repo.cmd_init(argparse.Namespace(path=str(tmp_path)))
    repo.git(tmp_path, "remote", "add", "origin", "https://bob:s3cr3t-token@git.example.org/team/app.git")
    state = repo.cmd_state(argparse.Namespace(path=str(tmp_path)))
    assert "s3cr3t" not in json.dumps(state) and state["remote"] == "https://git.example.org/team/app.git"
    repo.git(tmp_path, "remote", "set-url", "origin", "git@github.com:someone/my.site.git")
    assert repo.cmd_state(argparse.Namespace(path=str(tmp_path)))["remote"] == "someone/my.site"   # dots allowed


def test_verify_accepts_401_only_for_protected_apps():
    assert verify.answered_ok(200) and verify.answered_ok(302) and not verify.answered_ok(401)
    assert verify.answered_ok(401, protected=True) and not verify.answered_ok(200, protected=True)  # must be locked
    assert verify.external_ok({"is1": "401", "pl2": None}, protected=True)
    assert not verify.external_ok({"is1": "401"})


# ------------------------------------------------------------------ 0.3.0: domain env, build-time env, markers


def _create_app_args(**kw):
    base = dict(project="p", repo="o/r", branch="main", port="4000", domain="web", name="web", environment="production",
                cpus=None, memory=None, dockerfile=None, base_dir=None, no_autodeploy=False, env_domain=None)
    return argparse.Namespace(**{**base, **kw})


def _fake_create_api(calls, fail_envs=False):
    def fake(method, path, body=None, query=None):
        calls.append((method, path, body))
        if path == "/applications" or path.endswith("/envs") and method == "GET":
            return []
        if path.endswith("/envs") and fail_envs:
            raise coolify.Error("HTTP 500")
        return {"uuid": APP_UUID}
    return fake


def test_create_app_sets_domain_envs_as_runtime_only(config, monkeypatch):
    calls = []
    monkeypatch.setattr(coolify, "api", _fake_create_api(calls))
    r = coolify.cmd_create_app(_create_app_args(env_domain=["NG_ALLOWED_HOSTS"]))
    assert r["ok"] and r["env_domain"] == ["NG_ALLOWED_HOSTS"] and r["env_errors"] == []
    env = next(b for m, p, b in calls if m == "POST" and p.endswith("/envs"))
    assert (env["key"], env["value"], env["is_buildtime"], env["is_runtime"]) == ("NG_ALLOWED_HOSTS", "web.example.org",
                                                                                  False, True)


def test_create_app_keeps_the_uuid_when_the_env_fails(config, monkeypatch):
    monkeypatch.setattr(coolify, "api", _fake_create_api([], fail_envs=True))
    r = coolify.cmd_create_app(_create_app_args(env_domain=["NG_ALLOWED_HOSTS"]))
    assert r["ok"] and r["app_uuid"] == APP_UUID
    assert r["env_errors"][0]["key"] == "NG_ALLOWED_HOSTS"
    assert coolify.registry()["web"]["app_uuid"] == APP_UUID


def test_create_app_rejects_bad_env_names_before_creating(config, monkeypatch):
    calls = []
    monkeypatch.setattr(coolify, "api", _fake_create_api(calls))
    with pytest.raises(coolify.Error):
        coolify.cmd_create_app(_create_app_args(env_domain=["BAD-KEY"]))
    assert not [c for c in calls if c[0] == "POST"]


def test_env_domain_uses_the_apps_own_domain(config, monkeypatch):
    sent = []

    def fake(method, path, body=None, query=None):
        if method == "GET" and path == f"/applications/{APP_UUID}":
            return {"fqdn": "https://shop.example.org,https://www.shop.example.org"}
        if method == "POST":
            sent.append(body)
        return []
    monkeypatch.setattr(coolify, "api", fake)
    r = coolify.cmd_env_domain(argparse.Namespace(app=APP_UUID, keys=["NG_ALLOWED_HOSTS"]))
    assert r["ok"] and r["host"] == "shop.example.org"
    assert sent[0]["value"] == "shop.example.org"


def test_env_push_buildtime_keeps_secrets_hidden(config, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(coolify, "_set_env", lambda app, k, v, secret, buildtime=None:
                        calls.append((k, secret, buildtime)) or {"key": k, "action": "created"})
    f = make(tmp_path, {"vars.env": "DB_URL=x\nOTHER=y\n"})
    r = coolify.cmd_env_push(argparse.Namespace(app=APP_UUID, file=str(f / "vars.env"), only=None, buildtime=["DB_URL"]))
    assert ("DB_URL", True, True) in calls and ("OTHER", True, False) in calls
    assert {v["key"]: v["buildtime"] for v in r["variables"]} == {"DB_URL": True, "OTHER": False}


def test_set_env_secret_at_build_time(config, monkeypatch):
    sent = []
    monkeypatch.setattr(coolify, "api", lambda method, path, body=None, query=None: sent.append(body) or [])
    coolify._set_env(APP_UUID, "DB_URL", "x", secret=True, buildtime=True)
    body = sent[-1]
    assert (body["is_buildtime"], body["is_runtime"], body["is_shown_once"]) == (True, True, True)


def test_local_check_adds_args_after_every_from():
    import local_check
    out = local_check.with_build_args("FROM node:22 AS build\nRUN x\nfrom nginx\nCOPY a b\n", ["A", "B"])
    assert out == "FROM node:22 AS build\nARG A\nARG B\nRUN x\nfrom nginx\nARG A\nARG B\nCOPY a b\n"


def test_verify_expect_marker(monkeypatch, capsys):
    monkeypatch.setattr(verify, "certificate", lambda host: {"valid": True})
    monkeypatch.setattr(verify, "fetch", lambda url, follow=True: (301, "https://x/") if not follow else (200, ""))
    for page, protected, expected in (("<app-root ng-server-context=\"ssr\">", False, True),
                                      ("<app-root></app-root>", False, False), ("", True, None)):
        monkeypatch.setattr(verify, "body", lambda url, page=page: page)
        argv = ["verify.py", "https://web.example.org", "--expect", "ng-server-context"] + (["--protected"] * protected)
        monkeypatch.setattr(sys, "argv", argv)
        verify.main()
        res = json.loads(capsys.readouterr().out)
        assert res["marker_found"] == expected
        if expected is False:
            assert res["ok"] is False


def test_init_ignores_the_build_output_only_when_the_image_builds_it(tmp_path):
    sk = make(tmp_path / "sk", {"package.json": json.dumps({"devDependencies": {"@sveltejs/kit": "^3"}}),
                                "svelte.config.js": "import a from '@sveltejs/adapter-node'\nexport default {}"})
    assert repo.build_output(sk) == ["build/"]
    ng = make(tmp_path / "ng", {"package.json": json.dumps({"dependencies": {"@angular/core": "^20"}}),
                                "angular.json": json.dumps({"projects": {"w": {"architect": {"build": {
                                    "builder": "@angular/build:application", "options": {"outputPath": "dist/w"}}}}}})})
    assert repo.build_output(ng) == ["dist/"]
    nuxt = make(tmp_path / "nuxt", {"package.json": json.dumps({"dependencies": {"nuxt": "^4"}})})
    assert repo.build_output(nuxt) == []                       # .output/ is already in the base .gitignore
    site = make(tmp_path / "site", {"index.html": "<h1>x</h1>", "build/logo.png": "x"})
    assert repo.build_output(site) == []                       # static-nginx copies build/ as is: keep it


def test_create_postgres_buildtime_flag(config, monkeypatch):
    calls = []
    monkeypatch.setattr(coolify, "api", lambda method, path, body=None, query=None: {"uuid": "d" * 24})
    monkeypatch.setattr(coolify, "_set_env", lambda app, k, v, secret, buildtime=None:
                        calls.append((k, secret, buildtime)) or {})
    for flag in (False, True):
        coolify.cmd_create_postgres(argparse.Namespace(project="p", name="blog", app="blog", app_uuid=APP_UUID,
                                                       environment="production", image="postgres:17-alpine",
                                                       memory="512m", buildtime=flag))
    assert calls == [("DATABASE_URL", True, False), ("DATABASE_URL", True, True)]


def test_env_push_reports_buildtime_keys_missing_from_the_file(config, monkeypatch, tmp_path):
    monkeypatch.setattr(coolify, "_set_env", lambda *a, **k: {"key": a[1], "action": "created"})
    f = make(tmp_path, {"vars.env": "API_KEY=x\n"})
    r = coolify.cmd_env_push(argparse.Namespace(app=APP_UUID, file=str(f / "vars.env"), only=None,
                                                buildtime=["API_KEY", "DATABASE_URL"]))
    assert r["buildtime_not_in_file"] == ["DATABASE_URL"]


def test_extra_env_override_is_validated():
    assert prepare.values({"stack": {}}, {"EXTRA_ENV": " A=x B=y/z"})["EXTRA_ENV"] == " A=x B=y/z"
    for bad in (" A=x\nRUN id", "A=x", " A", " A=x;y", " BAD-KEY=x"):
        with pytest.raises(ValueError):
            prepare.values({"stack": {}}, {"EXTRA_ENV": bad})


# ------------------------------------------------------------------ local_check.py (docker mocked)


class _Done:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


@pytest.fixture
def docker(monkeypatch):
    import local_check
    calls, files = [], {}

    def fake_run(*cmd, timeout=None):
        calls.append(cmd)
        if cmd[:2] == ("docker", "build") and "-f" in cmd:
            files["dockerfile"] = Path(cmd[cmd.index("-f") + 1]).read_text()
            files["path"] = cmd[cmd.index("-f") + 1]
        return _Done()
    monkeypatch.setattr(local_check, "run", fake_run)
    monkeypatch.setattr(local_check, "fetch", lambda url: (200, "text/html"))
    monkeypatch.setattr(local_check.time, "sleep", lambda s: None)
    return local_check, calls, files


def test_local_check_build_env_and_cleanup(tmp_path, docker, monkeypatch, capsys):
    local_check, calls, files = docker
    make(tmp_path, {"Dockerfile": "FROM node:22 AS build\nRUN npm run build\nFROM node:22\nCMD x\n"})
    monkeypatch.setattr(local_check, "body", lambda url: '<app-root ng-server-context="ssr">')
    with pytest.raises(SystemExit) as e:
        local_check.main([str(tmp_path), "--port", "3000", "--build-env", "DB_URL=test", "--expect", "ng-server-context"])
    res = json.loads(capsys.readouterr().out)
    assert e.value.code == 0 and res["ok"] and res["marker_found"] and res["cleaned_up"]
    build = next(c for c in calls if c[:2] == ("docker", "build"))
    assert ("--build-arg", "DB_URL=test") == build[build.index("--build-arg"):build.index("--build-arg") + 2]
    assert files["dockerfile"].count("ARG DB_URL") == 2
    assert not Path(files["path"]).exists()                                   # temporary Dockerfile removed
    assert (tmp_path / "Dockerfile").read_text().count("ARG") == 0              # the project's file is untouched


def test_local_check_failures_exit_non_zero(tmp_path, docker, monkeypatch, capsys):
    local_check, calls, _ = docker
    make(tmp_path, {"Dockerfile": "FROM node:22\n"})
    for argv, error in (([str(tmp_path), "--port", "1", "--build-env", "BAD-KEY=x"], "invalid --build-env"),
                        ([str(tmp_path / "missing"), "--port", "1", "--build-env", "A=x"], "no Dockerfile")):
        with pytest.raises(SystemExit) as e:
            local_check.main(argv)
        assert e.value.code == 1 and error in json.loads(capsys.readouterr().out)["error"]
    monkeypatch.setattr(local_check, "body", lambda url: "<app-root></app-root>")
    with pytest.raises(SystemExit) as e:
        local_check.main([str(tmp_path), "--port", "1", "--expect", "ng-server-context"])
    res = json.loads(capsys.readouterr().out)
    assert e.value.code == 1 and res["marker_found"] is False and res["stage"] == "routes"
