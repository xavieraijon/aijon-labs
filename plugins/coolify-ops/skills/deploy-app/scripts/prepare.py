#!/usr/bin/env python3
"""Generate the deployment files (Dockerfile, .dockerignore, nginx.conf, coolify_settings.py,
config/trustedproxy.php) from the templates.

Never overwrites an existing file unless --overwrite is passed. Never touches the application code.

Usage:  prepare.py <path> [--var KEY=value ...] [--template NAME] [--overwrite] [--dry-run]
        Values come from the analysis (analyze.py); --var corrects them (e.g. --var PORT=8080).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"
sys.path.insert(0, str(HERE))
from analyze import analyze, with_build_args  # noqa: E402
from phpstack import COMPOSER_COPY, COMPOSER_VERSION, EXT_INSTALLER, EXTENSION  # noqa: E402
from pystack import (  # noqa: E402
    COLLECTSTATIC,
    DEPS_FILES,
    INSTALLS,
    MODULE_PATH,
    PACKAGE,
    POETRY_SETUP,
    UV_IMAGE,
    WSGI_MODULE,
)

# Values read from the user's config files end up in a Dockerfile or nginx.conf: only plain paths and names pass.
SAFE_PATH = re.compile(r"(?!.*\.\.)[A-Za-z0-9._@/-]+")
ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ENV_VALUE = re.compile(r"[A-Za-z0-9._,:/-]*")


def nginx_conf(template: str, stack: dict) -> str | None:
    if template == "static-nginx":
        return "nginx-static.conf"
    if template == "spa-nginx":
        return "nginx-spa.conf" if stack.get("spa", True) else "nginx-static.conf"
    return None


def extra_env(env: dict) -> str:
    for k, val in env.items():
        if not ENV_KEY.fullmatch(k) or not ENV_VALUE.fullmatch(str(val)):
            raise ValueError(f"unsafe environment variable for the Dockerfile: {k}")
    return "".join(f" {k}={val}" for k, val in env.items())


def values(analysis: dict, extra: dict) -> dict:
    s = analysis.get("stack", {})
    v = {"PORT": str(s.get("port", "")), "NODE_VERSION": s.get("node_version", "22"),
         "PYTHON_VERSION": s.get("python_version", "3.12"), "MODULE": s.get("module", "main:app"),
         "BUILD_CMD": s.get("build_cmd", "npm run build"), "BUILD_DIR": s.get("build_dir", "dist"),
         "PHP_VERSION": s.get("php_version", "8.3"), "SPA_FALLBACK": s.get("spa_fallback", "index.html"),
         "START_CMD": json.dumps(s.get("start_cmd") or ["npm", "start"]),
         "EXTRA_ENV": extra_env(s.get("extra_env") or {})}
    django = s.get("framework") == "django"
    v.update({"DEPS_FILES": s.get("deps_files", DEPS_FILES["pip"]), "INSTALL": s.get("install", INSTALLS["pip"]),
              "POETRY_SETUP": s.get("poetry_setup", ""), "UV_IMAGE": UV_IMAGE,
              "EXTRA_PACKAGES": " ".join(f'"{x}"' for x in s.get("extra_packages") or ["gunicorn"]),
              "COLLECTSTATIC": COLLECTSTATIC if s.get("collectstatic", django) else "",
              "SETTINGS_MODULE": s.get("settings_module", "app.settings")})
    if django:
        v["MODULE"] = s.get("module", "app.wsgi:application")
    v.update({"EXT_INSTALLER": EXT_INSTALLER, "COMPOSER_VERSION": COMPOSER_VERSION,
              "PHP_EXTENSIONS": s.get("php_extensions", "pdo_pgsql opcache"),
              "COMPOSER_COPY": COMPOSER_COPY[s.get("composer_copy", "manifests")]})
    v.update(extra)
    python_checks(v)
    php_checks(v)
    for key in ("BUILD_DIR", "SPA_FALLBACK"):
        if not SAFE_PATH.fullmatch(v[key]):
            raise ValueError(f"{key} is not a plain relative path: {v[key]!r}")
    if not isinstance(json.loads(v["START_CMD"]), list):
        raise ValueError("START_CMD must be a JSON list")
    pairs = v["EXTRA_ENV"].split(" ")[1:] if v["EXTRA_ENV"] else []
    if v["EXTRA_ENV"] and (not v["EXTRA_ENV"].startswith(" ") or not all("=" in x for x in pairs)):
        raise ValueError("EXTRA_ENV must be « KEY=value KEY=value…» (with a leading space)")
    extra_env(dict(x.split("=", 1) for x in pairs))  # same checks as values from the analysis
    return v


def python_checks(v: dict) -> None:
    """Values that reach a Dockerfile RUN/CMD line: only fixed commands, plain file names and Python identifiers."""
    if not re.fullmatch(r"\d{0,5}", v["PORT"]):
        raise ValueError(f"PORT must be a number: {v['PORT']!r}")
    if not re.fullmatch(r"3\.\d+", v["PYTHON_VERSION"]):
        raise ValueError(f"PYTHON_VERSION must look like 3.12: {v['PYTHON_VERSION']!r}")
    if v["INSTALL"] not in INSTALLS.values():
        raise ValueError("INSTALL must be one of the fixed install commands")
    if v["DEPS_FILES"] != "." and v["DEPS_FILES"] not in DEPS_FILES.values():
        raise ValueError("DEPS_FILES must be one of the fixed dependency files or «.»")
    if v["POETRY_SETUP"] not in ("", POETRY_SETUP) or v["COLLECTSTATIC"] not in ("", COLLECTSTATIC):
        raise ValueError("POETRY_SETUP and COLLECTSTATIC cannot be overridden")
    packages = re.findall(r'"([^"]*)"', v["EXTRA_PACKAGES"])
    if not packages or not all(PACKAGE.fullmatch(x) for x in packages) or v["EXTRA_PACKAGES"] != " ".join(f'"{x}"' for x in packages):
        raise ValueError("EXTRA_PACKAGES must be quoted package names, e.g. \"gunicorn\" \"psycopg[binary]\"")
    if not (WSGI_MODULE.fullmatch(v["MODULE"]) or MODULE_PATH.fullmatch(v["MODULE"])):
        raise ValueError(f"MODULE is not a Python module path: {v['MODULE']!r}")
    if not MODULE_PATH.fullmatch(v["SETTINGS_MODULE"]):
        raise ValueError(f"SETTINGS_MODULE is not a Python module path: {v['SETTINGS_MODULE']!r}")


def php_checks(v: dict) -> None:
    """PHP/Laravel values that reach a Dockerfile: version and extension names by pattern, the rest fixed."""
    if not re.fullmatch(r"8\.\d+", v["PHP_VERSION"]):
        raise ValueError(f"PHP_VERSION must look like 8.4: {v['PHP_VERSION']!r}")
    if not re.fullmatch(r"\d{1,3}", v["NODE_VERSION"]):
        raise ValueError(f"NODE_VERSION must be a major version number: {v['NODE_VERSION']!r}")
    exts = v["PHP_EXTENSIONS"].split(" ")
    if not all(EXTENSION.fullmatch(x) for x in exts):
        raise ValueError(f"PHP_EXTENSIONS must be extension names separated by spaces: {v['PHP_EXTENSIONS']!r}")
    if v["COMPOSER_COPY"] not in COMPOSER_COPY.values():
        raise ValueError("COMPOSER_COPY must be one of the fixed values")
    if v["EXT_INSTALLER"] != EXT_INSTALLER or v["COMPOSER_VERSION"] != COMPOSER_VERSION:
        raise ValueError("EXT_INSTALLER and COMPOSER_VERSION cannot be overridden")


def render(text: str, v: dict) -> str:
    result = re.sub(r"\{\{(\w+)\}\}", lambda m: str(v.get(m.group(1), m.group(0))), text)
    missing = re.findall(r"\{\{(\w+)\}\}", result)
    if missing:
        raise ValueError(f"missing values for: {', '.join(sorted(set(missing)))}")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--var", action="append", default=[], help="KEY=value")
    p.add_argument("--template", help="force a specific template")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="write nothing, show what would be done")
    a = p.parse_args()

    root = Path(a.path).expanduser().resolve()
    analysis = analyze(root)
    if not analysis.get("ok"):
        print(json.dumps(analysis, ensure_ascii=False))
        sys.exit(1)
    stack = analysis.get("stack", {})
    template = a.template or stack.get("template") or (stack.get("suggested_template") if a.overwrite else None)
    if not template:
        reason = "it already has a Dockerfile" if stack.get("existing_dockerfile") else "no template for this project"
        print(json.dumps({"ok": True, "created": [], "skipped": [], "reason": reason}, ensure_ascii=False))
        return
    try:
        v = values(analysis, dict(x.split("=", 1) for x in a.var))
    except (ValueError, json.JSONDecodeError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    laravel = template.startswith("php-laravel")
    plan = [("Dockerfile", TEMPLATES / f"{template}.Dockerfile"),
            (".dockerignore", TEMPLATES / ("dockerignore-laravel" if laravel else "dockerignore"))]
    conf = nginx_conf(template, stack)
    if conf:
        plan.append(("nginx.conf", TEMPLATES / conf))
    if template == "python-django":
        plan.append(("coolify_settings.py", TEMPLATES / "django-settings.py.tmpl"))
    if laravel and stack.get("trust_proxies", "generated") == "generated":
        plan.append(("config/trustedproxy.php", TEMPLATES / "laravel-trustedproxy.php.tmpl"))

    build_time = analysis.get("build_time_candidates") or []
    created, skipped = [], []
    try:
        for target, source in plan:
            path = root / target
            if path.exists() and not a.overwrite:
                skipped.append(target)
                continue
            content = render(source.read_text(), v)
            if target == "Dockerfile":
                content = with_build_args(content, build_time)
            if not a.dry_run:
                path.write_text(content)
            created.append(target)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"ok": True, "template": template, "values": v, "created": created, "skipped": skipped,
                      "dry_run": a.dry_run}, ensure_ascii=False))


if __name__ == "__main__":
    main()
