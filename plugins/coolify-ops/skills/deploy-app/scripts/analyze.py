#!/usr/bin/env python3
"""Analyze a local project and propose how to deploy it to Coolify. Read-only.

JSON output: stack, recommended template and its values, port, environment variables used by the code,
databases it seems to need, git (remote, branch, unpushed changes), committed secrets, signs of login and of
paid services, and «blockers» (reasons NOT to deploy automatically).

Usage:  analyze.py <path>             full analysis
        analyze.py <path> --secrets   only scan the files that would be pushed for secrets (run before a push)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".angular",
                ".nx", "vendor", ".cache", "coverage", ".turbo", ".pytest_cache", ".ruff_cache"}
MAX_FILE = 400_000  # bytes: larger files are not scanned

# Secret patterns (name → regex). Reported with file and line, never with the value.
SECRET_PATTERNS = {
    "private key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "OpenAI/Anthropic key": r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
    "Stripe live key": r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b",
    "URL with password": r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:[^\s@'\"]{6,}@(?!localhost|127\.0\.0\.1|example)",
}
SENSITIVE_FILES = re.compile(r"(^|/)(\.env(\.[\w-]+)?|.*\.pem|.*\.key|id_rsa|id_ed25519|credentials\.json|"
                             r"service-account.*\.json|wp-config\.php)$")
ENV_TEMPLATE_FILES = re.compile(r"\.env\.(example|sample|template|dist|demo)$")

LOGIN_LIBS = ["next-auth", "@auth/", "passport", "@supabase/auth", "@clerk/", "lucia", "better-auth", "firebase/auth",
              "jsonwebtoken", "@nestjs/jwt", "flask_login", "flask-login", "fastapi.security", "django.contrib.auth",
              "authlib", "python-jose", "pyjwt", "fastapi-users", "laravel/sanctum", "laravel/breeze"]
PAID_SERVICE_HINTS = ["stripe", "groq", "openai", "anthropic", "elevenlabs", "replicate", "twilio", "sendgrid",
                      "@google/genai", "google.generativeai", "mailgun", "resend"]

# Angular major version → Node version it builds with
NODE_FOR_ANGULAR = {12: "14", 13: "16", 14: "16", 15: "18", 16: "18", 17: "20", 18: "20", 19: "22", 20: "22"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".woff", ".woff2", ".ttf",
                   ".mp3", ".mp4", ".lock"}
LOCK_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}
MANIFESTS = ("package.json", "requirements.txt", "pyproject.toml", "composer.json")


# ---------------------------------------------------------------- helpers


def git(path: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_FILE:
            return ""
        return path.read_text(errors="ignore")
    except (OSError, UnicodeDecodeError):
        return ""


def project_files(root: Path) -> list[Path]:
    """Files that would be pushed: git-tracked plus untracked-not-ignored if it is a repo; otherwise a plain walk."""
    out = git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    if out:
        return [root / l for l in out.splitlines() if (root / l).is_file()]
    return [p for p in root.rglob("*")
            if p.is_file() and not any(part in IGNORED_DIRS for part in p.relative_to(root).parts)]


def major(version: str | None) -> int | None:
    m = re.search(r"(\d+)", version or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- analysis


def scan_secrets(root: Path, files: list[Path]) -> list[dict]:
    findings = []
    for f in files:
        rel = str(f.relative_to(root))
        if SENSITIVE_FILES.search(rel) and not ENV_TEMPLATE_FILES.search(rel):
            content = read(f)
            has_values = bool(re.search(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*\S+", content, re.M)) or "define(" in content
            findings.append({"file": rel, "type": "sensitive file", "has_values": has_values})
            continue
        if f.suffix.lower() in BINARY_SUFFIXES or f.name in LOCK_FILES:
            continue
        text = read(f)
        if not text:
            continue
        for name, pattern in SECRET_PATTERNS.items():
            m = re.search(pattern, text)
            if m:
                findings.append({"file": rel, "line": text.count("\n", 0, m.start()) + 1, "type": name})
    return findings


def env_vars_used(root: Path, files: list[Path]) -> dict:
    example = {}
    for name in (".env.example", ".env.sample", ".env.template", ".env.dist"):
        p = root / name
        if p.exists():
            for l in read(p).splitlines():
                m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)", l)
                if m:
                    example[m.group(1)] = bool(m.group(2).strip().strip("\"'"))
            break
    in_code = set()
    patterns = [r"os\.(?:environ\.get|getenv)\(\s*['\"]([A-Z_][A-Z0-9_]*)", r"os\.environ\[\s*['\"]([A-Z_][A-Z0-9_]*)",
                r"process\.env\.([A-Z_][A-Z0-9_]*)", r"process\.env\[\s*['\"]([A-Z_][A-Z0-9_]*)",
                r"import\.meta\.env\.([A-Z_][A-Z0-9_]*)", r"env\(\s*['\"]([A-Z_][A-Z0-9_]*)",
                r"getenv\(\s*['\"]([A-Z_][A-Z0-9_]*)"]
    for f in files:
        if f.suffix not in {".py", ".js", ".ts", ".mjs", ".cjs", ".tsx", ".jsx", ".php", ".vue", ".svelte"}:
            continue
        text = read(f)
        for p in patterns:
            in_code.update(re.findall(p, text))
    ignored = {"NODE_ENV", "PORT", "HOST", "PATH", "HOME", "PWD", "CI", "DEBUG", "TZ", "LANG"}
    return {"example": example, "in_code": sorted(in_code - ignored)}


def detect_monorepo(root: Path, files: list[Path]) -> list[str]:
    reasons = [m for m in ("nx.json", "turbo.json", "pnpm-workspace.yaml", "lerna.json", "rush.json")
               if (root / m).exists()]
    pkg = root / "package.json"
    if pkg.exists():
        try:
            if json.loads(read(pkg)).get("workspaces"):
                reasons.append("package.json with workspaces")
        except json.JSONDecodeError:
            pass
    packages = {f.parent for f in files if f.name in MANIFESTS and f.parent != root}
    root_has_manifest = any((root / n).exists() for n in MANIFESTS)
    if packages and (len(packages) > 1 or not root_has_manifest):
        names = sorted(str(p.relative_to(root)) for p in packages)[:5]
        reasons.append("several projects in subfolders: " + ", ".join(names))
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        dc = root / name
        if dc.exists():
            services = re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", read(dc), re.M)
            if len(services) > 1:
                reasons.append(f"{name} with {len(services)} services ({', '.join(services[:5])})")
    return reasons


def analyze_node(root: Path) -> dict:
    pkg = json.loads(read(root / "package.json") or "{}")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    scripts = pkg.get("scripts", {})
    engines_node = (pkg.get("engines") or {}).get("node")
    nvmrc = read(root / ".nvmrc").strip() or read(root / ".node-version").strip()
    r: dict = {"language": "node", "key_dependencies": {k: deps[k] for k in deps if k in {
        "next", "react", "vue", "svelte", "@angular/core", "vite", "express", "hono", "fastify", "@nestjs/core",
        "nuxt", "astro", "@sveltejs/kit", "typescript", "prisma", "@prisma/client", "drizzle-orm", "pg", "mysql2",
        "mongoose", "redis", "ioredis"}}}
    node = major(nvmrc) or major(engines_node)
    if "@angular/core" in deps and not node:
        node = int(NODE_FOR_ANGULAR.get(major(deps["@angular/core"]) or 0, "22"))
    r["node_version"] = str(node or 22)
    pm = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm"
    r["package_manager"] = pm
    if pm == "npm" and not (root / "package-lock.json").exists():
        r["warning_lock"] = "no package-lock.json: the build will use npm install (less reproducible)"

    if "next" in deps:
        r.update(framework="nextjs", template="nextjs", port=3000)
    elif "@angular/core" in deps:
        out_dir, ssr = None, False
        try:
            ang = json.loads(read(root / "angular.json"))
            project = ang.get("defaultProject") or next(iter(ang["projects"]))
            build = ang["projects"][project]["architect"]["build"]
            opts = build["options"]
            out_dir = opts.get("outputPath")
            if isinstance(out_dir, dict):
                out_dir = out_dir.get("base")
            if build["builder"].endswith(":application") or (major(deps["@angular/core"]) or 0) >= 17:
                out_dir = f"{out_dir}/browser"  # the modern builder adds /browser
            ssr = "server" in opts or "ssr" in opts
        except (json.JSONDecodeError, KeyError, StopIteration):
            pass
        r.update(framework="angular", template="spa-nginx", port=80, spa=True,
                 build_cmd="npx ng build --configuration production", build_dir=out_dir or "dist")
        if ssr:
            r["warning_ssr"] = "Angular with SSR: the static template does not fit; review manually"
    elif any(k in deps for k in ("nuxt", "astro", "@sveltejs/kit")):
        r.update(framework=next(k for k in ("nuxt", "astro", "@sveltejs/kit") if k in deps), template=None,
                 warning_framework="framework with its own SSR server: no template yet")
    elif "vite" in deps and not any(k in deps for k in ("express", "hono", "fastify", "@nestjs/core")):
        r.update(framework="vite", template="spa-nginx", port=80, spa=True,
                 build_cmd=f"{pm} run build", build_dir="dist")
    elif "react-scripts" in deps:
        r.update(framework="create-react-app", template="spa-nginx", port=80, spa=True,
                 build_cmd=f"{pm} run build", build_dir="build")
    else:
        fw = next((k for k in ("@nestjs/core", "hono", "fastify", "express") if k in deps), "node")
        port = 3000
        for f in list(root.glob("src/**/*.[tj]s"))[:200] + list(root.glob("*.[tj]s")):
            m = re.search(r"(?:listen|port)\D{0,40}?(\d{4,5})", read(f))
            if m:
                port = int(m.group(1))
                break
        r.update(framework=fw, template="node-server", port=port, has_build="build" in scripts,
                 has_start="start" in scripts)
        if "start" not in scripts:
            r["warning_start"] = "package.json has no «start» script: the start command must be specified"
    return r


def analyze_python(root: Path, files: list[Path]) -> dict:
    reqs = (read(root / "requirements.txt") + read(root / "pyproject.toml")).lower()
    r: dict = {"language": "python"}
    version = re.search(r"python_requires\s*=\s*['\"][^0-9]*(3\.\d+)|requires-python\s*=\s*['\"][^0-9]*(3\.\d+)",
                        read(root / "pyproject.toml") + read(root / "setup.py"))
    r["python_version"] = next((g for g in (version.groups() if version else ()) if g), "3.12")
    if not (root / "requirements.txt").exists():
        r["warning_requirements"] = "no requirements.txt (the template needs it; adapt it for pyproject-only projects)"
    module = None
    for f in files:
        if f.suffix == ".py" and (f.parent == root or f.parent.name in {"app", "src"}):
            m = re.search(r"^(\w+)\s*=\s*(FastAPI|Flask)\(", read(f), re.M)
            if m:
                module = ".".join(f.relative_to(root).with_suffix("").parts) + ":" + m.group(1)
                break
    if "fastapi" in reqs:
        r.update(framework="fastapi", template="python-fastapi", port=8000, module=module or "main:app")
    elif "flask" in reqs:
        r.update(framework="flask", template="python-flask", port=8000, module=module or "app:app")
    elif "django" in reqs:
        r.update(framework="django", template=None, warning_framework="Django: no template yet")
    else:
        r.update(framework="python", template=None, warning_framework="unrecognized web framework")
    return r


def analyze(root: Path) -> dict:
    root = root.resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"Folder {root} does not exist"}
    files = project_files(root)
    res: dict = {"ok": True, "path": str(root),
                 "suggested_name": re.sub(r"[^a-z0-9-]", "-", root.name.lower()).strip("-")}
    blockers: list[str] = []
    warnings: list[str] = []

    # --- git
    if (root / ".git").exists():
        remote = git(root, "remote", "get-url", "origin")
        m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", remote)
        status = git(root, "status", "--porcelain")
        ahead = git(root, "rev-list", "--count", "@{u}..HEAD") if remote else ""
        res["git"] = {"remote": m.group(1) if m else (remote or None), "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
                      "uncommitted_changes": len(status.splitlines()) if status else 0,
                      "unpushed_commits": int(ahead) if ahead.isdigit() else None,
                      "has_upstream": bool(ahead)}
        if remote and not m:
            blockers.append("the remote is not on GitHub (only GitHub repositories are supported)")
    else:
        res["git"] = None

    # --- stack
    monorepo = detect_monorepo(root, files)
    if monorepo:
        res["monorepo"] = monorepo
        blockers.append("monorepo or several services (" + "; ".join(monorepo) + "): not supported yet")
    if (root / "package.json").exists():
        res["stack"] = analyze_node(root)
    elif (root / "requirements.txt").exists() or (root / "pyproject.toml").exists():
        res["stack"] = analyze_python(root, files)
    elif (root / "composer.json").exists() or any(f.suffix == ".php" for f in files):
        composer = read(root / "composer.json")
        if "laravel/framework" in composer or "symfony/" in composer:
            res["stack"] = {"language": "php", "framework": "laravel/symfony", "template": None,
                            "warning_framework": "full PHP framework: no template yet"}
        else:
            res["stack"] = {"language": "php", "framework": "php", "template": "php-apache", "port": 80}
    elif (root / "index.html").exists():
        res["stack"] = {"language": "html", "framework": "static", "template": "static-nginx", "port": 80}
    else:
        res["stack"] = {"language": None, "template": None}
    stack = res["stack"]
    dockerfile = root / "Dockerfile"
    if dockerfile.exists():
        expose = re.findall(r"^\s*EXPOSE\s+(\d+)", read(dockerfile), re.M | re.I)
        stack["existing_dockerfile"] = True
        stack["template"] = None
        if expose:
            stack["port"] = int(expose[-1])
        else:
            warnings.append("the Dockerfile has no EXPOSE: the port must be confirmed")
    elif not stack.get("template") and not monorepo:
        blockers.append(stack.get("warning_framework") or "unknown project type")
    warnings += [stack[k] for k in stack if k.startswith("warning_")]

    # --- variables, databases, login, paid services
    res["env_vars"] = env_vars_used(root, files)
    manifests = " ".join(read(f).lower() for f in files if f.name in {*MANIFESTS, "schema.prisma", "drizzle.config.ts"})
    names = set(res["env_vars"]["in_code"]) | set(res["env_vars"]["example"])
    dbs = []
    if "DATABASE_URL" in names or any(x in manifests for x in ("psycopg", "asyncpg", '"pg"', "postgres",
                                                                "sqlalchemy", "prisma")):
        dbs.append("postgresql")
    if any(x in manifests for x in ("mysql", "mariadb")):
        dbs.append("mysql")
    if any(x in manifests for x in ("mongoose", "mongodb", "pymongo")):
        dbs.append("mongodb")
    if "REDIS_URL" in names or any(x in manifests for x in ('"redis"', "ioredis", "redis==", "redis>")):
        dbs.append("redis")
    if "supabase" in manifests:
        res["external_services"] = ["supabase (hosted: only its variables are needed)"]
        if "DATABASE_URL" not in names:  # with Supabase the database is hosted, unless it uses its own URL
            dbs = [d for d in dbs if d != "postgresql"]
    res["databases"] = dbs
    res["has_login_estimate"] = any(lib in manifests for lib in LOGIN_LIBS)
    paid = sorted({p for p in PAID_SERVICE_HINTS if p in manifests})
    res["paid_services_estimate"] = paid
    if paid and not res["has_login_estimate"]:
        warnings.append(f"uses paid services ({', '.join(paid)}) and seems to have no login: propose protected access")

    # --- secrets
    secrets = scan_secrets(root, files)
    res["secrets"] = secrets
    if secrets:
        blockers.append(f"{len(secrets)} possible secret(s) in files that would be pushed (review before publishing)")

    res["warnings"] = warnings
    res["blockers"] = blockers
    res["deployable"] = not blockers
    return res


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(__doc__)
        sys.exit(0)
    root = Path(sys.argv[1]).expanduser()
    if "--secrets" in sys.argv:
        findings = scan_secrets(root.resolve(), project_files(root.resolve()))
        print(json.dumps({"ok": not findings, "secrets": findings}, ensure_ascii=False))
        sys.exit(0 if not findings else 1)
    print(json.dumps(analyze(root), ensure_ascii=False))


if __name__ == "__main__":
    main()
