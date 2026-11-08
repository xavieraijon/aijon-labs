"""Python projects for analyze.py: dependency source (pip, uv, Poetry, pyproject), Python version and framework
(FastAPI, Flask, Django). Read-only: project files are read as text, never imported or executed.

Every value that ends up in a Dockerfile comes from the fixed tables below, never from the project's files;
module paths read from the project are checked against strict identifier patterns.
"""

from __future__ import annotations

import re
from pathlib import Path

MAX_FILE = 400_000
UV_IMAGE = "ghcr.io/astral-sh/uv:0.13.7"
POETRY_VERSION = "2.5.1"

PIP_UV = "uv pip install --python /opt/venv/bin/python"
INSTALLS = {
    "uv": "uv sync --locked --no-dev --no-install-project",
    "poetry": "/opt/poetry/bin/poetry install --only main --no-root",
    "pip": f"{PIP_UV} -r requirements.txt",
    "pyproject": f"{PIP_UV} -r pyproject.toml",
}
DEPS_FILES = {"uv": "pyproject.toml uv.lock", "poetry": "pyproject.toml poetry.lock", "pip": "requirements.txt",
              "pyproject": "pyproject.toml"}
POETRY_SETUP = f" && python -m venv /opt/poetry && /opt/poetry/bin/pip install poetry=={POETRY_VERSION}"
COLLECTSTATIC = "RUN DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput"
BASE_PACKAGES = {"fastapi": ["uvicorn[standard]"], "flask": ["gunicorn"], "django": ["gunicorn"]}

MODULE_PATH = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
WSGI_MODULE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*")
PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[a-z0-9,_-]+\])?")

# Variables the deployment sets itself (Django overlay): never offered in env-template, never pushed by the user
DJANGO_MANAGED_ENV = ["DJANGO_SECRET_KEY", "DJANGO_ALLOWED_HOSTS", "DJANGO_DEBUG", "DJANGO_INSECURE_COOKIES"]
MIN_DJANGO = (4, 2)


def read(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            return ""
        return path.read_text(errors="ignore")
    except (OSError, UnicodeDecodeError):
        return ""


def norm(name: str) -> str:
    """PEP 503 normalised distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


# ---------------------------------------------------------------- minimal TOML reading (no tomllib on 3.10)


def section(text: str, name: str) -> str | None:
    """Body of the [name] table, up to the next table header."""
    m = re.search(rf"^\[{re.escape(name)}\]\s*$", text, re.M)
    if not m:
        return None
    end = re.search(r"^\s*\[", text[m.end():], re.M)
    return text[m.end(): m.end() + end.start()] if end else text[m.end():]


def toml_array(body: str, key: str) -> list[str] | None:
    """Strings of `key = [ ... ]` (may span lines); None if the key is absent or not a plain array."""
    m = re.search(rf"^\s*{re.escape(key)}\s*=\s*\[", body, re.M)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(body) and depth:
        ch = body[i]
        if ch in "\"'":
            close = body.find(ch, i + 1)
            i = close if close != -1 else len(body)
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "#":
            nl = body.find("\n", i)
            i = nl if nl != -1 else len(body)
        i += 1
    if depth:
        return None
    return [a or b for a, b in re.findall(r'"([^"]*)"|\'([^\']*)\'', body[m.end(): i - 1])]


def table_entries(body: str) -> dict[str, str]:
    """`key = value` lines of a table (one level; values are kept as raw text)."""
    out = {}
    for line in body.splitlines():
        m = re.match(r"""\s*["']?([A-Za-z0-9][A-Za-z0-9._-]*)["']?\s*=\s*(.+?)\s*$""", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def parse_requirement(req: str) -> tuple[str, set[str], str] | None:
    """`name[extra,...] spec` → (normalised name, extras, spec). None for options, URLs and local paths."""
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?\s*(.*)", req)
    if not m:
        return None
    spec = m.group(3).split(";")[0].split("#")[0].strip()
    extras = {norm(e) for e in (m.group(2) or "").split(",") if e.strip()}
    return norm(m.group(1)), extras, spec


# ---------------------------------------------------------------- dependency source


def requirements(root: Path, rel: str, seen: set[str]) -> tuple[dict, bool]:
    """Names from a requirements file, following -r/-c inside the repository. Returns (names, has local refs)."""
    names: dict = {}
    local = False
    if rel in seen or ".." in Path(rel).parts:
        return names, local
    seen.add(rel)
    path = root / rel
    for raw in read(path).splitlines():
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"(-r|--requirement|-c|--constraint)[\s=]+(\S+)", line)
        if m:
            local = True  # included files must be in the build context before the install
            inc = str(Path(rel).parent / m.group(2))
            sub, _ = requirements(root, inc, seen)
            if m.group(1) in ("-r", "--requirement"):
                names.update(sub)
            continue
        if line.startswith(("-e", "--editable", ".", "/", "file:")) or re.search(r"@\s*file:", line):
            local = True
            continue
        if line.startswith("-"):
            continue  # index options
        p = parse_requirement(line)
        if p and "://" not in line:
            names[p[0]] = (p[1], p[2])
    return names, local


def project_deps(text: str) -> tuple[dict, bool, bool]:
    """[project] dependencies → (names, local refs, dynamic dependencies)."""
    body = section(text, "project")
    if body is None:
        return {}, False, False
    dynamic = "dependencies" in (toml_array(body, "dynamic") or [])
    names, local = {}, False
    for req in toml_array(body, "dependencies") or []:
        if re.search(r"@\s*file:", req) or req.strip().startswith((".", "/")):
            local = True
            continue
        p = parse_requirement(req)
        if p:
            names[p[0]] = (p[1], p[2])
    return names, local, dynamic


def poetry_deps(text: str) -> tuple[dict, bool, str | None]:
    """[tool.poetry.dependencies] → (names, local refs, python constraint)."""
    body = section(text, "tool.poetry.dependencies")
    names, local, python = {}, False, None
    for key, value in table_entries(body or "").items():
        if key == "python":
            python = value
            continue
        if re.search(r"\bpath\s*=", value):
            local = True
        extras = set()
        m = re.search(r"extras\s*=\s*\[([^\]]*)\]", value)
        if m:
            extras = {norm(e) for e in re.findall(r"[\"']([^\"']+)", m.group(1))}
        spec = value.strip().strip("\"'") if value.lstrip()[:1] in "\"'" else ""
        vm = re.search(r"version\s*=\s*[\"']([^\"']+)", value)
        names[norm(key)] = (extras, vm.group(1) if vm else spec)
    return names, local, python


def locked_version(root: Path, name: str) -> str | None:
    for lock in ("uv.lock", "poetry.lock"):
        m = re.search(rf'^name\s*=\s*"{re.escape(name)}"\s*\n\s*version\s*=\s*"([^"]+)"', read(root / lock), re.M | re.I)
        if m:
            return m.group(1)
    return None


def deps_source(root: Path) -> dict:
    """Which file lists the dependencies and how the image installs them."""
    pyproject = read(root / "pyproject.toml")
    order = [("uv", "uv.lock"), ("poetry", "poetry.lock"), ("pip", "requirements.txt")]
    present = [kind for kind, f in order if (root / f).is_file()]
    proj_names, proj_local, dynamic = project_deps(pyproject)
    if pyproject and section(pyproject, "project") is not None and toml_array(section(pyproject, "project"), "dependencies"):
        present.append("pyproject")
    r: dict = {"warnings": []}
    if not present:
        if (root / "Pipfile").is_file():
            r["blocked"] = ("Pipfile (Pipenv) is not supported: export a requirements.txt "
                            "(pipenv requirements > requirements.txt) or add your own Dockerfile")
        elif dynamic:
            r["blocked"] = "dependencies are dynamic in pyproject.toml: add a requirements.txt or your own Dockerfile"
        else:
            r["blocked"] = "no dependency list found (requirements.txt, pyproject.toml, uv.lock or poetry.lock)"
        return r
    kind = present[0]
    others = {"uv": "uv.lock", "poetry": "poetry.lock", "pip": "requirements.txt", "pyproject": "pyproject.toml"}
    ignored = [others[k] for k in present[1:] if k != "pyproject"]
    if ignored:
        r["warnings"].append(f"dependencies are installed from {others[kind]}; {', '.join(ignored)} is ignored")
    local = False
    if kind == "pip":
        names, local = requirements(root, "requirements.txt", set())
    elif kind == "poetry":
        pnames, plocal, python = poetry_deps(pyproject)
        names, local = {**proj_names, **pnames}, plocal or proj_local
        r["poetry_python"] = python
    else:
        if dynamic:
            r["blocked"] = "dependencies are dynamic in pyproject.toml: add a requirements.txt or your own Dockerfile"
            return r
        names, local = proj_names, proj_local
        if kind == "uv":
            sources = section(pyproject, "tool.uv.sources") or ""
            local = local or section(pyproject, "tool.uv.workspace") is not None or bool(
                re.search(r"\b(?:path|workspace)\s*=", sources))
    if local:
        r["warnings"].append("local dependencies (included files, paths or workspace members): the whole project is "
                             "copied before installing, so builds do not reuse the dependency cache")
    r.update(deps=kind, deps_files="." if local else DEPS_FILES[kind], install=INSTALLS[kind],
             poetry_setup=POETRY_SETUP if kind == "poetry" else "", names=names)
    return r


def python_version(root: Path, poetry_python: str | None) -> str | None:
    m = re.match(r"\s*(3\.\d+)", read(root / ".python-version"))
    if m:
        return m.group(1)
    m = re.search(r"(?:python_requires|requires-python)\s*=\s*['\"][^0-9]*(3\.\d+)",
                  read(root / "pyproject.toml") + read(root / "setup.py"))
    if m:
        return m.group(1)
    m = re.search(r"(3\.\d+)", poetry_python or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- Django


def module_file(root: Path, module: str) -> Path | None:
    base = root.joinpath(*module.split("."))
    for p in (base.with_suffix(".py"), base / "__init__.py"):
        if p.is_file():
            return p
    return None


def settings_sources(root: Path, module: str, seen: set | None = None) -> str:
    """Text of a settings module plus the modules it star-imports (`from .base import *`), recursively."""
    seen = seen if seen is not None else set()
    path = module_file(root, module)
    if not path or module in seen:
        return ""
    seen.add(module)
    text = read(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    out = [text]
    for dots, name in re.findall(r"^from\s+(\.*)([\w.]*)\s+import\s+\*", text, re.M):
        if dots:
            base = package.split(".")
            base = base[: len(base) - (len(dots) - 1)] if len(dots) > 1 else base
            target = ".".join([*base, name] if name else base)
        else:
            target = name
        if MODULE_PATH.fullmatch(target or ""):
            out.append(settings_sources(root, target, seen))
    return "\n".join(out)


def settings_module_in(text: str) -> tuple[str | None, bool]:
    """(module from os.environ.setdefault, whether the file assigns DJANGO_SETTINGS_MODULE instead)."""
    m = re.search(r"setdefault\(\s*['\"]DJANGO_SETTINGS_MODULE['\"]\s*,\s*['\"]([^'\"]+)['\"]", text)
    assigned = bool(re.search(r"environ\[\s*['\"]DJANGO_SETTINGS_MODULE['\"]\s*\]\s*=", text))
    return (m.group(1) if m else None), assigned


def too_old(spec: str, locked: str | None) -> bool:
    """Is every Django version allowed by the spec older than MIN_DJANGO? A lower bound alone never blocks."""
    if locked:
        return version_tuple(locked) < MIN_DJANGO
    s = spec.replace(" ", "")
    for v in re.findall(r"(?:===|==|~=)(\d+(?:\.\d+)*)", s) or ([s] if re.fullmatch(r"\d+(?:\.\d+)*", s) else []):
        return version_tuple(v) < MIN_DJANGO
    for v in re.findall(r"<=(\d+(?:\.\d+)*)", s):
        if version_tuple(v) < MIN_DJANGO:
            return True
    for v in re.findall(r"<(?!=)(\d+(?:\.\d+)*)", s):
        if version_tuple(v) <= MIN_DJANGO:
            return True
    m = re.match(r"\^(\d+)", s)  # Poetry caret: below the next major
    if m and (int(m.group(1)) + 1, 0) <= MIN_DJANGO:
        return True
    m = re.match(r"~(\d+)\.(\d+)", s)  # Poetry tilde: below the next minor
    return bool(m and (int(m.group(1)), int(m.group(2)) + 1) <= MIN_DJANGO)


def django_min_major(spec: str, locked: str | None) -> int | None:
    """Lowest major the project can get, when known (lock, pin or lower bound)."""
    if locked:
        return version_tuple(locked)[0]
    m = re.search(r"(?:===|==|~=|>=|>|\^|~)\s*(\d+)", spec) or re.fullmatch(r"\s*(\d+)(?:\.\d+)*\s*", spec)
    return int(m.group(1)) if m else None


def env_without_default(text: str) -> list[str]:
    names = set(re.findall(r"\benviron\[\s*['\"]([A-Z_][A-Z0-9_]*)['\"]\s*\](?!\s*=[^=])", text))
    names |= set(re.findall(r"\benv(?:\.(?:str|bool|int|float|list|tuple|dict|json|url|db|db_url|path))?"
                            r"\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]\s*\)", text))
    return sorted(names - {"DJANGO_SETTINGS_MODULE", *DJANGO_MANAGED_ENV})


def analyze_django(root: Path, r: dict, names: dict, files: list[Path]) -> dict:
    def blocked(reason: str) -> dict:
        r.update(template=None, warning_framework=reason)
        return r

    r.update(framework="django", port=8000)
    spec = names.get("django", (set(), ""))[1]
    locked = locked_version(root, "django")
    if too_old(spec, locked):
        return blocked(f"Django {locked or spec} is older than 4.2 (unsupported): upgrade Django or add your own Dockerfile")
    r["django_version"] = locked or spec or None
    if not (root / "manage.py").is_file():
        return blocked("manage.py is not at the repository root: add your own Dockerfile")
    manage = read(root / "manage.py")
    module, assigned = settings_module_in(manage)
    if assigned:
        return blocked("manage.py assigns DJANGO_SETTINGS_MODULE: use os.environ.setdefault(...) so the deployment "
                       "can choose its settings (a code change: only if the user asks)")
    if not module or not MODULE_PATH.fullmatch(module) or not module_file(root, module):
        return blocked("cannot find the settings module named in manage.py (DJANGO_SETTINGS_MODULE)")
    text = settings_sources(root, module)
    m = re.search(r"^WSGI_APPLICATION\s*=\s*['\"]([\w.]+)\.(\w+)['\"]", text, re.M)
    wsgi_mod, wsgi_attr = (m.group(1), m.group(2)) if m else (f"{module.split('.')[0]}.wsgi", "application")
    wsgi_text = read(module_file(root, wsgi_mod) or Path("/nonexistent"))
    if not wsgi_text or not WSGI_MODULE.fullmatch(f"{wsgi_mod}:{wsgi_attr}"):
        return blocked(f"cannot find the WSGI module ({wsgi_mod}.py): add your own Dockerfile")
    w_module, w_assigned = settings_module_in(wsgi_text)
    if w_assigned:
        return blocked(f"{wsgi_mod.replace('.', '/')}.py assigns DJANGO_SETTINGS_MODULE: use os.environ.setdefault(...) "
                       "so the deployment can choose its settings (a code change: only if the user asks)")
    if w_module and w_module != module:
        if not MODULE_PATH.fullmatch(w_module) or not module_file(root, w_module):
            return blocked(f"cannot find the settings module named in {wsgi_mod}.py")
        r["warning_settings"] = (f"production uses {w_module} (named in the WSGI file), not {module} (manage.py)")
        module = w_module
        text = settings_sources(root, module)
    r.update(template="python-django", module=f"{wsgi_mod}:{wsgi_attr}", settings_module=module, migrations=True)

    # static files
    staticfiles = "django.contrib.staticfiles" in text
    backends = re.findall(r"STATICFILES_STORAGE\s*=\s*['\"]([\w.]+)", text)
    sf = re.search(r"['\"]staticfiles['\"]\s*:\s*\{[^}]*?['\"]BACKEND['\"]\s*:\s*['\"]([\w.]+)", text, re.S)
    backends += [sf.group(1)] if sf else []
    remote = [b for b in backends if not b.startswith(("django.", "whitenoise."))]
    if remote:
        r["warning_static"] = f"static files go to remote storage ({remote[0]}): run collectstatic yourself"
    r["collectstatic"] = staticfiles and not remote

    # database
    if "django.db.backends.mysql" in text:
        r["db_engine"] = "mysql"
    elif "DATABASE_URL" in text or "dj_database_url" in text or re.search(r"\benv\.db(?:_url)?\(", text) \
            or "django.db.backends.postgresql" in text:
        r["db_engine"] = "postgresql"
    elif "django.db.backends.sqlite3" in text:
        r["db_engine"] = "sqlite"
        r["warning_sqlite"] = ("SQLite would lose its data on every deploy: a PostgreSQL database is created and Django "
                               "is pointed to it; data in db.sqlite3 is not copied")
    else:
        r["db_engine"] = "postgresql"

    r["extra_packages"] = ["whitenoise"] if r["collectstatic"] and "whitenoise" not in names else []

    # warnings
    if {"channels", "daphne"} & set(names) or re.search(r"^ASGI_APPLICATION\s*=", text, re.M):
        r["warning_asgi"] = "websockets / ASGI will not work: the app is served with gunicorn (WSGI)"
    if "celery" in names:
        r["warning_celery"] = "uses Celery: the worker is not deployed (only the web app)"
    models = any(f.name == "models.py" and re.search(r"\b(?:FileField|ImageField)\(", read(f)) for f in files)
    if models or re.search(r"^MEDIA_ROOT\s*=", text, re.M):
        r["warning_media"] = "uploaded files (MEDIA_ROOT) are lost on every deploy: the container has no persistent storage"
    needed = env_without_default(text)
    if needed:
        r["warning_import_env"] = ("settings read " + ", ".join(needed) + " with no default when imported, also by "
                                   "collectstatic at build time: give them a default or the build fails")
    if re.search(r"^SECRET_KEY\s*=\s*['\"]", text, re.M):
        r["warning_secret_key"] = ("hard-coded SECRET_KEY: production uses DJANGO_SECRET_KEY instead; if the repository "
                                   "is public the committed key is already exposed (harmless only if it is the "
                                   "development key)")

    # checks
    routes = []
    static_url = re.search(r"^STATIC_URL\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
    root_urlconf = re.search(r"^ROOT_URLCONF\s*=\s*['\"]([\w.]+)['\"]", text, re.M)
    urls = read(module_file(root, root_urlconf.group(1)) or Path("/nonexistent")) if root_urlconf else ""
    admin = re.search(r"path\(\s*['\"]([\w/-]*)['\"]\s*,\s*admin\.site\.urls", urls)
    if "django.contrib.admin" in text and admin:
        prefix = admin.group(1).strip("/")
        routes.append(f"/{prefix}/login/" if prefix else "/login/")
        if r["collectstatic"] and static_url and "://" not in static_url.group(1):
            routes.append("/" + static_url.group(1).strip("/") + "/admin/css/base.css")
    r["check_routes"] = routes
    r["runtime_env"] = {"DJANGO_ALLOWED_HOSTS": "{domain}"}
    r["generated_env"] = ["DJANGO_SECRET_KEY"]
    r["managed_env"] = list(DJANGO_MANAGED_ENV)  # DATABASE_URL: set by create-postgres, or by the user (external)
    r["local_env"] = ["DJANGO_SECRET_KEY=local-check-only", "DJANGO_INSECURE_COOKIES=1"]
    if r["db_engine"] == "sqlite":
        r["local_env"].append("DATABASE_URL=sqlite:////tmp/local-check.sqlite3")
    return r


# ---------------------------------------------------------------- entry points


def is_django(root: Path) -> bool:
    """manage.py at the root and django among the Python dependencies (wins over a package.json)."""
    if not (root / "manage.py").is_file():
        return False
    src = deps_source(root)
    return "django" in src.get("names", {}) or bool(re.search(r"^\s*django\b", read(root / "requirements.txt"), re.M | re.I))


def analyze_python(root: Path, files: list[Path]) -> dict:
    r: dict = {"language": "python"}
    src = deps_source(root)
    names = src.get("names", {})
    for i, w in enumerate(src["warnings"]):
        r[f"warning_deps_{i}"] = w
    version = python_version(root, src.get("poetry_python"))
    r["python_version"] = version or "3.12"
    if "blocked" in src:
        r.update(framework="python", template=None, warning_framework=src["blocked"])
        return r
    r.update(deps=src["deps"], deps_files=src["deps_files"], install=src["install"], poetry_setup=src["poetry_setup"])

    module = None
    for f in files:
        if f.suffix == ".py" and (f.parent == root or f.parent.name in {"app", "src"}):
            m = re.search(r"^(\w+)\s*=\s*(FastAPI|Flask)\(", read(f), re.M)
            if m:
                module = ".".join(f.relative_to(root).with_suffix("").parts) + ":" + m.group(1)
                break
    if "django" in names:
        analyze_django(root, r, names, files)
        major = django_min_major(names["django"][1], locked_version(root, "django"))
        if r.get("template") and major and major >= 6 and version_tuple(r["python_version"]) < (3, 12):
            r["warning_python"] = f"Django {major} needs Python 3.12 or newer: the image uses 3.12 instead of {r['python_version']}"
            r["python_version"] = "3.12"
    elif "fastapi" in names:
        r.update(framework="fastapi", template="python-fastapi", port=8000, module=module or "main:app")
    elif "flask" in names:
        r.update(framework="flask", template="python-flask", port=8000, module=module or "app:app")
    else:
        r.update(framework="python", template=None, warning_framework="unrecognized web framework")
    if r.get("template"):
        needs_driver = r["framework"] == "django" and r.get("db_engine") in ("postgresql", "sqlite")
        driver = postgres_driver(names, needs_driver)
        if driver is None:
            r.update(template=None, warning_framework=(
                "psycopg2 must be built from source and the image has no compiler: use psycopg2-binary or "
                "psycopg[binary] (a code change: only if the user asks)"))
            return r
        r["extra_packages"] = BASE_PACKAGES[r["framework"]] + r.get("extra_packages", []) + driver
    return r


def postgres_driver(names: dict, required: bool) -> list[str] | None:
    """Extra package for PostgreSQL on a slim image (no libpq, no compiler); None when it cannot be built."""
    if "psycopg2" in names:
        return None
    pg = names.get("psycopg")
    if pg is not None and not pg[0] & {"binary", "c"}:
        return ["psycopg[binary]"]  # plain psycopg needs the system libpq
    if required and pg is None and "psycopg2-binary" not in names:
        return ["psycopg[binary]"]
    return []
