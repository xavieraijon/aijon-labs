"""PostgreSQL backups: schedule, backup now, restore, download, status (coolify.py). Offline: api and ssh mocked."""

import argparse
import subprocess

import coolify
import pytest

DB = "d" * 24
APP = "a" * 24
SCHED = {"uuid": "sched1", "timeout": coolify.TIMEOUT_SCHEDULED, "enabled": True, "frequency": "daily",
         "database_backup_retention_amount_locally": 7, "save_s3": False}
MANUAL = {"uuid": "man1", "timeout": coolify.TIMEOUT_MANUAL, "enabled": False, "frequency": coolify.MANUAL_FREQUENCY,
          "database_backup_retention_amount_locally": 5, "save_s3": False}


def ex(uuid, status="success", day=1, **kw):
    return {"uuid": uuid, "status": status, "created_at": f"2026-11-{day:02d}T00:00:00Z", "size": "2048",
            "filename": f"/data/coolify/backups/databases/t-0/db-{DB}/pg-dump-{uuid}.dmp", **kw}


class FakeCoolify:
    """Records calls; answers from a small in-memory model of one database and its backup configurations."""

    def __init__(self, configs=None, version="4.6.0", db_type="standalone-postgresql", db_status="running:healthy"):
        self.configs = configs if configs is not None else []
        self.version, self.db_type, self.db_status = version, db_type, db_status
        self.calls = []
        self.on_backup_now = lambda cfg: cfg.setdefault("executions", []).insert(0, ex("new", day=20))
        self.imports = []
        self.import_states = [{"status": "finished", "exit_code": 0}]

    def __call__(self, method, path, body=None, query=None):
        self.calls.append((method, path, body))
        base = f"/databases/{DB}"
        if path == "/version":
            return {"text": self.version}
        if (method, path) == ("GET", base):
            return {"uuid": DB, "database_type": self.db_type, "status": self.db_status}
        if (method, path) == ("GET", f"{base}/backups"):
            return self.configs
        if (method, path) == ("POST", f"{base}/backups"):
            cfg = {**body, "uuid": f"new{len(self.configs)}", "executions": []}
            cfg.pop("backup_now", None)
            self.configs.append(cfg)
            if body.get("backup_now"):
                self.on_backup_now(cfg)
            return {"uuid": cfg["uuid"]}
        if method == "PATCH" and path.startswith(f"{base}/backups/"):
            cfg = next(c for c in self.configs if c["uuid"] == path.rsplit("/", 1)[1])
            if body.get("backup_now"):
                self.on_backup_now(cfg)
            cfg.update({k: v for k, v in body.items() if k != "backup_now"})
            return {"message": "updated"}
        if method == "GET" and path.endswith("/executions"):
            cfg = next(c for c in self.configs if c["uuid"] == path.split("/")[-2])
            return {"executions": cfg.get("executions", [])}
        if (method, path) == ("POST", f"{base}/imports"):
            self.imports.append(body)
            return {"id": 42, "status": "queued"}
        if method == "GET" and path.startswith(f"{base}/imports/"):
            return self.import_states.pop(0) if len(self.import_states) > 1 else self.import_states[0]
        raise AssertionError(f"unexpected call {method} {path}")

    def writes(self):
        return [(m, p, b) for m, p, b in self.calls if m != "GET"]


@pytest.fixture
def fake(config, monkeypatch):
    f = FakeCoolify()
    monkeypatch.setattr(coolify, "api", f)
    monkeypatch.setattr(coolify.time, "sleep", lambda _s: None)
    coolify.write_json(coolify.REGISTRY, {"shop": {"app_uuid": APP, "db_uuid": DB}})
    return f


def ns(**kw):
    base = {"app": "shop", "db": None, "frequency": None, "keep": None, "off": False, "backup": None,
            "confirmed": False, "timeout": 60, "backup_timeout": 60, "out": None}
    return argparse.Namespace(**{**base, **kw})


# ---------------------------------------------------------------- target, version


@pytest.mark.parametrize("version", ["4.5.3", "v4.4.0", "nightly"])
def test_old_or_unknown_coolify_is_refused_before_anything_else(fake, version):
    fake.version = version
    with pytest.raises(coolify.Error, match="4.6.0 or later"):
        coolify.cmd_backup_status(ns())
    assert [p for _m, p, _b in fake.calls] == ["/version"]


@pytest.mark.parametrize("version", ["4.6.0", "v4.7.4"])
def test_supported_versions_pass(fake, version):
    fake.version = version
    assert coolify.cmd_backup_status(ns())["ok"]


def test_database_from_registry_by_name_by_app_uuid_or_db_flag(fake):
    assert coolify.cmd_backup_status(ns())["db_uuid"] == DB
    assert coolify.cmd_backup_status(ns(app=APP))["db_uuid"] == DB
    assert coolify.cmd_backup_status(ns(app="other", db=DB))["db_uuid"] == DB


def test_no_database_known_is_an_error(fake):
    with pytest.raises(coolify.Error, match="--db"):
        coolify.cmd_backup_status(ns(app="other"))


def test_only_postgresql(fake):
    fake.db_type = "standalone-mysql"
    with pytest.raises(coolify.Error, match="only for PostgreSQL"):
        coolify.cmd_backup_status(ns())


# ---------------------------------------------------------------- status


def test_status_tells_configurations_apart_and_merges_backups(fake):
    other = {"uuid": "ui1", "timeout": 3600, "enabled": True, "frequency": "weekly",
             "executions": [ex("o1", day=3)]}
    fake.configs = [{**SCHED, "executions": [ex("s1", day=5), ex("s0", day=4, local_storage_deleted=True),
                                             ex("f1", "failed", day=6)]},
                    {**MANUAL, "executions": [ex("m1", day=2)]}, other]
    r = coolify.cmd_backup_status(ns())
    assert {s["uuid"]: s["origin"] for s in r["schedules"]} == {"sched1": "scheduled", "man1": "manual", "ui1": "other"}
    assert [b["uuid"] for b in r["backups"]] == ["s1", "o1", "m1"]  # newest first, deleted files left out
    assert r["backups"][0]["size_bytes"] == 2048 and r["has_schedule"]
    assert r["last_failed_at"].startswith("2026-11-06")


# ---------------------------------------------------------------- schedule


def test_schedule_creates_daily_keep_7_with_exact_body(fake):
    r = coolify.cmd_backup_schedule(ns())
    assert r["created"] and r["keep"] == 7
    assert fake.writes() == [("POST", f"/databases/{DB}/backups",
                              {"frequency": "daily", "enabled": True, "save_s3": False,
                               "database_backup_retention_amount_locally": 7, "timeout": coolify.TIMEOUT_SCHEDULED})]


def test_schedule_patches_only_changed_fields(fake):
    fake.configs = [{**SCHED, "executions": []}]
    coolify.cmd_backup_schedule(ns(keep=10))
    assert fake.writes() == [("PATCH", f"/databases/{DB}/backups/sched1",
                              {"database_backup_retention_amount_locally": 10})]  # no frequency sent


@pytest.mark.parametrize("bad", [{"keep": 0}, {"frequency": "every day"}, {"frequency": "* * * *"},
                                 {"frequency": "0 0 * * * ; rm"}])
def test_schedule_refuses_bad_values_before_any_call(fake, bad):
    with pytest.raises(coolify.Error):
        coolify.cmd_backup_schedule(ns(**bad))
    assert fake.calls == []


def test_lowering_keep_asks_first(fake):
    fake.configs = [{**SCHED, "executions": [ex(f"s{i}", day=i + 1) for i in range(7)]}]
    r = coolify.cmd_backup_schedule(ns(keep=2))
    assert not r["ok"] and r["needs_confirmation"] and r["would_delete"] == 5
    assert fake.writes() == []
    assert coolify.cmd_backup_schedule(ns(keep=2, confirmed=True))["ok"]
    assert fake.writes()[0][2] == {"database_backup_retention_amount_locally": 2}


def test_configurations_made_in_coolify_are_not_touched_without_backup_flag(fake):
    fake.configs = [{"uuid": "ui1", "timeout": 3600, "enabled": True, "frequency": "weekly", "executions": []}]
    with pytest.raises(coolify.Error, match="--backup"):
        coolify.cmd_backup_schedule(ns(keep=3))
    assert fake.writes() == []
    coolify.cmd_backup_schedule(ns(keep=3, backup="ui1"))
    assert fake.writes() == [("PATCH", f"/databases/{DB}/backups/ui1", {"database_backup_retention_amount_locally": 3})]


def test_schedule_off(fake):
    fake.configs = [{**SCHED, "executions": []}]
    assert coolify.cmd_backup_schedule(ns(off=True))["enabled"] is False
    assert fake.writes()[0][2] == {"enabled": False}


# ---------------------------------------------------------------- backup now


def test_backup_now_refuses_a_stopped_database(fake):
    fake.db_status = "exited:unhealthy"
    with pytest.raises(coolify.Error, match="not running"):
        coolify.cmd_backup_now(ns())
    assert fake.writes() == []


def test_backup_now_creates_a_disabled_manual_configuration(fake):
    fake.configs = [{**SCHED, "executions": []}]
    r = coolify.cmd_backup_now(ns())
    assert r["ok"] and r["execution_uuid"] == "new" and r["size_bytes"] == 2048
    (method, _path, body), = fake.writes()
    assert method == "POST" and body == {"frequency": coolify.MANUAL_FREQUENCY, "enabled": False, "save_s3": False,
                                         "backup_now": True, "database_backup_retention_amount_locally": 5,
                                         "timeout": coolify.TIMEOUT_MANUAL}
    assert fake.configs[0]["enabled"] is True and "executions" in fake.configs[0]  # scheduled one untouched


def test_backup_now_reuses_the_manual_configuration_and_ignores_old_executions(fake, monkeypatch):
    fake.configs = [{**MANUAL, "executions": [ex("old", day=1)]}]
    fake.on_backup_now = lambda cfg: None  # the executions below come from the polls instead
    states = iter([[ex("old")], [ex("new", "running"), ex("old")], [ex("new", day=20), ex("old")]])
    real = fake.__call__

    def api(method, path, body=None, query=None):
        if path.endswith("/executions"):
            fake.calls.append((method, path, body))
            return {"executions": next(states)}
        return real(method, path, body, query)
    monkeypatch.setattr(coolify, "api", api)
    r = coolify.cmd_backup_now(ns())
    assert r["execution_uuid"] == "new" and r["status"] == "success"
    assert ("PATCH", f"/databases/{DB}/backups/man1", {"backup_now": True}) in fake.writes()


def test_backup_now_failure_shows_only_error_lines(fake):
    msg = "pg_dump: dumping contents of table users\nERROR: out of memory\nCONTEXT: COPY users, line 3: \"x@example.org\""
    fake.on_backup_now = lambda cfg: cfg["executions"].insert(0, ex("new", "failed", message=msg))
    r = coolify.cmd_backup_now(ns())
    assert not r["ok"] and r["message"] == ["ERROR: out of memory"]


def test_backup_now_timeout(fake):
    fake.on_backup_now = lambda cfg: None
    with pytest.raises(coolify.Error, match="did not finish"):
        coolify.cmd_backup_now(ns(timeout=0))


# ---------------------------------------------------------------- restore


def test_restore_needs_confirmation(fake):
    with pytest.raises(coolify.Error, match="--confirmed"):
        coolify.cmd_backup_restore(ns(execution="s1"))
    assert fake.calls == []


@pytest.mark.parametrize("execution", ["f1", "nope", "gone"])
def test_restore_refuses_failed_unknown_or_deleted_backups(fake, execution):
    fake.configs = [{**SCHED, "executions": [ex("f1", "failed"), ex("gone", local_storage_deleted=True)]}]
    with pytest.raises(coolify.Error, match="not a successful backup"):
        coolify.cmd_backup_restore(ns(execution=execution, confirmed=True))
    assert fake.writes() == []


def test_restore_takes_a_safety_backup_then_imports_from_the_server_file(fake):
    fake.configs = [{**SCHED, "executions": [ex("s1", day=1)]}]
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert r["ok"] and r["safety_backup"] == "new" and r["restored_from"]["uuid"] == "s1"
    assert fake.imports == [{"source": "server", "path": ex("s1")["filename"], "replace_existing": True}]
    assert [m for m, _p, _b in fake.writes()] == ["POST", "POST"]  # manual configuration + backup, then import


def test_restore_stops_when_the_safety_backup_fails(fake):
    fake.configs = [{**SCHED, "executions": [ex("s1")]}]
    fake.on_backup_now = lambda cfg: cfg["executions"].insert(0, ex("new", "failed", message="FATAL: disk full"))
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert not r["ok"] and "nothing was restored" in r["error"] and fake.imports == []


def test_restore_stops_when_retention_removed_the_chosen_backup(fake):
    fake.configs = [{**SCHED, "executions": [ex("s1")]}]

    def rotate(cfg):  # Coolify's retention deletes the chosen file right after the safety backup
        cfg["executions"].insert(0, ex("new", day=20))
        fake.configs[0]["executions"][0]["local_storage_deleted"] = True
    fake.on_backup_now = rotate
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert not r["ok"] and "no longer exists" in r["error"] and r["safety_backup"] == "new" and fake.imports == []


def test_restore_failure_hides_row_data(fake):
    fake.configs = [{**SCHED, "executions": [ex("s1")]}]
    fake.import_states = [{"status": "error", "exit_code": 1, "output": (
        "pg_restore: error: could not execute query: ERROR: cannot drop table users because other objects depend on it\n"
        "DETAIL: constraint orders_user_fk on table orders depends on table users\n"
        "Command was: DROP TABLE public.users;")}]
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert not r["ok"] and len(r["output"]) == 1 and "DETAIL" not in r["output"][0]


def test_restore_timeout_returns_the_import_id(fake):
    fake.configs = [{**SCHED, "executions": [ex("s1")]}]
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True, timeout=0))
    assert not r["ok"] and r["import_id"] == 42 and "backup-restore-status" in r["error"]


def test_restore_has_no_way_to_skip_the_safety_backup():
    with pytest.raises(SystemExit):
        coolify.parser().parse_args(["backup-restore", "shop", "--execution", "s1", "--confirmed", "--no-safety-backup"])


@pytest.mark.parametrize("bad", ["../../applications", "42?x=1", "", "4 2"])
def test_restore_status_refuses_an_invalid_import_id_before_any_call(fake, bad):
    with pytest.raises(coolify.Error, match="Invalid import id"):
        coolify.cmd_backup_restore_status(ns(import_id=bad))
    assert fake.calls == []


def test_status_counts_schedules_made_in_coolify(fake):
    fake.configs = [{"uuid": "ui1", "timeout": 3600, "enabled": True, "frequency": "daily", "executions": []}]
    r = coolify.cmd_backup_status(ns())
    assert r["has_any_schedule"] and not r["has_schedule"]


def test_restore_status_while_running_is_not_an_error(fake):
    fake.import_states = [{"status": "in_progress"}]
    r = coolify.cmd_backup_restore_status(ns(import_id="42"))
    assert r["ok"] and not r["finished"]


# ---------------------------------------------------------------- download


class FakeSsh:
    def __init__(self, data=b"PGDMP\x01\x0e rest", code=0, stderr=b""):
        self.data, self.code, self.stderr, self.scripts = data, code, stderr, []

    def __call__(self, cmd, input=None, stdout=None, stderr=None, timeout=None, **_k):
        assert cmd[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
        self.scripts.append(input.decode())
        stdout.write(self.data)
        return subprocess.CompletedProcess(cmd, self.code, None, self.stderr)


@pytest.fixture
def ssh(fake, monkeypatch):
    cfg = coolify.read_json(coolify.CONFIG, {})
    coolify.write_json(coolify.CONFIG, {**cfg, "ssh": "user@server"})
    s = FakeSsh()
    monkeypatch.setattr(coolify.subprocess, "run", s)
    monkeypatch.setattr(coolify, "_inside_git", lambda _p: False)
    return s


def test_download_writes_a_private_dump_in_the_config_folder(ssh, config):
    r = coolify.cmd_backup_download(ns())
    f = coolify.Path(r["file"])
    assert f.parent == config / "backups" / "shop" and f.suffix == ".dump" and f.read_bytes().startswith(b"PGDMP")
    assert oct(f.stat().st_mode & 0o777) == "0o600" and oct(f.parent.stat().st_mode & 0o777) == "0o700"
    assert ssh.scripts == [f"docker exec {DB} sh -c 'pg_dump --format=custom -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\"'\n"]
    assert not list(f.parent.glob("*.part"))


@pytest.mark.parametrize("data,code", [(b"PGDMP partial", 1), (b"<html>", 0), (b"", 0)])
def test_download_never_keeps_a_broken_dump(ssh, config, data, code):
    ssh.data, ssh.code, ssh.stderr = data, code, b"pg_dump: error: connection lost\n"
    with pytest.raises(coolify.Error, match="nothing was kept"):
        coolify.cmd_backup_download(ns())
    assert list((config / "backups" / "shop").iterdir()) == []


def test_download_refuses_an_invalid_uuid_without_ssh(ssh, fake):
    with pytest.raises(coolify.Error, match="Invalid database uuid"):
        coolify.cmd_backup_download(ns(app="x", db="bad; rm -rf /"))
    assert ssh.scripts == []


def test_download_refuses_a_folder_inside_a_git_repository(ssh, monkeypatch, tmp_path):
    monkeypatch.setattr(coolify, "_inside_git", lambda _p: True)
    with pytest.raises(coolify.Error, match="outside any git repository"):
        coolify.cmd_backup_download(ns(out=str(tmp_path / "proj" / "dumps")))
    assert ssh.scripts == []


def test_inside_git_with_real_git_and_without_git(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert coolify._inside_git(repo / "not" / "yet")  # nearest existing parent is checked
    assert not coolify._inside_git(tmp_path / "elsewhere")

    def no_git(*_a, **_k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(coolify.subprocess, "run", no_git)
    assert not coolify._inside_git(repo)


def test_download_needs_ssh_in_the_configuration(fake):
    with pytest.raises(coolify.Error, match="ssh"):
        coolify.cmd_backup_download(ns())


# ---------------------------------------------------------------- create-postgres, status


def pg_args(**kw):
    return argparse.Namespace(**{"project": "p", "name": "shop", "app": "shop", "app_uuid": None,
                                 "environment": "production", "image": "postgres:17-alpine", "memory": "512m",
                                 "buildtime": False, "env_key": "DATABASE_URL", **kw})


def test_create_postgres_schedules_daily_backups_by_default(config, monkeypatch):
    f = FakeCoolify()

    def api(method, path, body=None, query=None):
        if path == "/databases/postgresql":
            return {"uuid": DB}
        return f(method, path, body, query)
    monkeypatch.setattr(coolify, "api", api)
    r = coolify.cmd_create_postgres(pg_args(backup="daily"))
    assert r["backup"]["keep"] == 7 and "backup_warning" not in r
    assert f.writes()[0][2]["timeout"] == coolify.TIMEOUT_SCHEDULED
    f.calls.clear()
    assert "backup" not in coolify.cmd_create_postgres(pg_args(backup="none")) and f.calls == []


def test_create_postgres_reports_a_failed_schedule_without_failing(config, monkeypatch):
    def api(method, path, body=None, query=None):
        if path == "/version":
            return {"text": "4.5.0"}
        return {"uuid": DB}
    monkeypatch.setattr(coolify, "api", api)
    r = coolify.cmd_create_postgres(pg_args(backup="daily"))
    assert r["ok"] and r["db_uuid"] == DB and "4.6.0" in r["backup_warning"]


def test_status_reports_backups_and_survives_one_failing_database(config, monkeypatch):
    def api(method, path, body=None, query=None):
        if path == "/databases":
            return [{"uuid": DB, "database_type": "standalone-postgresql"},
                    {"uuid": "e" * 24, "database_type": "standalone-postgresql"},
                    {"uuid": "r" * 24, "database_type": "standalone-redis"}]
        if path == f"/databases/{DB}/backups":
            return [{**SCHED, "executions": [ex("s1", day=9)]}]
        if path.endswith("/backups"):
            raise coolify.Error("HTTP 403 on GET")
        raise AssertionError(path)
    monkeypatch.setattr(coolify, "api", api)
    monkeypatch.setattr(coolify, "_apps", lambda: [])
    dbs = coolify.cmd_status(argparse.Namespace())["databases"]
    assert dbs[0]["backups"] == {"enabled": True, "frequency": "daily", "last_success_at": "2026-11-09T00:00:00Z"}
    assert "403" in dbs[1]["backups"]["error"] and "backups" not in dbs[2]


def test_main_exits_non_zero_when_ok_is_false(fake, capsys):
    fake.configs = [{**SCHED, "executions": [ex(f"s{i}") for i in range(7)]}]
    with pytest.raises(SystemExit) as e:
        coolify.main(["backup-schedule", "shop", "--keep", "1"])
    assert e.value.code == 1 and '"needs_confirmation": true' in capsys.readouterr().out
