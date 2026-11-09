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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phpstack import GENERATED_MARKER, analyze_laravel, laravel_env, php_framework  # noqa: E402
from pystack import analyze_python, is_django  # noqa: E402

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
                             r"service-account.*\.json|wp-config\.php|auth\.json)$")
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
# Prefixes a bundler/framework inlines into the browser bundle at build time (kept in sync with coolify.py's copy)
PUBLIC_PREFIXES = ("NEXT_PUBLIC_", "VITE_", "PUBLIC_", "NUXT_PUBLIC_", "REACT_APP_")
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
# Folders that are never an app of a repository with several apps
NOT_APP_DIRS = {"docs", "examples", "tests", "e2e", "cypress", "infra", "scripts", "tools", "bin", "docker", "deploy",
                "deployment", "k8s", "kubernetes", "helm", "charts"}
NOT_APP_HTML_DIRS = {"src", "public", "templates", "static", "assets"}  # an index.html there is a build input
APP_PATH = re.compile(r"[A-Za-z0-9._~@+/-]+")  # what Coolify accepts in base_directory


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


def repo_root(path: Path) -> tuple[Path, str]:
    """(repository root as git spells it, path of the folder inside it like «backend/»); (path, "") without git."""
    top = git(path, "rev-parse", "--show-toplevel")
    return (Path(top).resolve(), git(path, "rev-parse", "--show-prefix")) if top else (path, "")


def project_files(root: Path) -> list[Path]:
    """Files that would be pushed: git-tracked plus untracked-not-ignored if it is a repo; otherwise a plain walk."""
    out = git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    if out:
        return [root / l for l in out.splitlines() if (root / l).is_file()]
    return [p for p in root.rglob("*")
            if p.is_file() and not any(part in IGNORED_DIRS for part in p.relative_to(root).parts)]


def with_build_args(dockerfile: str, keys: list[str]) -> str:
    """Add «ARG KEY» after every FROM line: Coolify exports build-time variables to the build host's shell and
    passes «--build-arg KEY» (no value, read from that shell), but Docker only exposes a build arg to RUN
    commands when the Dockerfile declares it with ARG — otherwise it is silently dropped."""
    if not keys:
        return dockerfile
    out = []
    for line in dockerfile.splitlines():
        out.append(line)
        if re.match(r"\s*FROM\s", line, re.I):
            out += [f"ARG {k}" for k in keys]
    return "\n".join(out) + "\n"


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


def compose_blocks(text: str) -> dict[str, str]:
    """Service name → its body, for the top-level services: block only (2-space keys, 4 in Laravel Sail…)."""
    m = re.search(r"^services:[ \t]*$(.*?)(?=^\S|\Z)", text, re.M | re.S)
    indent = re.search(r"^([ \t]+)\S", m.group(1), re.M) if m else None
    if not indent:
        return {}
    parts = re.split(rf"^{indent.group(1)}([A-Za-z0-9_.-]+):[ \t]*$", m.group(1), flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def compose_services(text: str) -> list[str]:
    return list(compose_blocks(text))


def compose_builds(text: str) -> dict[str, str | None]:
    """Service name → folder it builds from, relative to the compose file («» = that folder); None = image only."""
    out: dict[str, str | None] = {}
    for name, body in compose_blocks(text).items():
        b = re.search(r"^\s+build:[ \t]*([^#\n]*)", body, re.M)
        if not b:
            out[name] = None
            continue
        value = b.group(1).strip().strip("'\"")
        if not value:  # long form: build: {context: …}; no context means the compose folder
            c = re.search(r"^\s+context:[ \t]*([^#\n]+)", body, re.M)
            value = c.group(1).strip().strip("'\"") if c else "."
        value = re.sub(r"^(\./)+", "", value.rstrip("/") or ".")
        out[name] = "" if value == "." else value
    return out


def pnpm_workspace_packages(text: str) -> list[str]:
    """Entries of the packages: list of pnpm-workspace.yaml (block or flow form); [] when there is no such key."""
    m = re.search(r"^packages:[ \t]*(.*)$", text, re.M)
    if not m:
        return []
    rest = m.group(1).split("#")[0].strip()
    if rest.startswith("["):
        items = rest.strip("[]").split(",")
    else:
        block = re.match(r"((?:^[ \t]+-.*\n?|^[ \t]*(?:#.*)?\n)*)", text[m.end() + 1:], re.M)
        items = re.findall(r"^[ \t]+-[ \t]*([^#\n]*)", block.group(1) if block else "", re.M)
    return [i.strip().strip("'\"") for i in items if i.strip().strip("'\"")]


def workspace_reasons(top: Path) -> list[str]:
    """Signs that the repository is a workspace (shared lockfile and packages): read at the repository root."""
    reasons = [m for m in ("nx.json", "turbo.json", "lerna.json", "rush.json") if (top / m).exists()]
    if [p for p in pnpm_workspace_packages(read(top / "pnpm-workspace.yaml")) if p not in {".", "./"}]:
        reasons.append("pnpm-workspace.yaml with packages")
    try:
        if json.loads(read(top / "package.json") or "{}").get("workspaces"):
            reasons.append("package.json with workspaces")
    except (json.JSONDecodeError, AttributeError):
        pass
    if re.search(r"^\[tool\.uv\.workspace\]", read(top / "pyproject.toml"), re.M):
        reasons.append("uv workspace in pyproject.toml")
    return reasons


def root_app(root: Path) -> bool:
    return any((root / n).exists() for n in (*MANIFESTS, "Dockerfile", "index.html"))


def skipped_folder(rel: Path) -> bool:
    return any(p in IGNORED_DIRS or p in NOT_APP_DIRS or p.startswith(".") for p in rel.parts)


def app_folders(root: Path, files: list[Path]) -> tuple[list[str], list[str]]:
    """Folders (up to two levels deep) that look like apps of their own, and compose files that block.

    A manifest or a Dockerfile makes a folder an app; an index.html only when no manifest is in it or above it and
    it is not a sources/templates folder. Compose files add the folders their services build from."""
    rels = [f.relative_to(root) for f in files]
    found = {r.parent for r in rels if r.name in (*MANIFESTS, "Dockerfile")}
    for r in rels:
        d = r.parent
        if r.name == "index.html" and d.name not in NOT_APP_HTML_DIRS and not any(
                (root / a / m).exists() for a in (d, *d.parents) for m in MANIFESTS):
            found.add(d)
    blocking = []
    for name in COMPOSE_FILES:
        builds = compose_builds(read(root / name))
        from_root = [s for s, b in builds.items() if b == ""]
        if len(from_root) > 1:
            blocking.append(f"{name} with {len(from_root)} services built from the project folder "
                            f"({', '.join(from_root[:5])})")
        found |= {Path(b) for b in builds.values() if b and not b.startswith("/") and ".." not in Path(b).parts}
    found = {d for d in found if 1 <= len(d.parts) <= 2 and not skipped_folder(d)}
    apps = sorted(str(d) for d in found if not any(a in found for a in d.parents))
    return apps, blocking


def detect_monorepo(root: Path, files: list[Path], top: Path | None = None) -> dict | None:
    """How the folder holds several apps, if it does: workspaces, app folders, both a root app and app folders."""
    reasons = workspace_reasons(root) + (workspace_reasons(top) if top and top != root else [])
    if reasons:
        return {"kind": "workspaces", "reasons": reasons}
    apps, blocking = app_folders(root, files)
    if blocking:
        return {"kind": "services", "reasons": blocking}
    if not apps or (root_app(root) and len(apps) == 1):
        return None
    return {"kind": "apps" if not root_app(root) else "mixed", "apps": apps}


def outside_references(root: Path) -> list[str]:
    """Dependencies that point outside the folder: the image is built from the folder alone."""
    found = []
    try:
        pkg = json.loads(read(root / "package.json") or "{}")
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            for dep, value in (pkg.get(section) or {}).items():
                if isinstance(value, str) and re.match(r"(file:|link:|portal:)?\.\./|workspace:", value):
                    found.append(f"{dep} ({value})")
    except (json.JSONDecodeError, AttributeError):
        pass
    for f in sorted(root.glob("requirements*.txt")):
        found += [line.strip() for line in read(f).splitlines() if re.match(r"\s*(-e\s+)?(file:)?\.\./", line)]
    found += re.findall(r"""path\s*=\s*["'](\.\./[^"']*)""", read(root / "pyproject.toml"))
    return found[:5]


def parent_apps_warning(root: Path) -> str | None:
    """No git yet: siblings with their own manifest may belong to the same repository (direct subfolders of a parent
    that looks like a repository: compose file, .gitignore, README or Makefile)."""
    parent = root.parent
    looks_like_repo = any((parent / n).exists() for n in (*COMPOSE_FILES, ".gitignore", "README.md", "README", "Makefile"))
    if parent == Path.home() or root_app(parent) or not looks_like_repo:  # a plain folder of projects is not a repo
        return None
    siblings = sorted(d.name for d in parent.iterdir()
                      if d.is_dir() and d != root and not d.name.startswith(".") and d.name not in NOT_APP_DIRS
                      and any((d / m).exists() for m in (*MANIFESTS, "Dockerfile")))
    if not siblings:
        return None
    return (f"{parent} holds other apps ({', '.join(siblings[:5])}) and nothing is a git repository yet: if they belong "
            f"to one repository, analyse {parent} instead; otherwise this folder becomes its own repository")


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
            ssr_server(r, "astro", "npm run build", "dist", ["node", "dist/server/entry.mjs"], 4321)
            # Astro trusts X-Forwarded-Proto only for hosts in security.allowedDomains; otherwise checkOrigin
            # sees http:// and rejects every form POST (403)
            if not re.search(r"\ballowedDomains\s*:|\bcheckOrigin\s*:\s*false\b", text):
                cfg = next((f.name for f in sorted(root.glob("astro.config.*"))), "astro.config.mjs")
                origin_fix(r, "Astro", cfg, 'security: { allowedDomains: [{ hostname: "{domain}", protocol: "https" }] }',
                           403)
            return r
        return blocked(r, "astro", "Astro's @astrojs/node adapter must use mode: 'standalone' to run on its own "
                                   f"(found: {mode or 'not set'}), or add your own Dockerfile")
    if literal(text, "output")[1] == "server":
        return blocked(r, "astro", "Astro has output: 'server' but no adapter: install @astrojs/node "
                                   "(mode: 'standalone'), or remove output: 'server' for a static site")
    return static_site(r, "astro", "npm run build", "dist", spa=False)


def analyze_sveltekit(root: Path, r: dict) -> dict:
    # SvelteKit ≤ 2: svelte.config.*; SvelteKit 3: options of the sveltekit() plugin in vite.config.*
    adapter_import = r"""from\s+['"]@sveltejs/adapter-([\w-]+)['"]"""
    text = config_text(root, "svelte.config") or ""
    if not re.search(adapter_import, text):
        text = config_text(root, "vite.config") or text
    m = re.search(adapter_import, text)
    adapter = m.group(1) if m else "auto"
    hint = ("install @sveltejs/adapter-node (server) or @sveltejs/adapter-static (static site) and use it in "
            "svelte.config.js (SvelteKit 3: in the sveltekit() options of vite.config.ts)")
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
    ssr_server(r, "react-router", "npm run build", build_dir, serve, 3000)
    if not re.search(r"\ballowedActionOrigins\s*:", text):
        # react-router-serve does not trust the proxy: behind HTTPS it sees http://, so the Origin check fails
        origin_fix(r, "React Router", "react-router.config.ts", 'allowedActionOrigins: ["{domain}"]', 400)
    return r


def origin_fix(r: dict, name: str, file: str, line: str, status: int) -> None:
    """Form posts fail behind the HTTPS proxy until the project trusts its own domain (a code change: offer it)."""
    r["origin_fix"] = {"file": file, "add": line}
    r["warning_origin"] = (f"{name} rejects form submissions ({status}) behind an HTTPS proxy until {file} trusts the "
                           f"app's domain: add {line}")


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


def infer_databases(stack: dict, names: set, manifests: str) -> list[str]:
    dbs = []
    if "DATABASE_URL" in names or any(x in manifests for x in ("psycopg", "asyncpg", '"pg"', "postgres",
                                                                "sqlalchemy", "prisma")):
        dbs.append("postgresql")
    if stack.get("db_engine") in ("postgresql", "sqlite") and "postgresql" not in dbs:
        dbs.append("postgresql")  # Django: SQLite would lose its data on every deploy
    if any(x in manifests for x in ("mysql", "mariadb")) or stack.get("db_engine") == "mysql":
        dbs.append("mysql")
    if any(x in manifests for x in ("mongoose", "mongodb", "pymongo")):
        dbs.append("mongodb")
    if "REDIS_URL" in names or any(x in manifests for x in ('"redis"', "ioredis", "redis==", "redis>")):
        dbs.append("redis")
    return dbs


def app_summary(root: Path, rel: str) -> dict:
    r = analyze(root / rel)
    stack = r.get("stack") or {}
    name = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", f"{root.name}-{rel}".lower())).strip("-")[:63].strip("-")
    return {"path": rel, "suggested_name": name,
            "language": stack.get("language"), "framework": stack.get("framework"), "template": stack.get("template"),
            "existing_dockerfile": bool(stack.get("existing_dockerfile")), "build_dir": stack.get("build_dir"),
            "databases": r.get("databases"),
            "deployable": r["deployable"], "blockers": r["blockers"]}


def analyze(root: Path) -> dict:
    root = root.resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"Folder {root} does not exist"}
    # --- git (the folder may be an app inside a repository: git.root is the repository, git.subdir the app)
    top, subdir = repo_root(root)
    root = top / subdir  # git's spelling of the path (case-insensitive file systems: «personal» vs «Personal»)
    files = project_files(root)
    res: dict = {"ok": True, "path": str(root)}
    blockers: list[str] = []
    warnings: list[str] = []
    name = f"{top.name}-{subdir}" if subdir else root.name
    res["suggested_name"] = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", name.lower())).strip("-")[:63].strip("-")
    if git(root, "rev-parse", "--is-inside-work-tree") == "true":
        remote = git(root, "remote", "get-url", "origin")
        remote = re.sub(r"//[^/@]+@", "//", remote)  # never print credentials stored in the URL
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", remote)
        status = git(root, "status", "--porcelain")
        ahead = git(root, "rev-list", "--count", "@{u}..HEAD") if remote else ""
        res["git"] = {"remote": m.group(1) if m else (remote or None), "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
                      "uncommitted_changes": len(status.splitlines()) if status else 0,
                      "unpushed_commits": int(ahead) if ahead.isdigit() else None,
                      "has_upstream": bool(ahead), "root": str(top), "subdir": subdir}
        if remote and not m:
            blockers.append("the remote is not on GitHub (only GitHub repositories are supported)")
        if top == Path.home().resolve():
            blockers.append("the folder is inside a git repository at your home folder: use a project folder with "
                            "its own repository")
        if subdir and not APP_PATH.fullmatch(subdir.rstrip("/")):
            blockers.append(f"the folder {subdir.rstrip('/')} has characters Coolify does not accept in a base "
                            "directory (letters, digits, . _ - ~ @ + only): rename it")
    else:
        res["git"] = None
        if warning := parent_apps_warning(root):
            warnings.append(warning)

    # --- stack
    php = php_framework(root)
    monorepo = detect_monorepo(root, files, top if subdir else None)
    if monorepo:
        res["monorepo"] = monorepo
        if monorepo["kind"] == "workspaces":
            blockers.append("workspaces (" + "; ".join(monorepo["reasons"]) + ") are not supported: the apps share the "
                            "root lockfile and packages, so they cannot be built from their own folders")
        elif monorepo["kind"] == "services":
            blockers.append("several services (" + "; ".join(monorepo["reasons"]) + "): not supported")
        elif monorepo["kind"] == "mixed":
            blockers.append("an app at the root plus several app folders (" + ", ".join(monorepo["apps"][:5])
                            + "): move the root app into its own folder")
        else:
            monorepo["apps"] = [app_summary(root, a) for a in monorepo["apps"]]
            blockers.append("several apps in this repository (" + ", ".join(a["path"] for a in monorepo["apps"][:5])
                            + "): deploy each from its folder")
    outside = outside_references(root)
    if outside:
        blockers.append(f"imports code from outside its folder ({', '.join(outside)}): the build only sees this folder; "
                        "move that code inside it or publish it as a package")
    if is_django(root):  # wins over a package.json (Tailwind, django-vite…)
        res["stack"] = analyze_python(root, files)
        pkg_scripts = {}
        try:
            pkg_scripts = json.loads(read(root / "package.json") or "{}").get("scripts") or {}
        except (json.JSONDecodeError, AttributeError):
            pass
        if pkg_scripts.get("build"):
            res["stack"].update(template=None, warning_framework=(
                "Django with a frontend build (package.json) is not supported yet: add your own Dockerfile"))
        elif (root / "package.json").exists():
            warnings.append("package.json is ignored: the image only installs the Python dependencies")
    elif php == "laravel":  # wins over its package.json (Vite)
        res["stack"] = analyze_laravel(root, files)
        if any("laravel.test" in compose_services(read(root / n)) for n in ("docker-compose.yml", "docker-compose.yaml",
                                                                             "compose.yml", "compose.yaml")):
            warnings.append("Sail's compose file is for local development: only the web app is deployed, with "
                            "PostgreSQL")
    elif php == "symfony":
        res["stack"] = {"language": "php", "framework": "symfony", "template": None,
                        "warning_framework": "Symfony has no template yet: add your own Dockerfile"}
    elif (root / "package.json").exists():
        res["stack"] = analyze_node(root)
    elif (root / "requirements.txt").exists() or (root / "pyproject.toml").exists() or (root / "Pipfile").exists():
        res["stack"] = analyze_python(root, files)
    elif (root / "composer.json").exists() or any(f.suffix == ".php" for f in files):
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
        if stack.get("template"):  # what prepare.py --overwrite regenerates (e.g. a Dockerfile it wrote before)
            stack["suggested_template"] = stack["template"]
        stack["template"] = None
        if stack.pop("warning_framework", None):  # the project's own Dockerfile is used as is
            warnings.append(f"{stack.get('framework') or 'this stack'} has no template: the project's own Dockerfile "
                            "is used as is (check its EXPOSE and that it listens on 0.0.0.0)")
        if stack.get("trust_proxies") == "generated" and GENERATED_MARKER not in read(root / "config" / "trustedproxy.php"):
            # Laravel with a foreign Dockerfile: no proxy file is generated (one written by prepare.py stays valid)
            stack["trust_proxies"] = "dockerfile"
            stack["warning_proxies"] = ("your Dockerfile or app must trust Coolify's proxy (e.g. trustProxies(at: '*')) "
                                        "or URLs and assets will use http://")
        if expose:
            stack["port"] = int(expose[-1])
        else:
            warnings.append("the Dockerfile has no EXPOSE: the port must be confirmed")
    elif not stack.get("template") and not monorepo:
        blockers.append(stack.get("warning_framework") or "unknown project type")
    warnings += [stack[k] for k in stack if k.startswith("warning_")]

    # --- variables, databases, login, paid services
    res["env_vars"] = env_vars_used(root, files)
    if stack.get("framework") == "laravel":
        warnings += laravel_env(root, files, res["env_vars"], bool(stack.get("existing_dockerfile")),
                                stack.get("laravel_version"))
    managed = set(stack.get("managed_env") or [])
    if managed:  # set by the deployment itself (generated, from the domain, the database): never asked from the user
        res["env_vars"]["in_code"] = [k for k in res["env_vars"]["in_code"] if k not in managed]
        res["env_vars"]["example"] = {k: v for k, v in res["env_vars"]["example"].items() if k not in managed}
        res["env_vars"]["managed"] = sorted(managed)
    if res["env_vars"]["build_time"]:
        res["build_time_env"] = res["env_vars"]["build_time"]
        warnings.append("variables imported from $env/static are needed at build time ("
                        + ", ".join(res["build_time_env"]) + "): upload them with env-push --buildtime, and pass test "
                        "values with --build-env to the local check")
    # Names a bundler inlines into the browser bundle (VITE_*…) are build-time too, even though the code never
    # says so explicitly; env-push already uploads them with is_buildtime=true. prepare.py declares them with ARG
    # so the Dockerfile actually receives them (Coolify drops an undeclared build-arg silently).
    public_env = {k for k in set(res["env_vars"]["in_code"]) | set(res["env_vars"]["example"])
                 if k.startswith(PUBLIC_PREFIXES)}
    res["build_time_candidates"] = sorted(set(res["env_vars"]["build_time"]) | public_env)
    manifests = " ".join(read(f).lower() for f in files if f.name in {*MANIFESTS, "schema.prisma", "drizzle.config.ts"})
    names = set(res["env_vars"]["in_code"]) | set(res["env_vars"]["example"])
    if stack.get("framework") == "laravel":  # decided by phpstack alone (config/database.php names every driver)
        dbs = list(stack["databases"])
    else:
        dbs = infer_databases(stack, names, manifests)
        if "supabase" in manifests:
            res["external_services"] = ["supabase (hosted: only its variables are needed)"]
            if "DATABASE_URL" not in names:  # with Supabase the database is hosted, unless it uses its own URL
                dbs = [d for d in dbs if d != "postgresql"]
    res["databases"] = dbs
    others = [d for d in dbs if d != "postgresql"]
    if others:
        blockers.append(f"uses {', '.join(others)}: only PostgreSQL can be created by this skill "
                        "(create it in Coolify by hand, or remove the dependency if it is unused)")
    res["has_login_estimate"] = any(lib in manifests for lib in LOGIN_LIBS) or bool(stack.get("has_login"))
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
