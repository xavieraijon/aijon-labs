#!/usr/bin/env python3
"""Generate the deployment files (Dockerfile, .dockerignore, nginx.conf) from the templates.

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
from analyze import analyze  # noqa: E402

NGINX = {"spa-nginx": "nginx-spa.conf", "static-nginx": "nginx-static.conf"}


def values(analysis: dict, extra: dict) -> dict:
    s = analysis.get("stack", {})
    v = {"PORT": str(s.get("port", "")), "NODE_VERSION": s.get("node_version", "22"),
         "PYTHON_VERSION": s.get("python_version", "3.12"), "MODULE": s.get("module", "main:app"),
         "BUILD_CMD": s.get("build_cmd", "npm run build"), "BUILD_DIR": s.get("build_dir", "dist"),
         "PHP_VERSION": "8.3"}
    v.update(extra)
    return v


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
    template = a.template or stack.get("template")
    if not template:
        reason = "it already has a Dockerfile" if stack.get("existing_dockerfile") else "no template for this project"
        print(json.dumps({"ok": True, "created": [], "skipped": [], "reason": reason}, ensure_ascii=False))
        return
    v = values(analysis, dict(x.split("=", 1) for x in a.var))

    plan = [("Dockerfile", TEMPLATES / f"{template}.Dockerfile"), (".dockerignore", TEMPLATES / "dockerignore")]
    if template in NGINX:
        plan.append(("nginx.conf", TEMPLATES / NGINX[template]))

    created, skipped = [], []
    try:
        for target, source in plan:
            path = root / target
            if path.exists() and not a.overwrite:
                skipped.append(target)
                continue
            content = render(source.read_text(), v)
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
