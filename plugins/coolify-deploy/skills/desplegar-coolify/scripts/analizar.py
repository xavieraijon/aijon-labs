#!/usr/bin/env python3
"""Analiza un proyecto local y propone cómo desplegarlo en Coolify. Solo lectura.

Salida JSON con: stack, plantilla recomendada y sus valores, puerto, variables que usa el código,
bases de datos que parece necesitar, git (remoto, rama, cambios sin subir), secretos subidos por error,
indicios de login y de acciones de pago, y «bloqueos» (motivos para NO desplegar automáticamente).

Uso:  analizar.py <ruta>              análisis completo
      analizar.py <ruta> --secretos   solo el escaneo de secretos de los ficheros que se subirían (para antes de un push)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

IGNORAR_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".angular",
                ".nx", "vendor", ".cache", "coverage", ".turbo", ".pytest_cache", ".ruff_cache"}
MAX_FICHERO = 400_000  # bytes: no se leen ficheros más grandes en el escaneo

# Patrones de secretos (nombre → regex). Se informan con fichero y línea, nunca con el valor.
PATRONES_SECRETOS = {
    "clave privada": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "token de GitHub": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "clave de OpenAI/Anthropic": r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b",
    "clave de Google": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "token de Slack": r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
    "clave de Stripe": r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b",
    "URL con contraseña": r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:[^\s@'\"]{6,}@(?!localhost|127\.0\.0\.1|example)",
}
FICHEROS_SENSIBLES = re.compile(r"(^|/)(\.env(\.[\w-]+)?|.*\.pem|.*\.key|id_rsa|id_ed25519|credentials\.json|"
                                r"service-account.*\.json|wp-config\.php)$")
FICHEROS_PLANTILLA_ENV = re.compile(r"\.env\.(example|sample|template|dist|demo)$")

LIBS_LOGIN = ["next-auth", "@auth/", "passport", "@supabase/auth", "@clerk/", "lucia", "better-auth", "firebase/auth",
              "jsonwebtoken", "@nestjs/jwt", "flask_login", "flask-login", "fastapi.security", "django.contrib.auth",
              "authlib", "python-jose", "pyjwt", "fastapi-users", "laravel/sanctum", "laravel/breeze"]
INDICIOS_PAGO = ["stripe", "groq", "openai", "anthropic", "elevenlabs", "replicate", "ai33", "twilio", "sendgrid", "@google/genai",
                 "google.generativeai", "mailgun", "resend"]

# Angular mayor → Node con el que compila sin problemas
NODE_POR_ANGULAR = {12: "14", 13: "16", 14: "16", 15: "18", 16: "18", 17: "20", 18: "20", 19: "22", 20: "22"}


# ---------------------------------------------------------------- utilidades


def git(ruta: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(ruta), *args], capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def leer(ruta: Path) -> str:
    try:
        if ruta.stat().st_size > MAX_FICHERO:
            return ""
        return ruta.read_text(errors="ignore")
    except (OSError, UnicodeDecodeError):
        return ""


def ficheros_proyecto(raiz: Path) -> list[Path]:
    """Ficheros que se subirían: los de git si es repo (versionados + nuevos no ignorados); si no, recorrido normal."""
    salida = git(raiz, "ls-files", "--cached", "--others", "--exclude-standard")
    if salida:
        return [raiz / l for l in salida.splitlines() if (raiz / l).is_file()]
    res = []
    for p in raiz.rglob("*"):
        if p.is_file() and not any(parte in IGNORAR_DIRS for parte in p.relative_to(raiz).parts):
            res.append(p)
    return res


def mayor(version: str | None) -> int | None:
    m = re.search(r"(\d+)", version or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- análisis


def escanear_secretos(raiz: Path, ficheros: list[Path]) -> list[dict]:
    hallazgos = []
    for f in ficheros:
        rel = str(f.relative_to(raiz))
        if FICHEROS_SENSIBLES.search(rel) and not FICHEROS_PLANTILLA_ENV.search(rel):
            contenido = leer(f)
            con_valor = bool(re.search(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*\S+", contenido, re.M)) or "define(" in contenido
            hallazgos.append({"fichero": rel, "tipo": "fichero sensible", "con_valores": con_valor})
            continue
        if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".woff", ".woff2",
                                ".ttf", ".mp3", ".mp4", ".lock"} or f.name in {"package-lock.json", "yarn.lock",
                                                                                 "pnpm-lock.yaml", "poetry.lock"}:
            continue
        texto = leer(f)
        if not texto:
            continue
        for nombre, patron in PATRONES_SECRETOS.items():
            for m in re.finditer(patron, texto):
                linea = texto.count("\n", 0, m.start()) + 1
                hallazgos.append({"fichero": rel, "linea": linea, "tipo": nombre})
                break
    return hallazgos


def variables_usadas(raiz: Path, ficheros: list[Path]) -> dict:
    ejemplo = {}
    for nombre in (".env.example", ".env.sample", ".env.template", ".env.dist"):
        p = raiz / nombre
        if p.exists():
            for l in leer(p).splitlines():
                m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)", l)
                if m:
                    ejemplo[m.group(1)] = bool(m.group(2).strip().strip("\"'"))
            break
    en_codigo = set()
    patrones = [r"os\.(?:environ\.get|getenv)\(\s*['\"]([A-Z_][A-Z0-9_]*)", r"os\.environ\[\s*['\"]([A-Z_][A-Z0-9_]*)",
                r"process\.env\.([A-Z_][A-Z0-9_]*)", r"process\.env\[\s*['\"]([A-Z_][A-Z0-9_]*)",
                r"import\.meta\.env\.([A-Z_][A-Z0-9_]*)", r"env\(\s*['\"]([A-Z_][A-Z0-9_]*)",
                r"getenv\(\s*['\"]([A-Z_][A-Z0-9_]*)"]
    for f in ficheros:
        if f.suffix not in {".py", ".js", ".ts", ".mjs", ".cjs", ".tsx", ".jsx", ".php", ".vue", ".svelte"}:
            continue
        texto = leer(f)
        for p in patrones:
            en_codigo.update(re.findall(p, texto))
    ignorar = {"NODE_ENV", "PORT", "HOST", "PATH", "HOME", "PWD", "CI", "DEBUG", "TZ", "LANG"}
    return {"ejemplo": ejemplo, "en_codigo": sorted(en_codigo - ignorar)}


def detectar_monorepo(raiz: Path, ficheros: list[Path]) -> list[str]:
    motivos = []
    for marcador in ("nx.json", "turbo.json", "pnpm-workspace.yaml", "lerna.json", "rush.json"):
        if (raiz / marcador).exists():
            motivos.append(marcador)
    pkg = raiz / "package.json"
    if pkg.exists():
        try:
            if json.loads(leer(pkg)).get("workspaces"):
                motivos.append("package.json con workspaces")
        except json.JSONDecodeError:
            pass
    paquetes = {f.parent for f in ficheros if f.name in {"package.json", "requirements.txt", "pyproject.toml",
                                                          "composer.json"} and f.parent != raiz}
    raiz_tiene = any((raiz / n).exists() for n in ("package.json", "requirements.txt", "pyproject.toml", "composer.json"))
    if paquetes and (len(paquetes) > 1 or not raiz_tiene):
        motivos.append("varios proyectos en subcarpetas: " + ", ".join(sorted(str(p.relative_to(raiz)) for p in paquetes)[:5]))
    for nombre in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        dc = raiz / nombre
        if dc.exists():
            servicios = re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", leer(dc), re.M)
            if len(servicios) > 1:
                motivos.append(f"{nombre} con {len(servicios)} servicios ({', '.join(servicios[:5])})")
    return motivos


def analizar_node(raiz: Path) -> dict:
    pkg = json.loads(leer(raiz / "package.json") or "{}")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    scripts = pkg.get("scripts", {})
    engines_node = (pkg.get("engines") or {}).get("node")
    nvmrc = leer(raiz / ".nvmrc").strip() or leer(raiz / ".node-version").strip()
    r: dict = {"lenguaje": "node", "dependencias_clave": {k: deps[k] for k in deps if k in {
        "next", "react", "vue", "svelte", "@angular/core", "vite", "express", "hono", "fastify", "@nestjs/core",
        "nuxt", "astro", "@sveltejs/kit", "typescript", "prisma", "@prisma/client", "drizzle-orm", "pg", "mysql2",
        "mongoose", "redis", "ioredis"}}}
    node = mayor(nvmrc) or mayor(engines_node)
    if "@angular/core" in deps and not node:
        node = int(NODE_POR_ANGULAR.get(mayor(deps["@angular/core"]) or 0, "22"))
    r["node_version"] = str(node or 22)
    gestor = "pnpm" if (raiz / "pnpm-lock.yaml").exists() else "yarn" if (raiz / "yarn.lock").exists() else "npm"
    r["gestor"] = gestor
    if gestor == "npm" and not (raiz / "package-lock.json").exists():
        r["aviso_lock"] = "no hay package-lock.json: la build usará npm install (menos reproducible)"

    if "next" in deps:
        r.update(framework="nextjs", plantilla="nextjs", puerto=3000)
    elif "@angular/core" in deps:
        salida = None
        try:
            ang = json.loads(leer(raiz / "angular.json"))
            proyecto = ang.get("defaultProject") or next(iter(ang["projects"]))
            opts = ang["projects"][proyecto]["architect"]["build"]["options"]
            salida = opts.get("outputPath")
            if isinstance(salida, dict):
                salida = salida.get("base")
            builder = ang["projects"][proyecto]["architect"]["build"]["builder"]
            if builder.endswith(":application") or (mayor(deps["@angular/core"]) or 0) >= 17:
                salida = f"{salida}/browser"  # el builder moderno añade /browser
            ssr = "server" in opts or "ssr" in opts
        except (json.JSONDecodeError, KeyError, StopIteration):
            ssr = False
        r.update(framework="angular", plantilla="spa-nginx", puerto=80, spa=True,
                 build_cmd="npx ng build --configuration production", build_dir=salida or "dist")
        if ssr:
            r["aviso_ssr"] = "Angular con SSR: la plantilla estática no sirve; revisar a mano"
    elif any(k in deps for k in ("nuxt", "astro", "@sveltejs/kit")):
        r.update(framework=next(k for k in ("nuxt", "astro", "@sveltejs/kit") if k in deps), plantilla=None,
                 aviso_framework="framework con SSR propio: aún sin plantilla en la v1")
    elif "vite" in deps and not any(k in deps for k in ("express", "hono", "fastify", "@nestjs/core")):
        r.update(framework="vite", plantilla="spa-nginx", puerto=80, spa=True,
                 build_cmd=f"{gestor} run build", build_dir="dist")
    elif "react-scripts" in deps:
        r.update(framework="create-react-app", plantilla="spa-nginx", puerto=80, spa=True,
                 build_cmd=f"{gestor} run build", build_dir="build")
    else:
        fw = next((k for k in ("@nestjs/core", "hono", "fastify", "express") if k in deps), "node")
        puerto = 3000
        for f in list(raiz.glob("src/**/*.[tj]s"))[:200] + list(raiz.glob("*.[tj]s")):
            m = re.search(r"(?:listen|port)\D{0,40}?(\d{4,5})", leer(f))
            if m:
                puerto = int(m.group(1))
                break
        r.update(framework=fw, plantilla="node-server", puerto=puerto, tiene_build="build" in scripts,
                 tiene_start="start" in scripts)
        if "start" not in scripts:
            r["aviso_start"] = "package.json no tiene script «start»: hay que indicar cómo arrancar"
    return r


def analizar_python(raiz: Path, ficheros: list[Path]) -> dict:
    reqs = (leer(raiz / "requirements.txt") + leer(raiz / "pyproject.toml")).lower()
    r: dict = {"lenguaje": "python"}
    version = re.search(r"python_requires\s*=\s*['\"][^0-9]*(3\.\d+)|requires-python\s*=\s*['\"][^0-9]*(3\.\d+)",
                        leer(raiz / "pyproject.toml") + leer(raiz / "setup.py"))
    r["python_version"] = next((g for g in (version.groups() if version else ()) if g), "3.12")
    if not (raiz / "requirements.txt").exists():
        r["aviso_requirements"] = "no hay requirements.txt (la plantilla lo necesita; con pyproject hay que adaptar)"
    modulo = None
    for f in ficheros:
        if f.suffix == ".py" and (f.parent == raiz or f.parent.name in {"app", "src"}):
            texto = leer(f)
            m = re.search(r"^(\w+)\s*=\s*(FastAPI|Flask)\(", texto, re.M)
            if m:
                rel = f.relative_to(raiz).with_suffix("")
                modulo = ".".join(rel.parts) + ":" + m.group(1)
                break
    if "fastapi" in reqs:
        r.update(framework="fastapi", plantilla="python-fastapi", puerto=8000, modulo=modulo or "main:app")
    elif "flask" in reqs:
        r.update(framework="flask", plantilla="python-flask", puerto=8000, modulo=modulo or "app:app")
    elif "django" in reqs:
        r.update(framework="django", plantilla=None, aviso_framework="Django: aún sin plantilla en la v1")
    else:
        r.update(framework="python", plantilla=None, aviso_framework="no reconozco el framework web")
    return r


def analizar(raiz: Path) -> dict:
    raiz = raiz.resolve()
    if not raiz.is_dir():
        return {"ok": False, "error": f"No existe la carpeta {raiz}"}
    ficheros = ficheros_proyecto(raiz)
    res: dict = {"ok": True, "ruta": str(raiz), "nombre_sugerido": re.sub(r"[^a-z0-9-]", "-", raiz.name.lower()).strip("-")}
    bloqueos: list[str] = []
    avisos: list[str] = []

    # --- git
    if (raiz / ".git").exists():
        remoto = git(raiz, "remote", "get-url", "origin")
        m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", remoto)
        rama = git(raiz, "rev-parse", "--abbrev-ref", "HEAD")
        estado = git(raiz, "status", "--porcelain")
        sin_subir = git(raiz, "rev-list", "--count", "@{u}..HEAD") if remoto else ""
        res["git"] = {"remoto": m.group(1) if m else (remoto or None), "rama": rama,
                      "cambios_sin_commit": len(estado.splitlines()) if estado else 0,
                      "commits_sin_subir": int(sin_subir) if sin_subir.isdigit() else None,
                      "tiene_upstream": bool(sin_subir)}
        if remoto and not m:
            bloqueos.append("el remoto no es de GitHub (la v1 solo despliega desde GitHub)")
    else:
        res["git"] = None

    # --- stack
    dockerfile = raiz / "Dockerfile"
    monorepo = detectar_monorepo(raiz, ficheros)
    if monorepo:
        res["monorepo"] = monorepo
        bloqueos.append("monorepo o varios servicios (" + "; ".join(monorepo) + "): fuera del alcance de la v1")
    if (raiz / "package.json").exists():
        res["stack"] = analizar_node(raiz)
    elif (raiz / "requirements.txt").exists() or (raiz / "pyproject.toml").exists():
        res["stack"] = analizar_python(raiz, ficheros)
    elif (raiz / "composer.json").exists() or any(f.suffix == ".php" for f in ficheros):
        composer = leer(raiz / "composer.json")
        if "laravel/framework" in composer or "symfony/" in composer:
            res["stack"] = {"lenguaje": "php", "framework": "laravel/symfony", "plantilla": None,
                            "aviso_framework": "framework PHP completo: aún sin plantilla en la v1"}
        else:
            res["stack"] = {"lenguaje": "php", "framework": "php", "plantilla": "php-apache", "puerto": 80}
    elif (raiz / "index.html").exists():
        res["stack"] = {"lenguaje": "html", "framework": "estatico", "plantilla": "static-nginx", "puerto": 80}
    else:
        res["stack"] = {"lenguaje": None, "plantilla": None}
    stack = res["stack"]
    if dockerfile.exists():
        expose = re.findall(r"^\s*EXPOSE\s+(\d+)", leer(dockerfile), re.M | re.I)
        stack["dockerfile_existente"] = True
        stack["plantilla"] = None
        if expose:
            stack["puerto"] = int(expose[-1])
        else:
            avisos.append("el Dockerfile no tiene EXPOSE: hay que confirmar el puerto")
    elif not stack.get("plantilla") and not monorepo:
        bloqueos.append(stack.get("aviso_framework") or "no sé qué tipo de proyecto es")
    for k in [k for k in stack if k.startswith("aviso_")]:
        avisos.append(stack[k])

    # --- variables, BD, login, pago
    res["variables"] = variables_usadas(raiz, ficheros)
    todo = " ".join(leer(f).lower() for f in ficheros if f.name in {
        "package.json", "requirements.txt", "pyproject.toml", "composer.json", "schema.prisma", "drizzle.config.ts"})
    nombres = set(res["variables"]["en_codigo"]) | set(res["variables"]["ejemplo"])
    bd = []
    if "DATABASE_URL" in nombres or any(x in todo for x in ("psycopg", "asyncpg", '"pg"', "postgres", "sqlalchemy", "prisma")):
        bd.append("postgresql")
    if any(x in todo for x in ("mysql", "mariadb")):
        bd.append("mysql")
    if any(x in todo for x in ("mongoose", "mongodb", "pymongo")):
        bd.append("mongodb")
    if "REDIS_URL" in nombres or any(x in todo for x in ('"redis"', "ioredis", "redis==", "redis>")):
        bd.append("redis")
    if "supabase" in todo:
        res["servicios_externos"] = ["supabase (en la nube: solo hacen falta sus variables)"]
        if "DATABASE_URL" not in nombres:  # con Supabase la BD está en la nube, salvo que use una URL propia
            bd = [b for b in bd if b != "postgresql"]
    res["bases_de_datos"] = bd
    res["tiene_login_estimado"] = any(lib in todo for lib in LIBS_LOGIN)
    pago = sorted({p for p in INDICIOS_PAGO if p in todo})
    res["servicios_de_pago_estimados"] = pago
    if pago and not res["tiene_login_estimado"]:
        avisos.append(f"usa servicios de pago ({', '.join(pago)}) y no parece tener login: proponer acceso protegido")

    # --- secretos
    secretos = escanear_secretos(raiz, ficheros)
    res["secretos"] = secretos
    if secretos:
        bloqueos.append(f"hay {len(secretos)} posible(s) secreto(s) en ficheros que se subirían (revisar antes de publicar)")

    res["avisos"] = avisos
    res["bloqueos"] = bloqueos
    res["desplegable"] = not bloqueos
    return res


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(__doc__)
        sys.exit(0)
    raiz = Path(sys.argv[1]).expanduser()
    if "--secretos" in sys.argv:
        ficheros = ficheros_proyecto(raiz.resolve())
        hallazgos = escanear_secretos(raiz.resolve(), ficheros)
        print(json.dumps({"ok": not hallazgos, "secretos": hallazgos}, ensure_ascii=False))
        sys.exit(0 if not hallazgos else 1)
    print(json.dumps(analizar(raiz), ensure_ascii=False))


if __name__ == "__main__":
    main()
