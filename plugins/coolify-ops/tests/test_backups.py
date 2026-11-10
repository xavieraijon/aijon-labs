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
            "filename": f"/data/coolify/backups/databases/t-0/db-{DB}/pg-dump-shop-1794337857-{uuid}.dmp", **kw}


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


class FakeDbShell:
    """Stands in for _ssh_db: answers the state query, records every command run in the database container."""

    def __init__(self, version="170004", db="shop", tables=3):
        self.state = f"{version}|{db}|{tables}\n"
        self.runs = []
        self.reset_results = []  # (code, stderr) per reset; default success
        self.restore_code = 0

    def __call__(self, target, db, command, stdin="", timeout=600):
        assert target == "user@server" and db == DB
        if stdin == coolify.STATE_SQL:
            self.runs.append("state")
            return 0, self.state, ""
        if stdin == coolify.RESET_SQL:
            self.runs.append("reset")
            code, err = self.reset_results.pop(0) if self.reset_results else (0, "")
            return code, "", err
        kind = command.split()[0]
        self.runs.append(kind)
        return (self.restore_code if kind == "pg_restore" else 0), "", ""


@pytest.fixture
def shell(fake, monkeypatch):
    cfg = coolify.read_json(coolify.CONFIG, {})
    coolify.write_json(coolify.CONFIG, {**cfg, "ssh": "user@server"})
    sh = FakeDbShell()
    monkeypatch.setattr(coolify, "_ssh_db", sh)
    fake.configs = [{**SCHED, "executions": [ex("s1", day=1)]}]
    return sh


def test_restore_needs_confirmation(fake):
    with pytest.raises(coolify.Error, match="--confirmed"):
        coolify.cmd_backup_restore(ns(execution="s1"))
    assert fake.calls == []


def test_restore_needs_ssh_before_anything(fake):
    with pytest.raises(coolify.Error, match="ssh"):
        coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert fake.calls == []


@pytest.mark.parametrize("execution", ["f1", "nope", "gone"])
def test_restore_refuses_failed_unknown_or_deleted_backups(shell, fake, execution):
    fake.configs = [{**SCHED, "executions": [ex("f1", "failed"), ex("gone", local_storage_deleted=True)]}]
    with pytest.raises(coolify.Error, match="not a successful backup"):
        coolify.cmd_backup_restore(ns(execution=execution, confirmed=True))
    assert fake.writes() == [] and shell.runs == []


@pytest.mark.parametrize("change,message", [
    ({"size": str(11 * 1024 ** 3)}, "10 GiB"),
    ({"filename": "/data/coolify/backups/databases/t-0/x/pg-dump-other-1794337857-s1.dmp"}, "not a dump of this"),
    ({"filename": "/data/coolify/backups/databases/t-0/x/pg-dump-all-1794337857-s1.gz"}, "not a dump of this"),
])
def test_restore_pre_checks_change_nothing(shell, fake, change, message):
    fake.configs[0]["executions"][0].update(change)
    with pytest.raises(coolify.Error, match=message):
        coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert fake.writes() == [] and "reset" not in shell.runs


def test_restore_refuses_postgresql_older_than_15(shell, fake):
    shell.state = "140010|shop|3\n"
    with pytest.raises(coolify.Error, match="PostgreSQL 15"):
        coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert fake.writes() == [] and shell.runs == ["state"]


def test_clean_restore_order(shell, fake):
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert r["ok"] and r["safety_backup"] == "new" and r["restored_from"]["uuid"] == "s1"
    assert shell.runs == ["state", "pg_dump", "reset", "rm"]
    assert fake.imports == [{"source": "server", "path": ex("s1")["filename"], "replace_existing": True}]
    first_import = next(i for i, c in enumerate(fake.calls) if c[1].endswith("/imports"))
    first_backup = next(i for i, c in enumerate(fake.calls) if c[0] == "POST" and c[1].endswith("/backups"))
    assert first_backup < first_import


def test_reset_sql_is_sent_on_stdin_never_in_a_shell_string(fake, monkeypatch):
    seen = []
    monkeypatch.setattr(coolify.subprocess, "run", lambda cmd, **k: seen.append(k["input"]) or
                        subprocess.CompletedProcess(cmd, 0, "", ""))
    coolify._ssh_db("user@server", DB, coolify.PSQL, coolify.RESET_SQL)
    script = seen[0]
    assert script.startswith(f"docker exec -i {DB} sh -c 'psql ")
    assert "<<'COOLIFY_OPS_EOF'\n" + coolify.RESET_SQL + "COOLIFY_OPS_EOF\n" in script
    assert "lock_timeout = '30s'" in coolify.RESET_SQL and "-1 -v ON_ERROR_STOP=1" in coolify.PSQL


@pytest.mark.parametrize("sql", ["STATE_SQL", "RESET_SQL"])
def test_heredoc_end_marker_is_on_its_own_line(fake, monkeypatch, sql):
    seen = []
    monkeypatch.setattr(coolify.subprocess, "run", lambda cmd, **k: seen.append(k["input"]) or
                        subprocess.CompletedProcess(cmd, 0, "", ""))
    coolify._ssh_db("user@server", DB, coolify.PSQL, getattr(coolify, sql))
    lines = seen[0].splitlines()
    assert lines[-1] == "COOLIFY_OPS_EOF" and lines[-2].strip().endswith(";")


def test_an_empty_database_gets_no_safety_copies(shell, fake):
    shell.state = "170004|shop|0\n"
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert r["ok"] and r["safety_backup"] is None
    assert shell.runs == ["state", "reset"]
    assert not any(c[0] in ("POST", "PATCH") and c[1].endswith(("/backups", "/backups/man1")) for c in fake.calls)


def test_restore_stops_when_the_safety_backup_fails(shell, fake):
    fake.on_backup_now = lambda cfg: cfg["executions"].insert(0, ex("new", "failed", message="FATAL: disk full"))
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert not r["ok"] and "nothing was restored" in r["error"] and fake.imports == []
    assert shell.runs == ["state"]


def test_restore_stops_when_retention_removed_the_chosen_backup(shell, fake):
    def rotate(cfg):  # Coolify's retention deletes the chosen file right after the safety backup
        cfg["executions"].insert(0, ex("new", day=20))
        fake.configs[0]["executions"][-1]["local_storage_deleted"] = True
    fake.on_backup_now = rotate
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert not r["ok"] and "no longer exists" in r["error"] and r["safety_backup"] == "new" and fake.imports == []
    assert "reset" not in shell.runs


@pytest.mark.parametrize("stderr,message", [
    ("ERROR:  canceling statement due to lock timeout\n", "busy"),
    ("ERROR:  permission denied for schema public\n", "permission denied"),
])
def test_reset_failure_changes_nothing(shell, fake, stderr, message):
    shell.reset_results = [(3, stderr)]
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert not r["ok"] and message in r["error"] and fake.imports == []
    assert shell.runs == ["state", "pg_dump", "reset", "rm"]


def test_failed_import_puts_the_previous_data_back(shell, fake):
    fake.import_states = [{"status": "error", "exit_code": 1, "output": (
        "pg_restore: error: could not execute query: ERROR: cannot drop table users because other objects depend on it\n"
        "DETAIL: constraint orders_user_fk on table orders depends on table users\n"
        "Command was: DROP TABLE public.users;")}]
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert not r["ok"] and r["recovered"] and "put back" in r["error"]
    assert len(r["output"]) == 1 and "DETAIL" not in r["output"][0]
    assert shell.runs == ["state", "pg_dump", "reset", "reset", "pg_restore", "rm"]


def test_import_refused_at_the_post_is_recovered_too(shell, fake, monkeypatch):
    real = fake.__call__

    def api(method, path, body=None, query=None):
        if method == "POST" and path.endswith("/imports"):
            raise coolify.Error("HTTP 422 on POST (Coolify rejected the data): The backup exceeds the 10 GiB limit.")
        return real(method, path, body, query)
    monkeypatch.setattr(coolify, "api", api)
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert not r["ok"] and r["recovered"] and "refused" in r["error"]
    assert shell.runs[-3:] == ["reset", "pg_restore", "rm"]


def test_failed_recovery_keeps_the_copy_and_names_it(shell, fake):
    fake.import_states = [{"status": "error", "exit_code": 1, "output": "ERROR: boom"}]
    shell.restore_code = 1
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert not r["ok"] and r["recovered"] is False
    assert coolify.CONTAINER_COPY in r["error"] and "backup-restore --execution new" in r["error"]
    assert "rm" not in shell.runs


def test_restore_timeout_does_not_recover(shell, fake):
    fake.import_states = [{"status": "in_progress"}]
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True, timeout=0))
    assert not r["ok"] and r["import_id"] == 42 and "backup-restore-status" in r["error"]
    assert r["copy_in_container"] == coolify.CONTAINER_COPY and shell.runs == ["state", "pg_dump", "reset"]


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


def test_decommission_deletes_backups_first_and_stops_if_one_fails(config, monkeypatch):
    coolify.save_to_registry("shop", {"app_uuid": APP, "db_uuid": DB, "project_uuid": "p1"})
    calls = []

    def api(method, path, body=None, query=None):
        calls.append((method, path))
        if path == f"/databases/{DB}/backups":
            return [{"uuid": "b1"}, {"uuid": "b2"}]
        if path.endswith("/b2"):
            raise coolify.Error("HTTP 403 on DELETE")
        return {}
    monkeypatch.setattr(coolify, "api", api)
    with pytest.raises(coolify.Error, match="Nothing else was deleted"):
        coolify.cmd_decommission(argparse.Namespace(app="shop", confirmed=True, with_db=True, with_project=True))
    assert [c for c in calls if c[0] == "DELETE"] == [("DELETE", f"/databases/{DB}/backups/b1"),
                                                     ("DELETE", f"/databases/{DB}/backups/b2")]



def test_state_sql_counts_objects_in_every_user_schema():
    sql = coolify.STATE_SQL
    assert "pg_tables" not in sql and "pg_class" in sql and "'public'" not in sql
    assert "NOT LIKE 'pg\\_%'" in sql and "'v'" in sql and "'S'" in sql


def test_lost_contact_while_polling_never_recovers(shell, fake, monkeypatch):
    real = fake.__call__

    def api(method, path, body=None, query=None):
        if method == "GET" and "/imports/" in path:
            raise coolify.Error("HTTP 502 on GET")
        return real(method, path, body, query)
    monkeypatch.setattr(coolify, "api", api)
    r = coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert not r["ok"] and r["import_id"] == 42 and "backup-restore-status" in r["error"]
    assert "recovered" not in r and r["copy_in_container"] == coolify.CONTAINER_COPY
    assert shell.runs == ["state", "pg_dump", "reset"]


@pytest.mark.parametrize("answer", ["Welcome to the server\n", "17|shop\n", "x|shop|3\n"])
def test_unexpected_state_answer_is_an_error_not_a_traceback(shell, fake, answer):
    shell.state = answer
    with pytest.raises(coolify.Error, match="nothing was changed"):
        coolify.cmd_backup_restore(ns(execution="s1", confirmed=True))
    assert fake.writes() == []


def test_decommission_without_backup_api_goes_on(config, monkeypatch):
    coolify.save_to_registry("shop", {"app_uuid": APP, "db_uuid": DB})
    calls = []

    def api(method, path, body=None, query=None):
        calls.append((method, path))
        if path == f"/databases/{DB}/backups":
            raise coolify.Error("HTTP 404 on GET")
        if method == "GET":
            raise coolify.Error("HTTP 404 on GET")
        return {}
    monkeypatch.setattr(coolify, "api", api)
    monkeypatch.setattr(coolify.time, "sleep", lambda s: None)
    r = coolify.cmd_decommission(argparse.Namespace(app="shop", confirmed=True, with_db=True, with_project=False))
    assert r["deleted"]["backups"] == [] and ("DELETE", f"/databases/{DB}") in calls


def test_init_again_keeps_the_saved_server_and_github_app(config, monkeypatch):
    coolify.write_json(coolify.CONFIG, {**coolify.read_json(coolify.CONFIG, {}), "url": "http://203.0.113.5:8000",
                                        "base_domain": "example.org", "server_name": "vps",
                                        "github_app_name": "second"})
    answers = {"/servers": [{"name": "localhost", "uuid": "s0"}, {"name": "vps", "uuid": "s1"}],
               "/github-apps": [{"name": "first", "uuid": "g0"}, {"name": "second", "uuid": "g1"}]}
    monkeypatch.setattr(coolify, "api", lambda method, path, body=None, query=None: answers[path])
    r = coolify.cmd_init(argparse.Namespace(url=None, domain=None, ssh="user@server", server=None, github_app=None,
                                            reserved=None, projects_dir=None))
    cfg = coolify.read_json(coolify.CONFIG, {})
    assert r["server"] == "vps" and cfg["server_uuid"] == "s1" and cfg["github_app_uuid"] == "g1"
    assert cfg["ssh"] == "user@server"
