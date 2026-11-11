#!/usr/bin/env python3
"""Minimal client for the Coolify v4 API, used by the coolify-ops skills.

Standard library only. Every command prints a single line of JSON for Claude to read.
Tokens and passwords are never printed: sensitive values are masked.

Configuration (outside the repo):
  ~/.config/coolify-ops/config.json   url, base_domain, server_uuid, github_app_uuid, …
  ~/.config/coolify-ops/apps.json     local registry of deployed apps
  API token, first found wins:
    1. COOLIFY_TOKEN environment variable
    2. ~/.config/coolify-ops/token      (one line, chmod 600)
    3. macOS Keychain, service "coolify-api-token"

Usage:  coolify.py <command> [options]      (coolify.py --help for the list)
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LEGACY_DIR = Path.home() / ".config" / "coolify-deploy"
CONFIG_DIR = Path(os.environ.get("COOLIFY_OPS_HOME", Path.home() / ".config" / "coolify-ops"))
CONFIG = CONFIG_DIR / "config.json"
REGISTRY = CONFIG_DIR / "apps.json"
TOKEN_FILE = CONFIG_DIR / "token"
KEYCHAIN_SERVICE = "coolify-api-token"
FINAL_STATES = {"finished", "failed", "cancelled-by-user", "cancelled"}
PUBLIC_PREFIXES = ("NEXT_PUBLIC_", "VITE_", "PUBLIC_", "NUXT_PUBLIC_", "REACT_APP_")

# Keys used by v0.1 (Spanish) → current keys. Applied when reading old files.
LEGACY_CONFIG_KEYS = {"dominio_base": "base_domain", "subdominios_reservados": "reserved_subdomains",
                      "carpeta_proyectos": "projects_dir", "limites_defecto": "default_limits"}
# Coolify's own checks of these fields (app/Support/ValidationPatterns.php); watch paths are globs, «!» excludes
BASE_DIR = re.compile(r"/[A-Za-z0-9._~@+/-]*")
DOCKERFILE_PATH = re.compile(r"/[A-Za-z0-9._~@+/-]+")
WATCH_PATH = re.compile(r"!?[A-Za-z0-9._~@+/*?\[\]-]+")
LEGACY_REGISTRY_KEYS = {"proyecto_uuid": "project_uuid", "dominio": "domain", "rama": "branch",
                        "actualizado": "updated"}


# ---------------------------------------------------------------- helpers


class Error(Exception):
    """Expected error: printed as JSON with ok=false. «status» is the HTTP status when Coolify answered with one."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def emit(data: dict, code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False, default=str))
    sys.exit(code)


def mask(text: str) -> str:
    """Hide passwords in URLs (proto://user:PASS@host) and Bearer tokens."""
    text = re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1****@", text)
    return re.sub(r"(?i)(bearer\s+)\S+", r"\1****", text)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)  # config, registry and secrets are private to the user
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)


def _rename_keys(d: dict, mapping: dict) -> dict:
    return {mapping.get(k, k): v for k, v in d.items()}


def migrate_legacy() -> bool:
    """Move a v0.1 configuration (~/.config/coolify-deploy, Spanish keys) to the current layout once."""
    if "COOLIFY_OPS_HOME" in os.environ or CONFIG.exists() or not (LEGACY_DIR / "config.json").exists():
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = _rename_keys(read_json(LEGACY_DIR / "config.json", {}), LEGACY_CONFIG_KEYS)
    limits = cfg.get("default_limits") or {}
    if "memoria" in limits:
        limits["memory"] = limits.pop("memoria")
    write_json(CONFIG, cfg)
    reg = read_json(LEGACY_DIR / "apps.json", {})
    write_json(REGISTRY, {name: _rename_keys(app, LEGACY_REGISTRY_KEYS) for name, app in reg.items()})
    if (LEGACY_DIR / "secretos").is_dir() and not (CONFIG_DIR / "secrets").exists():
        shutil.copytree(LEGACY_DIR / "secretos", CONFIG_DIR / "secrets")
    return True


def config() -> dict:
    migrate_legacy()
    cfg = read_json(CONFIG, None)
    if not cfg:
        raise Error(f"No configuration at {CONFIG}. Run: coolify.py init --url URL --domain DOMAIN")
    return cfg


def token() -> str:
    if os.environ.get("COOLIFY_TOKEN"):
        return os.environ["COOLIFY_TOKEN"].strip()
    if TOKEN_FILE.exists():
        value = TOKEN_FILE.read_text().strip()
        if value:
            return value
    if sys.platform == "darwin":
        try:
            r = subprocess.run(
                ["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, check=True,
            )
            if r.stdout.strip():
                return r.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    raise Error("No API token found. Set COOLIFY_TOKEN, write it to "
                f"{TOKEN_FILE} (chmod 600) or, on macOS, store it in the Keychain under service «{KEYCHAIN_SERVICE}».")


def random_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------- HTTP


def api(method: str, path: str, body: dict | list | None = None, query: dict | None = None):
    cfg = config()
    url = cfg["url"].rstrip("/") + "/api/v1" + path
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as r:
            text = r.read().decode(errors="replace") or "{}"
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode(errors="replace")[:800]
        except (OSError, http.client.HTTPException):  # the answer was cut short: the status is what matters
            detail = ""
        hints = {401: "invalid or expired token", 403: "token lacks a permission or your IP is not in «Allowed IPs»",
                 404: "not found (uuid or path)", 422: "Coolify rejected the data"}
        if e.code == 403 and method in ("POST", "PATCH") and re.search(r"/(backups|imports)(/|$)", path):
            hints[403] = ("token lacks a permission — running a backup or a restore needs «deploy» — or your IP is "
                          "not in «Allowed IPs»")
        raise Error(f"HTTP {e.code} on {method} {path} ({hints.get(e.code, 'error')}): {mask(detail)}",
                    status=e.code) from None
    except urllib.error.URLError as e:
        raise Error(f"Cannot reach Coolify at {cfg['url']}: {e.reason}. "
                    "Are you on the right network/VPN? Is API access enabled?") from None
    except (OSError, http.client.HTTPException) as e:  # timeout or connection dropped while reading the answer
        raise Error(f"Lost the connection to Coolify during {method} {path} ({type(e).__name__}): the request may "
                    "or may not have been processed") from None


# ---------------------------------------------------------------- local registry of apps


def registry() -> dict:
    config()  # triggers the legacy migration if needed
    return read_json(REGISTRY, {})


def save_to_registry(name: str, data: dict) -> None:
    reg = registry()
    reg[name] = {**reg.get(name, {}), **data, "updated": time.strftime("%Y-%m-%d %H:%M")}
    write_json(REGISTRY, reg)


COOLIFY_UUID = re.compile(r"[a-z0-9]{24}")


def resolve_app(name_or_uuid: str) -> str:
    """Accept a name from the local registry, a Coolify uuid, or the name of an app on the server."""
    reg = registry()
    if name_or_uuid in reg and reg[name_or_uuid].get("app_uuid"):
        return reg[name_or_uuid]["app_uuid"]
    if COOLIFY_UUID.fullmatch(name_or_uuid):
        return name_or_uuid
    matches = [ap for ap in _apps() if ap.get("name") == name_or_uuid or ap.get("uuid") == name_or_uuid]
    if len(matches) == 1:
        return matches[0]["uuid"]
    if not matches:
        raise Error(f"No app named {name_or_uuid!r} (see «status» for names and uuids)")
    raise Error(f"Several apps are named {name_or_uuid!r}: use the uuid ({', '.join(m['uuid'] for m in matches)})")


def host_of(url_or_host: str) -> str:
    h = url_or_host.strip()
    if "://" in h:
        h = urllib.parse.urlparse(h).hostname or h
    return h.lower().rstrip(".")


# ---------------------------------------------------------------- commands


def cmd_check(_a):
    cfg = config()
    saved = {"url": cfg["url"], "base_domain": cfg.get("base_domain"), "ssh": cfg.get("ssh")}
    try:
        version = api("GET", "/version")
        projects = api("GET", "/projects")
    except Error as e:  # the API failed, but the saved values are still useful (provision-server check mode)
        return {"ok": False, "error": str(e), **saved}
    return {"ok": True, "coolify": version.get("text", version), **saved,
            "projects": len(projects) if isinstance(projects, list) else None}


def cmd_init(a):
    """Discover server_uuid and github_app_uuid and save the configuration."""
    migrate_legacy()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    prev = read_json(CONFIG, {})
    cfg = {**prev, "url": a.url or prev.get("url"), "base_domain": a.domain or prev.get("base_domain")}
    if not cfg["url"] or not cfg["base_domain"]:
        raise Error("Pass --url and --domain the first time.")
    write_json(CONFIG, cfg)  # so api() can read the url
    servers = api("GET", "/servers")
    if not servers:
        raise Error("Coolify returned no servers.")
    server = next((s for s in servers if s.get("name") == (a.server or prev.get("server_name") or "localhost")),
                  servers[0])
    gh_apps = api("GET", "/github-apps")
    private = [g for g in gh_apps if not g.get("is_public")] if isinstance(gh_apps, list) else []
    if not private:
        raise Error("No private GitHub App is connected in Coolify (Sources).")
    gh = next((g for g in private if g.get("name") == (a.github_app or prev.get("github_app_name"))), private[0])
    cfg.update({
        "server_uuid": server["uuid"], "server_name": server.get("name"),
        "github_app_uuid": gh["uuid"], "github_app_id": gh.get("id"), "github_app_name": gh.get("name"),
        "reserved_subdomains": sorted(set(prev.get("reserved_subdomains", []) + (a.reserved or []))),
        "ssh": a.ssh or prev.get("ssh"),
        "projects_dir": a.projects_dir or prev.get("projects_dir") or "~/Projects",
        "default_limits": prev.get("default_limits", {"cpus": "1", "memory": "512m"}),
    })
    write_json(CONFIG, cfg)
    return {"ok": True, "config": str(CONFIG), "server": cfg["server_name"], "github_app": cfg["github_app_name"],
            "base_domain": cfg["base_domain"], "reserved": cfg["reserved_subdomains"],
            "projects_dir": cfg["projects_dir"]}


def _apps() -> list[dict]:
    r = api("GET", "/applications")
    return r if isinstance(r, list) else []


def _autodeploy(app: dict):
    """The list endpoint has no «settings»; fetch the app detail when missing."""
    settings = app.get("settings") or (api("GET", f"/applications/{app['uuid']}") or {}).get("settings") or {}
    return settings.get("is_auto_deploy_enabled")


def cmd_status(_a):
    apps = [{"name": ap.get("name"), "uuid": ap.get("uuid"), "status": ap.get("status"),
             "domains": ap.get("fqdn"), "repo": ap.get("git_repository"), "branch": ap.get("git_branch"),
             "base_dir": ap.get("base_directory") or "/", "autodeploy": _autodeploy(ap)} for ap in _apps()]
    dbs = [{"name": d.get("name"), "uuid": d.get("uuid"), "type": d.get("database_type"), "status": d.get("status"),
            "public": d.get("is_public")} for d in (api("GET", "/databases") or [])]
    for d in dbs:
        if d["type"] == "standalone-postgresql" and d["uuid"]:
            d["backups"] = _backup_summary(d["uuid"])
    return {"ok": True, "apps": apps, "databases": dbs, "local_registry": sorted(registry())}


def _backup_summary(db: str) -> dict:
    """Short backup state for «status»; an error on one database does not stop the listing."""
    try:
        cfgs = _configs(db)
    except Error as e:
        return {"error": str(e)}
    sched = next((c for c in cfgs if c.get("enabled")), None)
    kept = sorted((str(e.get("created_at") or "") for c in cfgs for e in _kept(c)), reverse=True)
    return {"enabled": bool(sched), "frequency": sched.get("frequency") if sched else None,
            "last_success_at": kept[0] if kept else None}


def domains_in_use() -> set[str]:
    used = set()
    for ap in _apps():
        for d in (ap.get("fqdn") or "").split(","):
            if d.strip():
                used.add(host_of(d))
    return used


def cmd_domain_check(a):
    cfg = config()
    host = host_of(a.host)
    base = cfg["base_domain"]
    if "." not in host:
        host = f"{host}.{base}"
    sub = host[: -len(base) - 1] if host.endswith("." + base) else None
    reasons = []
    if not host.endswith("." + base):
        reasons.append(f"not a subdomain of {base}")
    if sub in cfg.get("reserved_subdomains", []):
        reasons.append(f"«{sub}» is reserved")
    if sub and not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", sub):
        reasons.append("invalid name (lowercase letters, digits and hyphens only)")
    if host in domains_in_use():
        reasons.append("already used by another app")
    return {"ok": True, "host": host, "available": not reasons, "reasons": reasons}


def cmd_create_project(a):
    for p in api("GET", "/projects") or []:
        if p.get("name") == a.name:
            return {"ok": True, "project_uuid": p["uuid"], "created": False}
    r = api("POST", "/projects", {"name": a.name, "description": a.description or ""})
    return {"ok": True, "project_uuid": r["uuid"], "created": True}


def cmd_create_postgres(a):
    env_key = getattr(a, "env_key", None) or "DATABASE_URL"
    if not ENV_KEY.fullmatch(env_key):
        raise Error(f"Invalid variable name: {env_key}")
    cfg = config()
    password = random_password()
    user = re.sub(r"[^a-z0-9_]", "_", a.name.lower())[:30] or "app"
    body = {"server_uuid": cfg["server_uuid"], "project_uuid": a.project, "environment_name": a.environment,
            "name": f"{a.name}-db", "image": a.image, "postgres_user": user, "postgres_password": password,
            "postgres_db": user, "is_public": False, "instant_deploy": True, "limits_memory": a.memory}
    r = api("POST", "/databases/postgresql", body)
    uuid = r["uuid"]
    internal_url = f"postgres://{user}:{password}@{uuid}:5432/{user}"
    save_to_registry(a.app or a.name, {"db_uuid": uuid, "project_uuid": a.project})
    if a.app_uuid:  # connect it to the app as DATABASE_URL or --env-key (secret; build time only if the build inlines it)
        _set_env(a.app_uuid, env_key, internal_url, secret=True, buildtime=getattr(a, "buildtime", False))
    result = {"ok": True, "db_uuid": uuid, "internal_host": uuid, "user": user, "env_key": env_key,
              "database_url": mask(internal_url), "linked_to_app": bool(a.app_uuid)}
    if getattr(a, "backup", "daily") != "none":  # daily backups on the server, last DEFAULT_KEEP kept
        try:
            _check_backup_version()
            result["backup"] = {"frequency": "daily", "keep": DEFAULT_KEEP, "backup_uuid": _create_schedule(uuid)}
        except Error as e:  # the database exists and works: report, do not fail
            result["backup_warning"] = f"no backup schedule was created: {e}"
    return result


def _path_errors(a) -> list[str]:
    """Paths Coolify would reject (app/Support/ValidationPatterns.php): checked before anything is created."""
    errors = []
    for value, pattern, what in ((getattr(a, "base_dir", None), BASE_DIR, "--base-dir"),
                                 (getattr(a, "dockerfile", None), DOCKERFILE_PATH, "--dockerfile")):
        if value is not None and (not pattern.fullmatch(value) or ".." in value):
            errors.append(f"{what} {value!r}")
    errors += [f"--watch-paths {p!r}" for p in getattr(a, "watch_paths", None) or []
               if not WATCH_PATH.fullmatch(p) or ".." in p]
    return errors


def cmd_create_app(a):
    cfg = config()
    bad = [k for k in (getattr(a, "env_domain", None) or []) + (getattr(a, "env_url", None) or [])
           if not ENV_KEY.fullmatch(k)]
    bad += [k for k in getattr(a, "env_generate", None) or [] if not _generated_key(k)]
    if bad:
        raise Error(f"Invalid variable names: {', '.join(bad)}")
    paths = _path_errors(a)
    if paths:
        raise Error(f"Invalid paths (letters, digits and . _ - ~ @ + / only, plus * ? [ ] ! in watch paths; no ..): "
                    f"{', '.join(paths)}")
    check = cmd_domain_check(argparse.Namespace(host=a.domain))
    if not check["available"]:
        raise Error(f"Domain {check['host']} not available: {', '.join(check['reasons'])}")
    limits = cfg.get("default_limits", {})
    body = {
        "project_uuid": a.project, "server_uuid": cfg["server_uuid"], "environment_name": a.environment,
        "github_app_uuid": cfg["github_app_uuid"], "git_repository": a.repo, "git_branch": a.branch,
        "build_pack": "dockerfile", "ports_exposes": str(a.port), "name": a.name,
        "domains": f"https://{check['host']}", "is_auto_deploy_enabled": not a.no_autodeploy,
        "is_force_https_enabled": True, "health_check_enabled": False, "instant_deploy": False,
        "limits_cpus": a.cpus or limits.get("cpus", "1"), "limits_memory": a.memory or limits.get("memory", "512m"),
    }
    if a.dockerfile:
        body["dockerfile_location"] = a.dockerfile
    if a.base_dir:
        body["base_directory"] = a.base_dir
    if getattr(a, "watch_paths", None):  # only pushes that change these paths redeploy (repo-relative globs)
        body["watch_paths"] = "\n".join(a.watch_paths)
    r = api("POST", "/applications/private-github-app", body)
    uuid = r["uuid"]
    save_to_registry(a.name, {"app_uuid": uuid, "project_uuid": a.project, "domain": check["host"],
                              "repo": a.repo, "branch": a.branch, "base_dir": a.base_dir or "/"})
    res = {"ok": True, "app_uuid": uuid, "url": f"https://{check['host']}"}
    if getattr(a, "env_domain", None):  # the app exists now: report env failures instead of raising, so the uuid is never lost
        res["env_domain"], res["env_errors"] = _set_domain_envs(uuid, check["host"], a.env_domain)
    if getattr(a, "env_url", None):
        res["env_url"], errors = _set_domain_envs(uuid, check["host"], a.env_url, scheme="https://")
        res["env_errors"] = res.get("env_errors", []) + errors
    if getattr(a, "env_generate", None):
        res["env_generated"], errors = _generate_envs(uuid, a.env_generate)
        res["env_errors"] = res.get("env_errors", []) + errors
    return res


# Secret formats for env-generate (KEY or KEY:format). «laravel»: APP_KEY as key:generate makes it.
SECRET_FORMATS = {
    "": lambda: secrets.token_urlsafe(50),
    "laravel": lambda: "base64:" + base64.b64encode(secrets.token_bytes(32)).decode(),
}


def _generated_key(spec: str) -> tuple[str, str] | None:
    """«KEY» or «KEY:format» → (KEY, format), or None when the name or the format is not valid."""
    key, _, fmt = spec.partition(":")
    return (key, fmt) if ENV_KEY.fullmatch(key) and fmt in SECRET_FORMATS else None


def _generate_envs(app_uuid: str, specs: list[str]) -> tuple[dict, list[dict]]:
    """Set each KEY to a random secret (e.g. DJANGO_SECRET_KEY, APP_KEY:laravel) unless it already exists:
    re-running never rotates it. The value goes straight to the API and is never printed or stored locally."""
    existing = {e.get("key") for e in api("GET", f"/applications/{app_uuid}/envs") or [] if not e.get("is_preview")}
    done, errors = {}, []
    wanted = {}
    for spec in specs:  # one value per key: «KEY KEY:laravel» never sets the key twice
        wanted.setdefault(_generated_key(spec)[0], spec)
    for key, spec in wanted.items():
        fmt = _generated_key(spec)[1]
        if key in existing:
            done[key] = "kept"
            continue
        try:
            _set_env(app_uuid, key, SECRET_FORMATS[fmt](), secret=True, buildtime=False)
            done[key] = "created"
        except Error as e:
            errors.append({"key": spec, "error": str(e)})  # with its format: retry as is
    return done, errors


def cmd_env_generate(a):
    """Random secret values for KEY or KEY:format… (only for keys the app does not have yet)."""
    bad = [k for k in a.keys if not _generated_key(k)]
    if bad:
        raise Error(f"Invalid variable names: {', '.join(bad)}")
    done, errors = _generate_envs(resolve_app(a.app), a.keys)
    return {"ok": not errors, "env_generated": done, "env_errors": errors}


def _set_domain_envs(app_uuid: str, host: str, keys: list[str], scheme: str = "") -> tuple[list[str], list[dict]]:
    """Set each KEY=<host> (or <scheme><host>, e.g. APP_URL=https://host) as a runtime variable (public value)."""
    done, errors = [], []
    for key in dict.fromkeys(keys):
        try:
            _set_env(app_uuid, key, scheme + host, secret=False, buildtime=False)
            done.append(key)
        except Error as e:
            errors.append({"key": key, "error": str(e)})
    return done, errors


def cmd_env_domain(a, scheme: str = ""):
    """Set KEY=<the app's domain host> (e.g. NG_ALLOWED_HOSTS) without the value going through the command line."""
    bad = [k for k in a.keys if not ENV_KEY.fullmatch(k)]
    if bad:
        raise Error(f"Invalid variable names: {', '.join(bad)}")
    app = resolve_app(a.app)
    fqdn = (api("GET", f"/applications/{app}") or {}).get("fqdn") or ""
    host = host_of(fqdn.split(",")[0]) if fqdn else ""
    if not host:
        raise Error("The app has no domain")
    done, errors = _set_domain_envs(app, host, a.keys, scheme)
    return {"ok": not errors, "host": host, "env_url" if scheme else "env_domain": done, "env_errors": errors}


def cmd_env_url(a):
    """Set KEY=https://<the app's domain host> (e.g. APP_URL)."""
    return cmd_env_domain(a, scheme="https://")


def _set_env(app_uuid: str, key: str, value: str, secret: bool, buildtime: bool | None = None) -> dict:
    """Create or update a variable. Secret = literal, shown once in the UI, and runtime only unless buildtime=True
    (needed when the build inlines it, e.g. SvelteKit $env/static). Non-secret: build time too unless buildtime=False."""
    body = {"key": key, "value": value, "is_preview": False, "is_literal": True,
            "is_buildtime": (not secret) if buildtime is None else buildtime, "is_runtime": True}
    if secret:
        body["is_shown_once"] = True
    existing = api("GET", f"/applications/{app_uuid}/envs") or []
    if any(e.get("key") == key and not e.get("is_preview") for e in existing):
        api("PATCH", f"/applications/{app_uuid}/envs", body)
        return {"key": key, "action": "updated"}
    api("POST", f"/applications/{app_uuid}/envs", body)
    return {"key": key, "action": "created"}


def cmd_env_set(a):
    app = resolve_app(a.app)
    if "=" not in a.pair:
        raise Error("Format: KEY=value")
    key, value = a.pair.split("=", 1)
    if a.stdin:
        value = sys.stdin.read().rstrip("\n")
    return {"ok": True, **_set_env(app, key.strip(), value, secret=a.secret)}


def cmd_env_push(a):
    """Upload KEY=value lines from a file without the values going through the chat.

    Public variables (NEXT_PUBLIC_*, VITE_*…) are also available at build time (they end up in the browser
    bundle); keys in --buildtime too (secret, but inlined by the build); everything else is runtime only and
    hidden. Only names are returned.
    """
    app = resolve_app(a.app)
    path = Path(a.file).expanduser()
    if not path.exists():
        raise Error(f"{path} does not exist")
    result, empty = [], []
    pairs = _read_env_file(path)
    buildtime = getattr(a, "buildtime", None) or []
    not_in_file = sorted(set(buildtime) - {k for k, _ in pairs})
    if a.only:
        missing = sorted(set(a.only) - {k for k, _ in pairs})
        if missing:
            raise Error(f"Not in {path.name}: {', '.join(missing)}")
        pairs = [(k, v) for k, v in pairs if k in a.only]
    for key, value in pairs:
        if not value:  # never overwrite a value (e.g. DATABASE_URL set by create-postgres) with an empty one
            empty.append(key)
            continue
        public = key.startswith(PUBLIC_PREFIXES)
        build = public or key in buildtime
        result.append({**_set_env(app, key, value, secret=not public, buildtime=build), "public": public,
                       "buildtime": build})
    res = {"ok": True, "variables": result, "skipped_empty": empty}
    if not_in_file:  # e.g. DATABASE_URL set by create-postgres: use its --buildtime instead
        res["buildtime_not_in_file"] = not_in_file
    return res


def _read_env_file(path: Path) -> list[tuple[str, str]]:
    pairs = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        pairs.append((key.strip(), value.strip().strip("\"'")))
    return pairs


ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
APP_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def cmd_env_template(a):
    """Create or extend secrets/<app>.env with empty keys for the user to fill in. Never touches existing values."""
    if not APP_NAME.fullmatch(a.app):
        raise Error("App name: lowercase letters, digits and hyphens")
    bad = [k for k in a.keys if not ENV_KEY.fullmatch(k)]
    if bad:
        raise Error(f"Invalid variable names: {', '.join(bad)}")
    folder = CONFIG_DIR / "secrets"
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    path = folder / f"{a.app}.env"
    existing = dict(_read_env_file(path)) if path.exists() else {}
    added = [k for k in dict.fromkeys(a.keys) if k not in existing]
    if added:
        text = path.read_text() if path.exists() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        path.write_text(text + "".join(f"{k}=\n" for k in added))
    path.touch()
    path.chmod(0o600)
    keys = {**existing, **{k: "" for k in added}}
    return {"ok": True, "file": str(path), "added": added, "already_present": [k for k in a.keys if k in existing],
            "empty": sorted(k for k, v in keys.items() if not v)}


def cmd_env_list(a):
    app = resolve_app(a.app)
    envs = api("GET", f"/applications/{app}/envs") or []
    # Coolify keeps a copy of every variable for preview deployments: hide those
    return {"ok": True, "variables": [{"key": e.get("key"), "build": e.get("is_buildtime"),
                                       "runtime": e.get("is_runtime")} for e in envs if not e.get("is_preview")]}


def cmd_env_delete(a):
    """Delete a variable (and its preview copy). Requires --confirmed."""
    if not a.confirmed:
        raise Error("Deleting a variable requires --confirmed (ask the user first).")
    app = resolve_app(a.app)
    envs = [e for e in (api("GET", f"/applications/{app}/envs") or []) if e.get("key") == a.key]
    if not envs:
        raise Error(f"The app has no variable {a.key}")
    for e in envs:
        api("DELETE", f"/applications/{app}/envs/{e['uuid']}")
    return {"ok": True, "key": a.key, "deleted": len(envs)}


def cmd_protect(a):
    """Basic auth handled by Coolify's proxy. The password is generated here and stored in secrets/<app>.access."""
    app = resolve_app(a.app)
    if a.off:
        api("PATCH", f"/applications/{app}", {"is_http_basic_auth_enabled": False})
        return {"ok": True, "protected": False, "note": "redeploy for the change to take effect"}
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", a.user):
        raise Error("User: letters, digits, dot, hyphen or underscore")
    name = a.app if APP_NAME.fullmatch(a.app) else app
    password = random_password(24)
    api("PATCH", f"/applications/{app}", {"is_http_basic_auth_enabled": True, "http_basic_auth_username": a.user,
                                         "http_basic_auth_password": password})
    folder = CONFIG_DIR / "secrets"
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    path = folder / f"{name}.access"
    path.write_text(f"user={a.user}\npassword={password}\n")
    path.chmod(0o600)
    return {"ok": True, "protected": True, "user": a.user, "credentials_file": str(path),
            "note": "redeploy for the change to take effect; the password is only in that file"}


def cmd_deploy(a):
    app = resolve_app(a.app)
    r = api("POST", "/deploy", query={"uuid": app, "force": "true" if a.force else "false"})
    deps = r.get("deployments") or []
    if not deps:
        raise Error(f"Coolify did not create a deployment: {r}")
    return {"ok": True, "deployment_uuid": deps[0].get("deployment_uuid"), "message": deps[0].get("message")}


def _last_lines(logs_json: str | None, n: int) -> list[str]:
    try:
        entries = json.loads(logs_json or "[]")
    except json.JSONDecodeError:
        return [mask(l) for l in (logs_json or "").splitlines()[-n:]]
    lines = [e.get("output", "") for e in entries if not e.get("hidden")]
    return [mask(l) for l in "\n".join(lines).splitlines()[-n:]]


def cmd_wait(a):
    start = time.time()
    while True:
        d = api("GET", f"/deployments/{a.deployment}")
        state = d.get("status")
        if state in FINAL_STATES:
            res = {"ok": state == "finished", "status": state, "seconds": int(time.time() - start),
                   "commit": (d.get("commit") or "")[:7]}
            if state != "finished":
                res["last_lines"] = _last_lines(d.get("logs"), a.lines)
            return res
        if time.time() - start > a.timeout:
            return {"ok": False, "status": state, "timeout": True, "last_lines": _last_lines(d.get("logs"), 20)}
        time.sleep(5)


def cmd_last_deployment(a):
    app = resolve_app(a.app)
    deps = api("GET", f"/deployments/applications/{app}", query={"take": 1})
    items = deps.get("deployments", deps) if isinstance(deps, dict) else deps
    if not items:
        return {"ok": True, "deployment": None}
    d = items[0]
    return {"ok": True, "deployment_uuid": d.get("deployment_uuid"), "status": d.get("status"),
            "commit": (d.get("commit") or "")[:7], "webhook": d.get("is_webhook"), "created": d.get("created_at")}


def cmd_logs(a):
    app = resolve_app(a.app)
    r = api("GET", f"/applications/{app}/logs", query={"lines": a.lines})
    return {"ok": True, "logs": mask(r.get("logs", "") if isinstance(r, dict) else str(r))}


def cmd_rollback(a):
    """Without --image: list the images (read-only). With --image: roll back (needs --confirmed)."""
    app = resolve_app(a.app)
    if not a.image:
        r = api("GET", f"/applications/{app}/rollback-images") or {}
        return {"ok": True, "current": r.get("current"), "images": r.get("images", [])}
    if not a.confirmed:
        raise Error("Rollback requires --confirmed (the user must approve it first).")
    r = api("POST", f"/applications/{app}/rollback", {"commit": a.image}) or {}
    return {"ok": True, "message": r.get("message"), "deployment_uuid": r.get("deployment_uuid")}


GRACE_WITHOUT_SSH = 45  # seconds to let Coolify's background cleanup run when it cannot be observed
SETTLE_SECONDS = 5  # after containers and volumes are gone, Coolify still removes networks/folders


def _wait_until_gone(path: str, timeout: int = 180) -> bool:
    """Wait until the API returns 404. Coolify answers 404 as soon as the record is marked deleted, BEFORE its
    background job cleans up the server, so this alone does not mean the cleanup has finished."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            api("GET", path)
        except Error as e:
            if e.status == 404:
                return True
            raise
        time.sleep(3)
    return False


def _remote_leftovers(target: str, uuids: list[str]) -> list[str] | None:
    """Containers and volumes on the server whose name contains one of the uuids (None if ssh fails)."""
    pattern = "|".join(re.escape(u) for u in uuids)
    script = "docker ps -a --format 'container {{.Names}}'; docker volume ls --format 'volume {{.Name}}'"
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, "sh -s"],
                           input=script, capture_output=True, text=True, timeout=40)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if r.returncode != 0:
        return None
    return [line for line in r.stdout.splitlines() if re.search(pattern, line)]


def _remove_app_images(target: str, app_uuid: str) -> int | None:
    """Coolify keeps the images of a deleted app (named exactly after its uuid). Remove only those."""
    if not re.fullmatch(r"[a-z0-9]{10,40}", app_uuid):
        return None
    script = (f"imgs=$(docker images --format '{{{{.Repository}}}}:{{{{.Tag}}}}' | grep '^{app_uuid}:'); "
              "[ -n \"$imgs\" ] && docker image rm $imgs >/dev/null; echo \"$imgs\" | grep -c . || true")
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, "sh -s"],
                           input=script, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    out = r.stdout.strip().splitlines()
    return int(out[-1]) if r.returncode == 0 and out and out[-1].isdigit() else None


def _wait_for_cleanup(uuids: list[str], timeout: int = 180) -> tuple[bool, str]:
    """Wait for Coolify's background cleanup of these resources. Returns (finished, how it was checked)."""
    target = (read_json(CONFIG, {}) or {}).get("ssh")
    if not target:
        time.sleep(GRACE_WITHOUT_SSH)
        return True, f"not observed (no ssh in the configuration): waited {GRACE_WITHOUT_SSH} s"
    deadline = time.time() + timeout
    left = None
    while time.time() < deadline:
        left = _remote_leftovers(target, uuids)
        if left is None:
            time.sleep(GRACE_WITHOUT_SSH)
            return True, f"not observed (ssh failed): waited {GRACE_WITHOUT_SSH} s"
        if not left:
            time.sleep(SETTLE_SECONDS)
            return True, "observed over ssh: no containers or volumes left"
        time.sleep(5)
    return False, "still on the server after {} s: {}".format(timeout, ", ".join(left or []))


def cmd_decommission(a):
    if not a.confirmed:
        raise Error("Decommission requires --confirmed (the user must approve it first).")
    reg = registry()
    app = resolve_app(a.app)
    # The registry entry may be keyed by another name than the one given (e.g. the app was given by uuid)
    name = a.app if a.app in reg else next((k for k, v in reg.items() if v.get("app_uuid") == app), a.app)
    entry = reg.get(name, {})
    unknown = [what for what, flag, key in (("database", a.with_db, "db_uuid"), ("project", a.with_project, "project_uuid"))
               if flag and not entry.get(key)]
    if unknown:  # refuse before deleting anything, so nothing is left half done
        raise Error(f"The {' and '.join(unknown)} of this app are not in the local registry (apps.json): nothing was "
                    "deleted. Run without --with-db/--with-project and delete them in Coolify, or by their own uuid")
    backups = []
    if a.with_db:  # Coolify keeps the backup files of a deleted database: delete them first, through the API
        dbu = reg[name]["db_uuid"]
        try:
            configs = _configs(dbu)
        except Error as e:
            if e.status != 404:  # 404 = no backup API (Coolify before 4.6): nothing to delete
                raise
            configs = []
        for cfg in configs:
            try:
                api("DELETE", f"/databases/{dbu}/backups/{cfg['uuid']}")
                backups.append(cfg["uuid"])
            except Error as e:
                raise Error(f"Could not delete the backups {cfg['uuid']} of the database ({e}); deleted so far: "
                            f"{', '.join(backups) or 'none'}. Nothing else was deleted: run decommission again") from None
    api("DELETE", f"/applications/{app}", query={"delete_configurations": "true", "delete_volumes": "true",
                                                   "docker_cleanup": "true", "delete_connected_networks": "true"})
    deleted = {"app": app, **({"backups": backups} if a.with_db else {})}
    pending = [f"/applications/{app}"]
    if a.with_db:
        api("DELETE", f"/databases/{reg[name]['db_uuid']}", query={"delete_volumes": "true"})
        deleted["db"] = reg[name]["db_uuid"]
        pending.append(f"/databases/{reg[name]['db_uuid']}")
    # Deleting the project before Coolify's background job finishes makes that job fail («project on null»)
    # and leaves volumes, images and folders orphaned. The API answers 404 before the job runs, so the
    # cleanup itself is watched on the server.
    unfinished = [p for p in pending if not _wait_until_gone(p)]
    finished, how = (False, "") if unfinished else _wait_for_cleanup([u for u in (app, deleted.get("db")) if u])
    deleted["cleanup"] = how
    if unfinished or not finished:
        deleted["warning"] = ("Coolify did not finish deleting in time: " + (", ".join(unfinished) or how)
                              + " (project kept; run decommission again later or delete it in Coolify)")
    else:
        target = (read_json(CONFIG, {}) or {}).get("ssh")
        removed = _remove_app_images(target, app) if target else None
        deleted["images"] = removed if removed is not None else "left to Coolify's scheduled Docker cleanup"
    sharing = sorted(k for k, v in reg.items() if k != name and v.get("project_uuid") == entry.get("project_uuid"))
    if not deleted.get("warning") and a.with_project and sharing:  # one project per repository: others still in it
        deleted["project_kept"] = f"other apps still in it: {', '.join(sharing)}"
    elif not deleted.get("warning") and a.with_project:
        try:
            api("DELETE", f"/projects/{reg[name]['project_uuid']}")
            deleted["project"] = reg[name]["project_uuid"]
        except Error as e:
            deleted["project_not_deleted"] = str(e)
    if name in reg:
        del reg[name]
        write_json(REGISTRY, reg)
    if APP_NAME.fullmatch(name):  # the app is gone: its local variable values and credentials are useless now
        removed = [f for f in (CONFIG_DIR / "secrets" / f"{name}.env", CONFIG_DIR / "secrets" / f"{name}.access")
                   if f.exists()]
        for f in removed:
            f.unlink()
        if removed:
            deleted["local_files"] = [str(f) for f in removed]
    return {"ok": True, "deleted": deleted}


# ---------------------------------------------------------------- PostgreSQL backups
# Coolify runs, rotates and records the backups (pg_dump --format=custom on the server). Retention is per backup
# configuration and deletes the files beyond the limit, so the skill keeps two configurations per database:
#   scheduled  enabled, the user's frequency, keep 7 by default
#   manual     disabled (never runs on its own): backup-now and the safety backup before a restore, keep 5
# They are told apart by a timeout value only the skill sets; configurations made in Coolify are never changed.

MIN_BACKUP_VERSION = (4, 6, 0)  # the only version whose API this was checked against
TIMEOUT_SCHEDULED = 3601
TIMEOUT_MANUAL = 3599
DEFAULT_KEEP = 7
MANUAL_KEEP = 5
MANUAL_FREQUENCY = "0 0 1 1 *"  # required by the API; unused while the configuration is disabled
FREQUENCY_KEYWORDS = {"hourly", "daily", "weekly", "monthly", "yearly"}
CRON_FIELD = re.compile(r"[0-9*/,-]+")
DB_UUID = re.compile(r"[a-z0-9]{10,40}")
IMPORT_FINAL = {"finished", "error", "killed", "cancelled", "closed"}
IMPORT_REFUSED = {400, 401, 403, 404, 413, 422}  # answers to the import POST that mean «not started»
POLL_SECONDS = 5
# Failure output may quote rows of the database (CONTEXT/DETAIL lines, «Command was»): keep only error lines
ERROR_LINE = re.compile(r"^\s*(ERROR:|FATAL:|pg_restore: error:|pg_dump: error:|Blocked PostgreSQL restore|"
                        r".*Nothing was changed)")


def valid_frequency(value: str) -> bool:
    if value in FREQUENCY_KEYWORDS:
        return True
    fields = value.split()
    return len(fields) == 5 and all(CRON_FIELD.fullmatch(f) for f in fields)


def error_lines(text, limit: int = 10) -> list[str]:
    lines = [mask(line.strip())[:300] for line in str(text or "").splitlines() if ERROR_LINE.match(line)]
    return lines[-limit:]


def _check_backup_version() -> None:
    v = api("GET", "/version")
    text = v.get("text", "") if isinstance(v, dict) else v
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", str(text))
    if not m or tuple(int(x) for x in m.groups()) < MIN_BACKUP_VERSION:
        found = m.group(0) if m else "unknown"
        raise Error(f"Database backups need Coolify {'.'.join(map(str, MIN_BACKUP_VERSION))} or later "
                    f"(found {found}). Update Coolify first.")


def _registry_db(app: str) -> str | None:
    reg = registry()
    entry = reg.get(app) or next((v for v in reg.values() if v.get("app_uuid") == app), {})
    return entry.get("db_uuid")


def _backup_target(a) -> tuple[str, dict]:
    """(database uuid, database detail) for --db or the app's database in apps.json; PostgreSQL only."""
    _check_backup_version()
    db = getattr(a, "db", None) or _registry_db(a.app)
    if not db:
        raise Error(f"No database of {a.app!r} in the local registry (apps.json): pass --db <uuid> "
                    "(see «status» for the uuids)")
    if not DB_UUID.fullmatch(db):
        raise Error(f"Invalid database uuid: {db!r}")
    info = api("GET", f"/databases/{db}") or {}
    if info.get("database_type") != "standalone-postgresql":
        raise Error(f"Backups from the skill are only for PostgreSQL (this database is {info.get('database_type')})")
    return db, info


def _origin(cfg: dict) -> str:
    return {TIMEOUT_SCHEDULED: "scheduled", TIMEOUT_MANUAL: "manual"}.get(cfg.get("timeout"), "other")


def _server_timezone() -> str | None:
    """Coolify runs backup crons in the server's timezone (Settings of the server; UTC by default)."""
    server = (read_json(CONFIG, {}) or {}).get("server_uuid")
    try:
        return ((api("GET", f"/servers/{server}") or {}).get("settings") or {}).get("server_timezone") if server else None
    except Error:
        return None


def _configs(db: str) -> list[dict]:
    r = api("GET", f"/databases/{db}/backups")
    return r if isinstance(r, list) else []


def _kept(cfg: dict) -> list[dict]:
    """Successful executions whose file is still on the server, newest first."""
    ex = [e for e in cfg.get("executions") or [] if e.get("status") == "success" and not e.get("local_storage_deleted")]
    return sorted(ex, key=lambda e: str(e.get("created_at") or ""), reverse=True)


def _size(e: dict) -> int:
    try:
        return int(float(e.get("size") or 0))
    except (TypeError, ValueError):
        return 0


def _create_schedule(db: str, frequency: str = "daily", keep: int = DEFAULT_KEEP) -> str:
    body = {"frequency": frequency, "enabled": True, "save_s3": False,
            "database_backup_retention_amount_locally": keep, "timeout": TIMEOUT_SCHEDULED}
    return (api("POST", f"/databases/{db}/backups", body) or {}).get("uuid")


def cmd_backup_status(a):
    db, info = _backup_target(a)
    cfgs = _configs(db)
    schedules = [{"uuid": c.get("uuid"), "origin": _origin(c), "frequency": c.get("frequency"),
                  "enabled": c.get("enabled"), "keep": c.get("database_backup_retention_amount_locally"),
                  "keep_days": c.get("database_backup_retention_days_locally"), "save_s3": c.get("save_s3")}
                 for c in cfgs]
    kept = sorted(((e, _origin(c)) for c in cfgs for e in _kept(c)),
                  key=lambda p: str(p[0].get("created_at") or ""), reverse=True)
    backups = [{"uuid": e.get("uuid"), "created_at": e.get("created_at"), "size_bytes": _size(e), "origin": o}
               for e, o in kept[:10]]
    last_success = backups[0]["created_at"] if backups else None
    failed = sorted((str(e.get("created_at") or "") for c in cfgs for e in c.get("executions") or []
                     if e.get("status") == "failed"), reverse=True)
    last_failed = failed[0] if failed and (not last_success or failed[0] > str(last_success)) else None
    return {"ok": True, "db_uuid": db, "database_status": info.get("status"), "schedules": schedules,
            "timezone": _server_timezone(),
            "has_schedule": any(s["origin"] == "scheduled" for s in schedules),
            "has_any_schedule": any(s["enabled"] for s in schedules), "backups": backups,
            "last_success_at": last_success, "last_failed_at": last_failed}


def cmd_backup_schedule(a):
    if a.on and a.off:
        raise Error("--on and --off cannot go together")
    if a.frequency and not valid_frequency(a.frequency):
        raise Error(f"Invalid frequency {a.frequency!r}: use hourly, daily, weekly, monthly, yearly or a 5-field cron")
    if a.keep is not None and a.keep < 1:
        raise Error("--keep must be 1 or more (the skill never keeps every backup forever: the disk would fill up)")
    db, _info = _backup_target(a)
    cfgs = _configs(db)
    if a.backup:
        cfg = next((c for c in cfgs if c.get("uuid") == a.backup), None)
        if not cfg:
            raise Error(f"No backup configuration {a.backup!r} on this database")
        if _origin(cfg) == "manual":
            raise Error("That is the skill's own configuration for on-demand backups (no schedule, keeps "
                        f"{MANUAL_KEEP}): it is not changed")
    else:
        cfg = next((c for c in cfgs if _origin(c) == "scheduled"), None)
        others = [c.get("uuid") for c in cfgs if _origin(c) == "other"]
        if not cfg and others:
            raise Error("This database has backup configurations made in Coolify: choose one with --backup "
                        f"({', '.join(others)}) or change them in Coolify")
    if not cfg:
        if a.off:
            return {"ok": True, "created": False, "enabled": False, "message": "no schedule to turn off"}
        keep = a.keep or DEFAULT_KEEP
        uuid = _create_schedule(db, a.frequency or "daily", keep)
        return {"ok": True, "created": True, "backup_uuid": uuid, "frequency": a.frequency or "daily", "keep": keep}
    changes = {}
    if a.frequency and a.frequency != cfg.get("frequency"):
        changes["frequency"] = a.frequency
    if a.keep is not None and a.keep != cfg.get("database_backup_retention_amount_locally"):
        would_delete = max(0, len(_kept(cfg)) - a.keep)
        if would_delete and not a.confirmed:
            return {"ok": False, "needs_confirmation": True, "would_delete": would_delete,
                    "error": f"Keeping {a.keep} deletes the {would_delete} oldest backup(s) at the next run: "
                             "ask the user, then repeat with --confirmed"}
        changes["database_backup_retention_amount_locally"] = a.keep
    # A stopped schedule starts again only when asked: with --on, or with a bare call on the skill's own
    # schedule. Changing --frequency or --keep alone leaves it stopped.
    bare = not (a.frequency or a.keep is not None or a.off)
    if a.off and cfg.get("enabled"):
        changes["enabled"] = False
    elif not cfg.get("enabled") and (a.on or (bare and _origin(cfg) == "scheduled")):
        changes["enabled"] = True
    if changes:
        api("PATCH", f"/databases/{db}/backups/{cfg['uuid']}", changes)
    merged = {**cfg, **changes}
    result = {"ok": True, "created": False, "backup_uuid": cfg.get("uuid"), "changed": sorted(changes),
              "frequency": merged.get("frequency"), "keep": merged.get("database_backup_retention_amount_locally"),
              "enabled": merged.get("enabled")}
    if not merged.get("enabled") and not a.off:
        result["message"] = "The schedule stays stopped: add --on to start it again"
    return result


def _backup_now(db: str, info: dict, timeout: int) -> dict:
    """Run a backup in the manual configuration and wait for its execution. Returns the execution."""
    status = str(info.get("status") or "")
    if not status.startswith("running"):
        raise Error(f"The database is not running ({status or 'unknown'}): Coolify skips backups of stopped "
                    "databases. Start it in Coolify first")
    manual = next((c for c in _configs(db) if _origin(c) == "manual"), None)
    if manual:
        before = {e.get("uuid") for e in manual.get("executions") or []}
        backup = manual["uuid"]
        api("PATCH", f"/databases/{db}/backups/{backup}", {"backup_now": True})
    else:
        before = set()
        body = {"frequency": MANUAL_FREQUENCY, "enabled": False, "save_s3": False, "backup_now": True,
                "database_backup_retention_amount_locally": MANUAL_KEEP, "timeout": TIMEOUT_MANUAL}
        backup = (api("POST", f"/databases/{db}/backups", body) or {}).get("uuid")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        r = api("GET", f"/databases/{db}/backups/{backup}/executions") or {}
        new = [e for e in r.get("executions") or [] if e.get("uuid") not in before]
        if new and new[0].get("status") in ("success", "failed"):
            return new[0]
    raise Error(f"The backup did not finish in {timeout} s; it may still be running on the server: "
                "check with backup-status")


def _execution_result(e: dict) -> dict:
    r = {"ok": e.get("status") == "success", "execution_uuid": e.get("uuid"), "status": e.get("status"),
         "size_bytes": _size(e), "created_at": e.get("created_at")}
    if not r["ok"]:
        r["error"] = "the backup failed"
        r["message"] = error_lines(e.get("message")) or ["no error line in the message (see the backup in Coolify)"]
    return r


def cmd_backup_now(a):
    db, info = _backup_target(a)
    return _execution_result(_backup_now(db, info, a.timeout))


def _find_execution(db: str, uuid: str) -> dict | None:
    return next((e for c in _configs(db) for e in c.get("executions") or [] if e.get("uuid") == uuid), None)


def _import_summary(imp, r: dict) -> dict:
    """Result of a restore from GET .../imports/{id}: running, finished (ok) or failed (error lines only)."""
    status = r.get("status")
    out = {"import_id": imp, "status": status, "exit_code": r.get("exit_code"), "finished": status in IMPORT_FINAL}
    out["ok"] = status == "finished" and r.get("exit_code") in (0, None)
    if out["finished"] and not out["ok"]:
        out["error"] = "the restore failed"
        out["output"] = error_lines(r.get("output")) or ["no error line in the output (see the database in Coolify)"]
    return out


def _import_result(db: str, imp, timeout: int) -> dict:
    deadline = time.time() + timeout
    r = {}
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        r = api("GET", f"/databases/{db}/imports/{imp}") or {}
        if r.get("status") in IMPORT_FINAL:
            return _import_summary(imp, r)
    return {**_import_summary(imp, r), "ok": False,
            "error": f"The restore did not finish in {timeout} s and is still running on the server: "
                     f"check it with backup-restore-status <app> {imp}"}


MAX_IMPORT_BYTES = 10 * 1024 ** 3  # Coolify refuses larger imports (StartDatabaseImport::MAX_BYTES)
MIN_CLEAN_RESTORE_PG = 150000  # CREATE SCHEMA … AUTHORIZATION pg_database_owner, as PostgreSQL 15+ creates «public»
CONTAINER_COPY = "/tmp/coolify-ops-before-restore.dump"
DUMP_NAME = re.compile(r"/pg-dump-(?P<db>.+)-\d+-[A-Za-z0-9]+\.dmp")
# Third field: tables, views, sequences… in every schema of the user (not only «public»): 0 = nothing to protect.
STATE_SQL = ("SELECT current_setting('server_version_num'), current_database(), "
             "(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
             "WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f') AND n.nspname <> 'information_schema' "
             "AND n.nspname NOT LIKE 'pg\\_%');")
# Empties «public» as PostgreSQL 15+ creates it. One transaction: a lock held by the app for 30 s cancels all of it.
RESET_SQL = ("SET lock_timeout = '30s';\nDROP SCHEMA public CASCADE;\n"
             "CREATE SCHEMA public AUTHORIZATION pg_database_owner;\nGRANT USAGE ON SCHEMA public TO PUBLIC;\n")
PSQL = 'psql -X -q -At -1 -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -'


def _ssh_db(target: str, db: str, command: str, stdin: str = "", timeout: int = 600):
    """Run a shell command inside the database container over ssh; stdin (e.g. SQL) goes to it as a quoted
    heredoc, never inside a shell string. db is validated by the caller. Returns (exit code, stdout, stderr)."""
    script = f"docker exec -i {db} sh -c '{command}'"
    if stdin and not stdin.endswith("\n"):  # the heredoc end marker must be on a line of its own
        stdin += "\n"
    script += f" <<'COOLIFY_OPS_EOF'\n{stdin}COOLIFY_OPS_EOF\n" if stdin else " </dev/null\n"
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, "sh -s"],
                           input=script, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 255, "", f"ssh failed: {type(e).__name__}"
    return r.returncode, r.stdout, r.stderr


def _ssh_lost(code: int) -> bool:
    """ssh itself failed, timed out or was killed: what it was running may or may not have finished."""
    return code == 255 or code < 0


def _reset(target: str, db: str) -> tuple[bool | None, str]:
    """True = emptied; False = failed and nothing changed (one transaction); None = ssh died, state unknown."""
    code, _out, err = _ssh_db(target, db, PSQL, RESET_SQL)
    if code == 0:
        return True, ""
    if _ssh_lost(code):  # the transaction may or may not have been committed
        return None, "lost the ssh connection while emptying the database"
    if "canceling statement due to lock timeout" in err:
        return False, "the database is busy (a lock held for more than 30 s): nothing changed, try again"
    return False, "could not empty the database: " + (" | ".join(error_lines(err)) or f"exit {code}")


def _recover(target: str, db: str) -> bool | None:
    """Put back the copy taken inside the container before the reset. True = done (copy removed); False = failed;
    None = ssh was lost meanwhile, state unknown. The copy is kept unless it was put back."""
    ok, _msg = _reset(target, db)
    if ok:
        code, _o, _e = _ssh_db(target, db, 'pg_restore --exit-on-error --single-transaction --no-owner --no-acl '
                               f'-U "$POSTGRES_USER" -d "$POSTGRES_DB" {CONTAINER_COPY}', timeout=1800)
        ok = None if _ssh_lost(code) else code == 0
    if ok:
        _ssh_db(target, db, f"rm -f {CONTAINER_COPY}")
    return ok


def cmd_backup_restore(a):
    """Clean restore: safety backup, a copy inside the container, empty «public», Coolify's import; if the import
    fails, the copy is put back by the script itself. Every check runs before anything changes."""
    if not a.confirmed:
        raise Error("Restore requires --confirmed (the user must approve it first).")
    target = (read_json(CONFIG, {}) or {}).get("ssh")
    if not target:
        raise Error("backup-restore needs «ssh» in the configuration (coolify.py init --ssh user@server): the "
                    "database is emptied and, if the import fails, put back over ssh. Nothing was changed")
    db, info = _backup_target(a)
    chosen = _find_execution(db, a.execution)
    if not chosen or chosen.get("status") != "success" or chosen.get("local_storage_deleted"):
        raise Error(f"{a.execution!r} is not a successful backup of this database still on the server "
                    "(see backup-status)")
    if _size(chosen) > MAX_IMPORT_BYTES:
        raise Error("This backup is larger than 10 GiB, the most Coolify imports: nothing was changed")
    code, out, err = _ssh_db(target, db, PSQL, STATE_SQL)
    if code != 0:
        raise Error("Cannot read the database over ssh: " + (" | ".join(error_lines(err)) or mask(err.strip()[-200:])))
    try:
        version, current_db, objects = (out.strip().splitlines() or [""])[-1].split("|")
        version, objects = int(version), int(objects)
    except ValueError:
        raise Error("Unexpected answer from the database over ssh: nothing was changed") from None
    m = DUMP_NAME.search(str(chosen.get("filename") or ""))
    if not m or m.group("db") != re.sub(r"[^A-Za-z0-9_.-]", "-", current_db):
        raise Error("This backup is not a dump of this app's database (another database, or all of them): "
                    "nothing was changed")
    if version < MIN_CLEAN_RESTORE_PG:
        raise Error(f"A clean restore needs PostgreSQL 15 or later (this one is {version}): nothing was changed")
    has_data = objects > 0
    safety = None
    if has_data:  # a database with nothing in it needs no copies (and retries must not rotate the real ones out)
        s = _backup_now(db, info, a.backup_timeout)
        if s.get("status") != "success":
            return {**_execution_result(s), "error": "the safety backup failed: nothing was restored"}
        safety = s.get("uuid")
    again = _find_execution(db, a.execution)  # retention runs after every backup: is the chosen file still there?
    if not again or again.get("local_storage_deleted"):
        return {"ok": False, "safety_backup": safety, "error": "the chosen backup no longer exists on the server "
                "(removed by retention): nothing was restored"}
    base = {"restored_from": {"uuid": again.get("uuid"), "created_at": again.get("created_at")},
            "safety_backup": safety}
    if has_data:
        code, _o, err = _ssh_db(target, db, 'pg_dump --format=custom -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                                f'-f {CONTAINER_COPY}', timeout=1800)
        if code != 0:
            return {**base, "ok": False, "error": "could not copy the current data inside the container: nothing "
                    "was changed. " + " | ".join(error_lines(err))}
    ok, msg = _reset(target, db)
    copies = (f". The data from before is in {CONTAINER_COPY} inside the database container and in the safety "
              f"backup {safety} (backup-restore --execution {safety})") if has_data else ""
    unknown = {**base, "ok": False, "state_unknown": True, "copy_in_container": CONTAINER_COPY if has_data else None}
    if ok is None:  # the copies are the only sure thing left: keep them and say where they are
        return {**unknown, "error": f"{msg}: it may be empty or as before. Do not restore again yet: look at the "
                                    f"data in the app first{copies}"}
    if not ok:
        if has_data:
            _ssh_db(target, db, f"rm -f {CONTAINER_COPY}")
        return {**base, "ok": False, "error": msg}
    try:
        r = api("POST", f"/databases/{db}/imports",
                {"source": "server", "path": again.get("filename"), "replace_existing": True}) or {}
    except Error as e:
        r = None
        if e.status in IMPORT_REFUSED:  # a definite «no» (size, validation, permission): nothing is running
            result = {"ok": False, "finished": True, "error": f"Coolify refused the import: {e}"}
        else:  # 5xx, 409 or no answer at all: Coolify may be running an import, recovering now would race it
            return {**unknown, "error": f"No clear answer from Coolify when starting the restore ({e}): it may be "
                                        f"running. Do not restore again yet: wait, then look at the data in the app{copies}"}
    if r is not None and not (isinstance(r, dict) and r.get("id")):  # accepted, but nothing to follow it with
        return {**unknown, "error": "Coolify accepted the restore but gave no id to follow it: it may be running. "
                                    f"Do not restore again yet: wait, then look at the data in the app{copies}"}
    if r is not None:
        try:
            result = _import_result(db, r.get("id"), a.timeout)
        except Error as e:  # lost contact while polling: the import may still be running, never race it
            result = {"ok": False, "finished": False, "import_id": r.get("id"),
                      "error": f"Lost contact with Coolify while the restore runs on the server ({e}): check it "
                               f"with backup-restore-status <app> {r.get('id')}"}
    if result.get("ok"):
        if has_data:
            _ssh_db(target, db, f"rm -f {CONTAINER_COPY}")
        return {**result, **base}
    if not result.get("finished"):  # still running on the server: recovering now would race it
        advice = (f"; if it ends in failure, restore the safety backup (backup-restore --execution {safety})"
                  if has_data else "; the database was empty before the restore: if it fails there is nothing to put back")
        return {**result, **base, "copy_in_container": CONTAINER_COPY if has_data else None,
                "error": result.get("error", "the restore is still running") + advice}
    failure = result.get("error", "the restore failed")
    if not has_data:  # nothing to put back: «recovered» is null, not true
        return {**result, **base, "ok": False, "recovered": None,
                "error": f"{failure}; the database was empty before the restore and is empty now"}
    recovered = _recover(target, db)
    if recovered is None:
        return {**result, **unknown, "error": f"{failure}, and the ssh connection was lost while putting the previous "
                                              "data back: the database may be empty, as before, or still being "
                                              f"restored. Do not restore again yet: wait, then look at the data in the app{copies}"}
    out = {**result, **base, "ok": False, "recovered": recovered}
    if recovered:
        out["error"] = f"{failure}; the data from before the restore was put back"
    else:
        out["error"] = (f"{failure} and putting the previous data back failed too: the database may be empty. "
                        f"Copies: {CONTAINER_COPY} inside the database container, and the safety backup {safety} "
                        f"(backup-restore --execution {safety})")
    return out


def cmd_backup_restore_status(a):
    """Read-only. While the restore runs: ok true, «finished» false. Finished: ok tells whether it worked."""
    if not re.fullmatch(r"\d{1,12}", str(a.import_id)):
        raise Error(f"Invalid import id: {a.import_id!r} (a number, from backup-restore)")
    db, _info = _backup_target(a)
    out = _import_summary(a.import_id, api("GET", f"/databases/{db}/imports/{a.import_id}") or {})
    return out if out["finished"] else {**out, "ok": True}


def _inside_git(path: Path) -> bool:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    if any((d / ".git").exists() for d in (p, *p.parents)):  # also when git gives no clear answer (see below)
        return True
    try:
        r = subprocess.run(["git", "-C", str(p), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False  # no git: not a repository
    return r.returncode == 0 and r.stdout.strip() == "true"


def cmd_backup_download(a):
    db, _info = _backup_target(a)
    target = (read_json(CONFIG, {}) or {}).get("ssh")
    if not target:
        raise Error("backup-download needs «ssh» in the configuration (coolify.py init --ssh user@server). "
                    "Without it, download a backup from Coolify: the database → Backups → Download")
    name = a.app if APP_NAME.fullmatch(a.app) else db
    default = not a.out
    out = (CONFIG_DIR / "backups" / name) if default else Path(a.out).expanduser()
    if _inside_git(out):
        raise Error(f"{out} is inside a git repository: a dump holds all the app's data and must never be "
                    "committed. Choose --out outside any git repository")
    out.mkdir(parents=True, exist_ok=True)
    if default:
        for d in (CONFIG_DIR, CONFIG_DIR / "backups", out):
            d.chmod(0o700)
    final = out / f"{name}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.dump"
    part = final.with_name(final.name + ".part")
    # db is validated above; the single quotes keep $POSTGRES_* for the container's shell (no password needed)
    script = f"docker exec {db} sh -c 'pg_dump --format=custom -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\"'\n"
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, "sh -s"],
                               input=script.encode(), stdout=f, stderr=subprocess.PIPE, timeout=a.timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        part.unlink(missing_ok=True)
        raise Error(f"The download did not finish ({type(e).__name__}): nothing was kept") from None
    with open(part, "rb") as f:
        magic = f.read(5)
    if r.returncode != 0 or magic != b"PGDMP":
        part.unlink(missing_ok=True)
        detail = error_lines(r.stderr.decode(errors="replace"))
        if not detail and r.returncode == 255:
            detail = ["ssh failed (check «ssh <server>» works without a password)"]
        raise Error(f"The dump failed (exit {r.returncode}): nothing was kept. " + " | ".join(detail))
    part.replace(final)
    return {"ok": True, "file": str(final), "size_bytes": final.stat().st_size}


# ---------------------------------------------------------------- CLI


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coolify.py", description="Coolify API client for the coolify-ops skills")
    s = p.add_subparsers(dest="command", required=True)

    s.add_parser("check", help="Coolify version and token validity").set_defaults(f=cmd_check)

    c = s.add_parser("init", help="create/update the configuration (discovers server and GitHub App)")
    c.add_argument("--url"); c.add_argument("--domain", help="base domain, e.g. example.org")
    c.add_argument("--ssh", help="user@host of the Coolify server (optional: server checks, thorough decommission, backup restore and "
                   "download); re-running init keeps the saved server and GitHub App")
    c.add_argument("--server", help="Coolify server name (default: the saved one, else localhost)")
    c.add_argument("--github-app", dest="github_app")
    c.add_argument("--reserved", action="append", help="subdomain that must not be used (repeatable)")
    c.add_argument("--projects-dir", dest="projects_dir", help="folder where projects are cloned (default ~/Projects)")
    c.set_defaults(f=cmd_init)

    s.add_parser("status", help="apps and databases").set_defaults(f=cmd_status)

    c = s.add_parser("domain-check"); c.add_argument("host"); c.set_defaults(f=cmd_domain_check)

    c = s.add_parser("create-project"); c.add_argument("name"); c.add_argument("--description")
    c.set_defaults(f=cmd_create_project)

    c = s.add_parser("create-app")
    for arg in ("--project", "--repo", "--branch", "--port", "--domain", "--name"):
        c.add_argument(arg, required=True)
    c.add_argument("--environment", default="production"); c.add_argument("--cpus"); c.add_argument("--memory")
    c.add_argument("--dockerfile"); c.add_argument("--base-dir", dest="base_dir")
    c.add_argument("--watch-paths", dest="watch_paths", action="append", metavar="GLOB",
                   help="redeploy on push only when these repo-relative paths change (repeatable), e.g. 'frontend/**'")
    c.add_argument("--no-autodeploy", dest="no_autodeploy", action="store_true")
    c.add_argument("--env-domain", dest="env_domain", action="append", metavar="KEY",
                   help="set KEY=<the app's domain> as a runtime variable (repeatable), e.g. NG_ALLOWED_HOSTS")
    c.add_argument("--env-url", dest="env_url", action="append", metavar="KEY",
                   help="set KEY=https://<the app's domain> as a runtime variable (repeatable), e.g. APP_URL")
    c.add_argument("--env-generate", dest="env_generate", action="append", metavar="KEY[:FORMAT]",
                   help="set KEY to a random secret unless it exists (repeatable), e.g. DJANGO_SECRET_KEY, "
                        "APP_KEY:laravel")
    c.set_defaults(f=cmd_create_app)

    c = s.add_parser("env-generate", help="set KEY… to random secrets, only if missing (values are never printed); "
                                          "KEY:laravel gives a Laravel APP_KEY")
    c.add_argument("app"); c.add_argument("keys", nargs="+", metavar="KEY[:FORMAT]"); c.set_defaults(f=cmd_env_generate)

    c = s.add_parser("env-url", help="set KEY=https://<the app's domain> as a runtime variable (e.g. APP_URL)")
    c.add_argument("app"); c.add_argument("keys", nargs="+", metavar="KEY"); c.set_defaults(f=cmd_env_url)

    c = s.add_parser("env-domain", help="set KEY=<the app's domain> as a runtime variable (e.g. NG_ALLOWED_HOSTS)")
    c.add_argument("app"); c.add_argument("keys", nargs="+", metavar="KEY"); c.set_defaults(f=cmd_env_domain)

    c = s.add_parser("create-postgres")
    c.add_argument("--project", required=True); c.add_argument("--name", required=True)
    c.add_argument("--app", help="app name in the local registry"); c.add_argument("--app-uuid", dest="app_uuid")
    c.add_argument("--environment", default="production"); c.add_argument("--image", default="postgres:17-alpine")
    c.add_argument("--memory", default="512m")
    c.add_argument("--buildtime", action="store_true",
                   help="DATABASE_URL also at build time (when the build inlines it, e.g. SvelteKit $env/static/private)")
    c.add_argument("--env-key", dest="env_key", default="DATABASE_URL", metavar="KEY",
                   help="name of the app variable that receives the URL (Laravel: DB_URL)")
    c.add_argument("--backup", choices=["daily", "none"], default="daily",
                   help=f"daily backups on the server, last {DEFAULT_KEEP} kept (default) or none")
    c.set_defaults(f=cmd_create_postgres)

    c = s.add_parser("env-set", help="KEY=value (with --stdin the value is read from standard input)")
    c.add_argument("app"); c.add_argument("pair"); c.add_argument("--secret", action="store_true")
    c.add_argument("--stdin", action="store_true")
    c.set_defaults(f=cmd_env_set)

    c = s.add_parser("env-list", help="variable names (never values)"); c.add_argument("app")
    c.set_defaults(f=cmd_env_list)

    c = s.add_parser("env-template", help="create secrets/<app>.env with empty keys for the user to fill in")
    c.add_argument("app"); c.add_argument("keys", nargs="+"); c.set_defaults(f=cmd_env_template)

    c = s.add_parser("env-push", help="upload KEY=value lines from a file (values are never printed; empty ones skipped)")
    c.add_argument("app"); c.add_argument("file")
    c.add_argument("--only", nargs="+", metavar="KEY", help="upload only these keys (others in the file are left as they are)")
    c.add_argument("--buildtime", nargs="+", metavar="KEY", help="also make these keys available at build time")
    c.set_defaults(f=cmd_env_push)

    c = s.add_parser("protect", help="HTTP basic auth on the app's domain; the password is saved locally, never printed")
    c.add_argument("app"); c.add_argument("--user", default="admin")
    c.add_argument("--off", action="store_true", help="remove the protection")
    c.set_defaults(f=cmd_protect)

    c = s.add_parser("env-delete"); c.add_argument("app"); c.add_argument("key")
    c.add_argument("--confirmed", action="store_true"); c.set_defaults(f=cmd_env_delete)

    c = s.add_parser("deploy"); c.add_argument("app"); c.add_argument("--force", action="store_true")
    c.set_defaults(f=cmd_deploy)

    c = s.add_parser("wait", help="wait for a deployment to finish")
    c.add_argument("deployment"); c.add_argument("--timeout", type=int, default=900)
    c.add_argument("--lines", type=int, default=40); c.set_defaults(f=cmd_wait)

    c = s.add_parser("last-deployment"); c.add_argument("app"); c.set_defaults(f=cmd_last_deployment)

    c = s.add_parser("logs"); c.add_argument("app"); c.add_argument("--lines", type=int, default=100)
    c.set_defaults(f=cmd_logs)

    c = s.add_parser("rollback", help="list rollback images; with --image and --confirmed, roll back")
    c.add_argument("app"); c.add_argument("--image")
    c.add_argument("--confirmed", action="store_true"); c.set_defaults(f=cmd_rollback)

    c = s.add_parser("decommission", help="delete an app (optionally its database and project)")
    c.add_argument("app"); c.add_argument("--confirmed", action="store_true")
    c.add_argument("--with-db", dest="with_db", action="store_true")
    c.add_argument("--with-project", dest="with_project", action="store_true")
    c.set_defaults(f=cmd_decommission)

    def backup_parser(name, help_):
        c = s.add_parser(name, help=help_)
        c.add_argument("app", help="app name in apps.json or app uuid")
        c.add_argument("--db", help="database uuid (when the app's database is not in apps.json)")
        return c

    backup_parser("backup-status", "PostgreSQL backups: schedules and the latest backups (read-only)"
                  ).set_defaults(f=cmd_backup_status)
    c = backup_parser("backup-schedule", "create or change the scheduled backups (a --keep that deletes backups needs --confirmed)")
    c.add_argument("--frequency", help="hourly, daily, weekly, monthly, yearly or a 5-field cron (default daily)")
    c.add_argument("--keep", type=int, help=f"backups kept on the server (default {DEFAULT_KEEP}, minimum 1)")
    c.add_argument("--off", action="store_true", help="stop the scheduled backups (existing ones stay)")
    c.add_argument("--on", action="store_true",
                   help="start stopped scheduled backups again (--frequency or --keep alone leave them stopped)")
    c.add_argument("--backup", help="uuid of a backup configuration made in Coolify to change instead")
    c.add_argument("--confirmed", action="store_true"); c.set_defaults(f=cmd_backup_schedule)
    c = backup_parser("backup-now", f"take a backup now (kept apart from the scheduled ones, last {MANUAL_KEEP})")
    c.add_argument("--timeout", type=int, default=900); c.set_defaults(f=cmd_backup_now)
    c = backup_parser("backup-restore", "replace the database's data with a backup (needs --confirmed)")
    c.add_argument("--execution", required=True, help="backup uuid from backup-status")
    c.add_argument("--confirmed", action="store_true")
    c.add_argument("--timeout", type=int, default=1800, help="seconds to wait for the restore")
    c.add_argument("--backup-timeout", dest="backup_timeout", type=int, default=900,
                   help="seconds to wait for the safety backup")
    c.set_defaults(f=cmd_backup_restore)
    c = backup_parser("backup-restore-status", "state of a restore that was still running (read-only)")
    c.add_argument("import_id"); c.set_defaults(f=cmd_backup_restore_status)
    c = backup_parser("backup-download", "copy the database to this computer (pg_dump over ssh; never into a git repo)")
    c.add_argument("--out", help="folder (default ~/.config/coolify-ops/backups/<app>/)")
    c.add_argument("--timeout", type=int, default=1800); c.set_defaults(f=cmd_backup_download)
    return p


def main(argv=None) -> None:
    args = parser().parse_args(argv)
    try:
        result = args.f(args)
        emit(result, 0 if result.get("ok", True) else 1)
    except Error as e:
        emit({"ok": False, "error": str(e)}, 1)


if __name__ == "__main__":
    main()
