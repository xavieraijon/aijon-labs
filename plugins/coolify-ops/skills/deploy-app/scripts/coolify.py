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
LEGACY_REGISTRY_KEYS = {"proyecto_uuid": "project_uuid", "dominio": "domain", "rama": "branch",
                        "actualizado": "updated"}


# ---------------------------------------------------------------- helpers


class Error(Exception):
    """Expected error: printed as JSON with ok=false."""


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
            text = r.read().decode() or "{}"
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:800]
        hints = {401: "invalid or expired token", 403: "token lacks a permission or your IP is not in «Allowed IPs»",
                 404: "not found (uuid or path)", 422: "Coolify rejected the data"}
        raise Error(f"HTTP {e.code} on {method} {path} ({hints.get(e.code, 'error')}): {mask(detail)}") from None
    except urllib.error.URLError as e:
        raise Error(f"Cannot reach Coolify at {cfg['url']}: {e.reason}. "
                    "Are you on the right network/VPN? Is API access enabled?") from None


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
    version = api("GET", "/version")
    projects = api("GET", "/projects")
    cfg = config()
    return {"ok": True, "coolify": version.get("text", version), "url": cfg["url"],
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
    server = next((s for s in servers if s.get("name") == (a.server or "localhost")), servers[0])
    gh_apps = api("GET", "/github-apps")
    private = [g for g in gh_apps if not g.get("is_public")] if isinstance(gh_apps, list) else []
    if not private:
        raise Error("No private GitHub App is connected in Coolify (Sources).")
    gh = next((g for g in private if g.get("name") == a.github_app), private[0])
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
             "autodeploy": _autodeploy(ap)} for ap in _apps()]
    dbs = [{"name": d.get("name"), "uuid": d.get("uuid"), "type": d.get("database_type"), "status": d.get("status"),
            "public": d.get("is_public")} for d in (api("GET", "/databases") or [])]
    return {"ok": True, "apps": apps, "databases": dbs, "local_registry": sorted(registry())}


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
    if a.app_uuid:  # connect it to the app as DATABASE_URL (secret; build time too only if the build inlines it)
        _set_env(a.app_uuid, "DATABASE_URL", internal_url, secret=True, buildtime=getattr(a, "buildtime", False))
    return {"ok": True, "db_uuid": uuid, "internal_host": uuid, "user": user,
            "database_url": mask(internal_url), "linked_to_app": bool(a.app_uuid)}


def cmd_create_app(a):
    cfg = config()
    bad = [k for k in (getattr(a, "env_domain", None) or []) + (getattr(a, "env_generate", None) or [])
           if not ENV_KEY.fullmatch(k)]
    if bad:
        raise Error(f"Invalid variable names: {', '.join(bad)}")
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
    r = api("POST", "/applications/private-github-app", body)
    uuid = r["uuid"]
    save_to_registry(a.name, {"app_uuid": uuid, "project_uuid": a.project, "domain": check["host"],
                              "repo": a.repo, "branch": a.branch})
    res = {"ok": True, "app_uuid": uuid, "url": f"https://{check['host']}"}
    if getattr(a, "env_domain", None):  # the app exists now: report env failures instead of raising, so the uuid is never lost
        res["env_domain"], res["env_errors"] = _set_domain_envs(uuid, check["host"], a.env_domain)
    if getattr(a, "env_generate", None):
        res["env_generated"], errors = _generate_envs(uuid, a.env_generate)
        res["env_errors"] = res.get("env_errors", []) + errors
    return res


def _generate_envs(app_uuid: str, keys: list[str]) -> tuple[dict, list[dict]]:
    """Set each KEY to a random secret (e.g. DJANGO_SECRET_KEY) unless it already exists: re-running never
    rotates it. The value goes straight to the API and is never printed or stored locally."""
    existing = {e.get("key") for e in api("GET", f"/applications/{app_uuid}/envs") or [] if not e.get("is_preview")}
    done, errors = {}, []
    for key in dict.fromkeys(keys):
        if key in existing:
            done[key] = "kept"
            continue
        try:
            _set_env(app_uuid, key, secrets.token_urlsafe(50), secret=True, buildtime=False)
            done[key] = "created"
        except Error as e:
            errors.append({"key": key, "error": str(e)})
    return done, errors


def cmd_env_generate(a):
    """Random secret values for KEY… (only for keys the app does not have yet)."""
    bad = [k for k in a.keys if not ENV_KEY.fullmatch(k)]
    if bad:
        raise Error(f"Invalid variable names: {', '.join(bad)}")
    done, errors = _generate_envs(resolve_app(a.app), a.keys)
    return {"ok": not errors, "env_generated": done, "env_errors": errors}


def _set_domain_envs(app_uuid: str, host: str, keys: list[str]) -> tuple[list[str], list[dict]]:
    """Set each KEY=<host> as a runtime variable (public value: the app's own domain)."""
    done, errors = [], []
    for key in dict.fromkeys(keys):
        try:
            _set_env(app_uuid, key, host, secret=False, buildtime=False)
            done.append(key)
        except Error as e:
            errors.append({"key": key, "error": str(e)})
    return done, errors


def cmd_env_domain(a):
    """Set KEY=<the app's domain host> (e.g. NG_ALLOWED_HOSTS) without the value going through the command line."""
    bad = [k for k in a.keys if not ENV_KEY.fullmatch(k)]
    if bad:
        raise Error(f"Invalid variable names: {', '.join(bad)}")
    app = resolve_app(a.app)
    fqdn = (api("GET", f"/applications/{app}") or {}).get("fqdn") or ""
    host = host_of(fqdn.split(",")[0]) if fqdn else ""
    if not host:
        raise Error("The app has no domain")
    done, errors = _set_domain_envs(app, host, a.keys)
    return {"ok": not errors, "host": host, "env_domain": done, "env_errors": errors}


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
            if "HTTP 404" in str(e):
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
    api("DELETE", f"/applications/{app}", query={"delete_configurations": "true", "delete_volumes": "true",
                                                   "docker_cleanup": "true", "delete_connected_networks": "true"})
    deleted = {"app": app}
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
    if not deleted.get("warning") and a.with_project:
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


# ---------------------------------------------------------------- CLI


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coolify.py", description="Coolify API client for the coolify-ops skills")
    s = p.add_subparsers(dest="command", required=True)

    s.add_parser("check", help="Coolify version and token validity").set_defaults(f=cmd_check)

    c = s.add_parser("init", help="create/update the configuration (discovers server and GitHub App)")
    c.add_argument("--url"); c.add_argument("--domain", help="base domain, e.g. example.org")
    c.add_argument("--ssh", help="user@host of the Coolify server (optional, for health checks)")
    c.add_argument("--server", help="Coolify server name (default: localhost)")
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
    c.add_argument("--no-autodeploy", dest="no_autodeploy", action="store_true")
    c.add_argument("--env-domain", dest="env_domain", action="append", metavar="KEY",
                   help="set KEY=<the app's domain> as a runtime variable (repeatable), e.g. NG_ALLOWED_HOSTS")
    c.add_argument("--env-generate", dest="env_generate", action="append", metavar="KEY",
                   help="set KEY to a random secret unless it exists (repeatable), e.g. DJANGO_SECRET_KEY")
    c.set_defaults(f=cmd_create_app)

    c = s.add_parser("env-generate", help="set KEY… to random secrets, only if missing (values are never printed)")
    c.add_argument("app"); c.add_argument("keys", nargs="+", metavar="KEY"); c.set_defaults(f=cmd_env_generate)

    c = s.add_parser("env-domain", help="set KEY=<the app's domain> as a runtime variable (e.g. NG_ALLOWED_HOSTS)")
    c.add_argument("app"); c.add_argument("keys", nargs="+", metavar="KEY"); c.set_defaults(f=cmd_env_domain)

    c = s.add_parser("create-postgres")
    c.add_argument("--project", required=True); c.add_argument("--name", required=True)
    c.add_argument("--app", help="app name in the local registry"); c.add_argument("--app-uuid", dest="app_uuid")
    c.add_argument("--environment", default="production"); c.add_argument("--image", default="postgres:17-alpine")
    c.add_argument("--memory", default="512m")
    c.add_argument("--buildtime", action="store_true",
                   help="DATABASE_URL also at build time (when the build inlines it, e.g. SvelteKit $env/static/private)")
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
    return p


def main(argv=None) -> None:
    args = parser().parse_args(argv)
    try:
        emit(args.f(args))
    except Error as e:
        emit({"ok": False, "error": str(e)}, 1)


if __name__ == "__main__":
    main()
