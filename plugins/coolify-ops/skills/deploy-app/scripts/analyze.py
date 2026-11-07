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

IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".angular", ".output",
                ".nuxt", ".svelte-kit", ".astro", ".react-router",
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
NODE_FOR_ANGULAR = {12: "14", 13: "16", 14: "16", 15: "18", 16: "18", 17: "20", 18: "20", 19: "22", 20: "22", 21: "22", 22: "24"}
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
    in_code, build_time = set(), set()
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
        # SvelteKit: names imported from $env/static/* are inlined at build time
        for names in re.findall(r"import\s*\{([^}]*)\}\s*from\s*['\"]\$env/static/(?:private|public)['\"]", text):
            build_time.update(m.group(1) for part in names.split(",")
                              if (m := re.match(r"\s*([A-Z_][A-Z0-9_]*)\b", part)))
    ignored = {"NODE_ENV", "PORT", "HOST", "PATH", "HOME", "PWD", "CI", "DEBUG", "TZ", "LANG"}
    return {"example": example, "in_code": sorted((in_code | build_time) - ignored), "build_time": sorted(build_time)}


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


def strip_comments(text: str) -> str:
    """Remove // and /* */ comments from JS/TS source, leaving string literals intact."""
    out, i, n, quote = [], 0, len(text), None
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
            out.append(c)
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def top_level(text: str, start: int) -> str:
    """Text of the object literal opening at text[start] == '{', with every nested {…}/[…]/(…) removed."""
    out, depth, i, quote = [], 0, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if depth == 1:
                out.append(c)
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
            if depth == 1:
                out.append(c)
        elif c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1:
            out.append(c)
        i += 1
    return "".join(out)


def config_text(root: Path, base: str) -> str | None:
    """Comment-free text of <base>.{ts,js,mjs,mts,cjs,cts}, or None if there is no such file."""
    for ext in ("ts", "js", "mjs", "mts", "cjs", "cts"):
        p = root / f"{base}.{ext}"
        if p.exists():
            return strip_comments(read(p))
    return None


def literal(text: str, key: str) -> tuple[bool, str | None]:
    """(key present, its value if it is a plain string literal)."""
    m = re.search(rf"\b{key}\s*:\s*(\S)", text)
    if not m:
        return False, None
    v = re.match(r"""(['"`])([^'"`$\\]*)\1""", text[m.start(1):])
    return True, v.group(2) if v else None


def blocked(r: dict, framework: str, reason: str) -> dict:
    r.update(framework=framework, template=None, warning_framework=reason)
    return r


def static_site(r: dict, framework: str, build_cmd: str, build_dir: str, spa: bool, fallback: str = "index.html") -> dict:
    r.update(framework=framework, template="spa-nginx", port=80, render="static", build_cmd=build_cmd,
             build_dir=build_dir.strip("/") or ".", spa=spa)
    if spa:
        r["spa_fallback"] = fallback
    return r


def ssr_server(r: dict, framework: str, build_cmd: str, build_dir: str, start: list[str], port: int,
               extra_env: dict | None = None) -> dict:
    r.update(framework=framework, template="node-ssr", port=port, render="server", build_cmd=build_cmd,
             build_dir=build_dir.strip("/"), start_cmd=start, extra_env=extra_env or {}, runtime_env={})
    return r


# Vite/Angular-based meta-frameworks without a template: always blocked, never treated as a plain SPA.
META_BLOCKED = {"@analogjs/platform": "Analog", "@solidjs/start": "SolidStart", "@builder.io/qwik-city": "Qwik City",
                "vike": "Vike", "@tanstack/react-start": "TanStack Start", "@tanstack/solid-start": "TanStack Start",
                "@tanstack/start": "TanStack Start"}
ASTRO_PLATFORM_ADAPTERS = ("@astrojs/vercel", "@astrojs/netlify", "@astrojs/cloudflare", "@astrojs/deno")


def analyze_nuxt(root: Path, r: dict, deps: dict, scripts: dict) -> dict:
    if (major(deps["nuxt"]) or 99) < 3:
        return blocked(r, "nuxt", "Nuxt 2 is not supported (end of life): upgrade to Nuxt 3+ or add your own Dockerfile")
    text = config_text(root, "nuxt.config") or ""
    build = scripts.get("build", "")
    m = re.search(r"\bdefineNuxtConfig\s*\(\s*\{", text) or re.search(r"export\s+default\s*\{", text)
    top = top_level(text, m.end() - 1) if m else ""
    spa = bool(re.search(r"\bssr\s*:\s*false\b", top))
    nested_ssr = len(re.findall(r"\bssr\s*:", text)) > len(re.findall(r"\bssr\s*:", top))
    if "routeRules" in text and nested_ssr:
        r["warning_route_rules"] = "Nuxt routeRules set per-route rendering: deployed as a Node server"
    env_preset = re.search(r"\bNITRO_PRESET=([\w-]+)", build)
    _, cfg_preset = literal(text, "preset")
    preset = env_preset.group(1) if env_preset else cfg_preset
    if preset and preset not in {"node", "node-server", "static"}:
        return blocked(r, "nuxt", f"Nuxt is built with the Nitro preset «{preset}», which does not run on a plain "
                                  "server: remove it (default node-server) or use 'static', or add your own Dockerfile")
    if spa or preset == "static" or "nuxt generate" in build:
        cmd = "npm run build" if "generate" in build or preset == "static" else "npx nuxt generate"
        if (root / "server").is_dir():
            r["warning_server_dir"] = "Nuxt is deployed as a static site: the routes in server/ will not work"
        return static_site(r, "nuxt", cmd, ".output/public", spa=spa, fallback="200.html")
    return ssr_server(r, "nuxt", "npm run build", ".output", ["node", ".output/server/index.mjs"], 3000)


def analyze_astro(root: Path, r: dict, deps: dict) -> dict:
    text = config_text(root, "astro.config") or ""
    other = next((a for a in ASTRO_PLATFORM_ADAPTERS if a in deps), None)
    if other:
        return blocked(r, "astro", f"Astro uses the {other} adapter, made for another platform: replace it with "
                                   "@astrojs/node (mode: 'standalone') or remove it for a static site")
    if "@astrojs/node" in deps:
        _, mode = literal(text, "mode")
        if mode == "standalone":
            return ssr_server(r, "astro", "npm run build", "dist", ["node", "dist/server/entry.mjs"], 4321)
        return blocked(r, "astro", "Astro's @astrojs/node adapter must use mode: 'standalone' to run on its own "
                                   f"(found: {mode or 'not set'}), or add your own Dockerfile")
    if literal(text, "output")[1] == "server":
        return blocked(r, "astro", "Astro has output: 'server' but no adapter: install @astrojs/node "
                                   "(mode: 'standalone'), or remove output: 'server' for a static site")
    return static_site(r, "astro", "npm run build", "dist", spa=False)


def analyze_sveltekit(root: Path, r: dict) -> dict:
    text = config_text(root, "svelte.config") or ""
    m = re.search(r"""from\s+['"]@sveltejs/adapter-([\w-]+)['"]""", text)
    adapter = m.group(1) if m else "auto"
    hint = ("install @sveltejs/adapter-node (server) or @sveltejs/adapter-static (static site) and use it in "
            "svelte.config.js")
    if adapter == "node":
        has_out, out = literal(text, "out")
        has_prefix, prefix = literal(text, "envPrefix")
        if has_out and out is None:
            r["warning_config"] = "adapter-node «out» is not a plain string: using the default «build»"
        env = {"PROTOCOL_HEADER": "x-forwarded-proto", "HOST_HEADER": "x-forwarded-host"}
        if has_prefix and prefix is None:
            r["warning_env_prefix"] = ("adapter-node envPrefix is not a plain string: set PORT, HOST, PROTOCOL_HEADER "
                                       "and HOST_HEADER with your prefix by hand")
        elif prefix:
            env = {f"{prefix}{k}": v for k, v in {**env, "PORT": "3000", "HOST": "0.0.0.0"}.items()}
        out = out or "build"
        return ssr_server(r, "sveltekit", "npm run build", out, ["node", f"{out}/index.js"], 3000, env)
    if adapter == "static":
        has_pages, pages = literal(text, "pages")
        if has_pages and pages is None:
            r["warning_config"] = "adapter-static «pages» is not a plain string: using the default «build»"
        _, fallback = literal(text, "fallback")
        return static_site(r, "sveltekit", "npm run build", pages or "build", spa=bool(fallback),
                           fallback=fallback or "index.html")
    return blocked(r, "sveltekit", f"SvelteKit uses adapter-{adapter}, which cannot run on a plain server: {hint}")


def analyze_react_router(root: Path, r: dict, pkg: dict) -> dict:
    text = config_text(root, "react-router.config") or ""
    if "@react-router/serve" not in (pkg.get("dependencies") or {}) and not re.search(r"\bssr\s*:\s*false\b", text):
        return blocked(r, "react-router", "React Router needs @react-router/serve in «dependencies» to run its server "
                                          "(npm install @react-router/serve), or add your own Dockerfile")
    has_dir, build_dir = literal(text, "buildDirectory")
    has_file, server_file = literal(text, "serverBuildFile")
    if (has_dir and build_dir is None) or (has_file and server_file is None):
        return blocked(r, "react-router", "react-router.config sets buildDirectory/serverBuildFile with code, not a "
                                          "plain string: add your own Dockerfile")
    build_dir = build_dir or "build"
    if re.search(r"\bssr\s*:\s*false\b", text):
        fallback = "__spa-fallback.html" if re.search(r"\bprerender\s*:", text) else "index.html"
        return static_site(r, "react-router", "npm run build", f"{build_dir}/client", spa=True, fallback=fallback)
    serve = ["./node_modules/.bin/react-router-serve", f"{build_dir}/server/{server_file or 'index.js'}"]
    return ssr_server(r, "react-router", "npm run build", build_dir, serve, 3000)


def analyze_angular(root: Path, r: dict, deps: dict) -> dict:
    ng = major(deps["@angular/core"]) or 99
    if any(k.startswith("@nguniversal/") for k in deps):
        return blocked(r, "angular", "Angular Universal (@nguniversal) is not supported: migrate to @angular/ssr "
                                     "(ng update) or add your own Dockerfile")
    project, out_dir, opts, builder = None, None, {}, ""
    try:
        ang = json.loads(read(root / "angular.json"))
        project = ang.get("defaultProject") or next(iter(ang["projects"]))
        build = ang["projects"][project]["architect"]["build"]
        opts, builder = build.get("options") or {}, build.get("builder", "")
        out_dir = opts.get("outputPath")
        if isinstance(out_dir, dict):
            out_dir = out_dir.get("base")
    except (json.JSONDecodeError, KeyError, StopIteration, AttributeError):
        pass
    base = out_dir or (f"dist/{project}" if project else "dist")
    modern = builder.endswith(":application") or ng >= 17
    ssr = bool(opts.get("ssr")) or bool(opts.get("prerender"))
    browser = f"{base}/browser" if modern else base
    if not (modern and opts.get("ssr")) or opts.get("outputMode") == "static":
        return static_site(r, "angular", "npx ng build --configuration production", browser, spa=True,
                           fallback="index.csr.html" if modern and ssr else "index.html")
    ssr_server(r, "angular", "npx ng build --configuration production", base,
               ["node", f"{base}/server/server.mjs"], 4000,
               {"NG_TRUST_PROXY_HEADERS": "x-forwarded-proto,x-forwarded-host"})
    if not (opts.get("security") or {}).get("allowedHosts"):
        r["runtime_env"] = {"NG_ALLOWED_HOSTS": "{domain}"}
    r["ssr_marker"] = "ng-server-context"
    return r


def analyze_node(root: Path) -> dict:
    pkg = json.loads(read(root / "package.json") or "{}")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    scripts = pkg.get("scripts", {})
    engines_node = (pkg.get("engines") or {}).get("node")
    nvmrc = read(root / ".nvmrc").strip() or read(root / ".node-version").strip()
    r: dict = {"language": "node", "key_dependencies": {k: deps[k] for k in deps if k in {
        "next", "react", "vue", "svelte", "@angular/core", "vite", "express", "hono", "fastify", "@nestjs/core",
        "nuxt", "astro", "@sveltejs/kit", "@react-router/dev", "@remix-run/dev", "typescript", "prisma",
        "@prisma/client", "drizzle-orm", "pg", "mysql2", "mongoose", "redis", "ioredis"}}}
    node = major(nvmrc) or major(engines_node)
    if "@angular/core" in deps and not node:
        node = int(NODE_FOR_ANGULAR.get(major(deps["@angular/core"]) or 0, "22"))
    r["node_version"] = str(node or 22)
    pm = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm"
    r["package_manager"] = pm
    if pm == "npm" and not (root / "package-lock.json").exists():
        r["warning_lock"] = "no package-lock.json: the build will use npm install (less reproducible)"

    meta = next((k for k in META_BLOCKED if k in deps), None)
    if meta:
        return blocked(r, META_BLOCKED[meta], f"{META_BLOCKED[meta]} has no template yet: add your own Dockerfile "
                                              "(it will be used as is)")
    if "next" in deps:
        text = config_text(root, "next.config") or ""
        if literal(text, "output")[1] == "export":
            return static_site(r, "nextjs", "npm run build", literal(text, "distDir")[1] or "out", spa=False)
        r.update(framework="nextjs", template="nextjs", port=3000)
    elif "@angular/core" in deps:
        analyze_angular(root, r, deps)
    elif "nuxt" in deps:
        analyze_nuxt(root, r, deps, scripts)
    elif "astro" in deps:
        analyze_astro(root, r, deps)
    elif "@sveltejs/kit" in deps:
        analyze_sveltekit(root, r)
    elif "@react-router/dev" in deps:
        analyze_react_router(root, r, pkg)
    elif "@remix-run/dev" in deps and "vite" in deps and "start" not in scripts:
        return blocked(r, "remix", "Remix with Vite and no «start» script: add \"start\": \"remix-serve "
                            "./build/server/index.js\" to package.json, upgrade to React Router, or add your own Dockerfile")
    elif "vite" in deps and not any(k in deps for k in ("express", "hono", "fastify", "@nestjs/core", "@remix-run/dev")):
        r.update(framework="vite", template="spa-nginx", port=80, spa=True, spa_fallback="index.html",
                 build_cmd=f"{pm} run build", build_dir="dist")
    elif "react-scripts" in deps:
        r.update(framework="create-react-app", template="spa-nginx", port=80, spa=True, spa_fallback="index.html",
                 build_cmd=f"{pm} run build", build_dir="build")
    else:
        fw = next((k for k in ("@remix-run/dev", "@nestjs/core", "hono", "fastify", "express") if k in deps), "node")
        port = 3000
        for f in list(root.glob("src/**/*.[tj]s"))[:200] + list(root.glob("*.[tj]s")):
            m = re.search(r"(?:listen|port)\D{0,40}?(\d{4,5})", read(f))
            if m:
                port = int(m.group(1))
                break
        r.update(framework="remix" if fw == "@remix-run/dev" else fw, template="node-server", port=port,
                 has_build="build" in scripts, has_start="start" in scripts)
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
        remote = re.sub(r"//[^/@]+@", "//", remote)  # never print credentials stored in the URL
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", remote)
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
        if stack.pop("warning_framework", None):  # the project's own Dockerfile is used as is
            warnings.append(f"{stack.get('framework') or 'this stack'} has no template: the project's own Dockerfile "
                            "is used as is (check its EXPOSE and that it listens on 0.0.0.0)")
        if expose:
            stack["port"] = int(expose[-1])
        else:
            warnings.append("the Dockerfile has no EXPOSE: the port must be confirmed")
    elif not stack.get("template") and not monorepo:
        blockers.append(stack.get("warning_framework") or "unknown project type")
    warnings += [stack[k] for k in stack if k.startswith("warning_")]

    # --- variables, databases, login, paid services
    res["env_vars"] = env_vars_used(root, files)
    if res["env_vars"]["build_time"]:
        res["build_time_env"] = res["env_vars"]["build_time"]
        warnings.append("variables imported from $env/static are needed at build time ("
                        + ", ".join(res["build_time_env"]) + "): upload them with env-push --buildtime, and pass test "
                        "values with --build-env to the local check")
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
    others = [d for d in dbs if d != "postgresql"]
    if others:
        blockers.append(f"uses {', '.join(others)}: only PostgreSQL can be created by this skill "
                        "(create it in Coolify by hand, or remove the dependency if it is unused)")
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
