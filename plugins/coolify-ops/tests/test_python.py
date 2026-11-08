"""Python projects in analyze.py / prepare.py: dependency sources (pip, uv, Poetry, pyproject) and Django.
Offline: files in tmp_path only; nothing is installed or executed except the generated settings overlay, which is
imported with a fake settings module (Django itself is not needed)."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "deploy-app" / "scripts"
TEMPLATES = SCRIPTS.parent / "templates"
sys.path.insert(0, str(SCRIPTS))

import analyze  # noqa: E402
import coolify  # noqa: E402
import prepare  # noqa: E402
import pystack  # noqa: E402

APP_UUID = "k" * 24

MANAGE = """import os, sys
def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{module}')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
"""
WSGI = """import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{module}')
application = get_wsgi_application()
"""
SETTINGS = """from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = 'django-insecure-abc'
DEBUG = True
ALLOWED_HOSTS = []
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.staticfiles', 'shop']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware']
ROOT_URLCONF = 'mysite.urls'
WSGI_APPLICATION = 'mysite.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
STATIC_URL = 'static/'
"""
URLS = """from django.contrib import admin
from django.urls import path
urlpatterns = [path('admin/', admin.site.urls)]
"""


def make(root: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


def django_project(root: Path, extra: dict[str, str] | None = None, settings: str = SETTINGS,
                   reqs: str | None = "Django>=5.2\n") -> dict:
    files = {"manage.py": MANAGE.format(module="mysite.settings"), "mysite/__init__.py": "",
             "mysite/settings.py": settings, "mysite/wsgi.py": WSGI.format(module="mysite.settings"),
             "mysite/urls.py": URLS}
    if reqs is not None:
        files["requirements.txt"] = reqs
    files.update(extra or {})
    make(root, files)
    return analyze.analyze(root)


def blocked(r: dict, words: str) -> None:
    assert not r["deployable"], r
    assert r["stack"]["template"] is None
    assert words in r["stack"]["warning_framework"]


# ------------------------------------------------------------------ dependency sources


@pytest.mark.parametrize("files, deps, deps_files", [
    ({"uv.lock": "", "pyproject.toml": '[project]\nname = "x"\ndependencies = ["fastapi"]\n'}, "uv", "pyproject.toml uv.lock"),
    ({"poetry.lock": "", "pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.11"\nfastapi = "^0.110"\n'},
     "poetry", "pyproject.toml poetry.lock"),
    ({"requirements.txt": "fastapi==0.110\n"}, "pip", "requirements.txt"),
    ({"pyproject.toml": '[project]\nname = "x"\ndependencies = [\n  "fastapi>=0.100",  # api\n]\n'}, "pyproject",
     "pyproject.toml"),
])
def test_dependency_sources(tmp_path, files, deps, deps_files):
    make(tmp_path, {**files, "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"})
    s = analyze.analyze(tmp_path)["stack"]
    assert (s["template"], s["deps"], s["deps_files"]) == ("python-fastapi", deps, deps_files)
    assert s["install"] == pystack.INSTALLS[deps]
    assert bool(s["poetry_setup"]) == (deps == "poetry")


def test_pyproject_only_fastapi_renders_without_requirements(tmp_path):
    make(tmp_path, {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["fastapi"]\n', "uv.lock": "",
                    "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"})
    out = prepare.render((TEMPLATES / "python-fastapi.Dockerfile").read_text(), prepare.values(analyze.analyze(tmp_path), {}))
    assert "requirements.txt" not in out and "COPY pyproject.toml uv.lock ./" in out
    assert '"uvicorn[standard]"' in out and "HEALTHCHECK --interval=5s" in out


@pytest.mark.parametrize("files, words", [
    ({"Pipfile": "[packages]\nflask = '*'\n"}, "Pipfile"),
    ({"pyproject.toml": '[project]\nname = "x"\ndynamic = ["dependencies"]\n'}, "dynamic"),
])
def test_unsupported_dependency_sources_block(tmp_path, files, words):
    make(tmp_path, files)
    blocked(analyze.analyze(tmp_path), words)


def test_second_dependency_file_is_reported_as_ignored(tmp_path):
    make(tmp_path, {"poetry.lock": "", "requirements.txt": "flask\n",
                    "pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.11"\nflask = "*"\n'})
    r = analyze.analyze(tmp_path)
    assert r["stack"]["deps"] == "poetry"
    assert any("requirements.txt is ignored" in w for w in r["warnings"])


@pytest.mark.parametrize("files", [
    {"requirements.txt": "-r requirements/base.txt\n", "requirements/base.txt": "flask\n"},
    {"requirements.txt": "-e .\nflask\n"},
    {"uv.lock": "", "pyproject.toml": '[project]\nname = "x"\ndependencies = ["flask", "lib"]\n'
                                      '[tool.uv.sources]\nlib = { path = "lib" }\n'},
    {"poetry.lock": "", "pyproject.toml": '[tool.poetry.dependencies]\nflask = "*"\nlib = { path = "lib", develop = true }\n'},
])
def test_local_dependencies_copy_the_whole_project(tmp_path, files):
    make(tmp_path, files)
    r = analyze.analyze(tmp_path)
    assert r["stack"]["framework"] == "flask"  # names from included files are read too
    assert r["stack"]["deps_files"] == "."
    assert any("local dependencies" in w for w in r["warnings"])


def test_dependency_names_are_exact(tmp_path):
    make(tmp_path, {"requirements.txt": "django-environ\nflask\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
    assert analyze.analyze(tmp_path)["stack"]["framework"] == "flask"


def test_python_version_sources(tmp_path):
    make(tmp_path, {"poetry.lock": "", "pyproject.toml": '[tool.poetry.dependencies]\npython = "~3.10"\nflask = "*"\n'})
    assert analyze.analyze(tmp_path)["stack"]["python_version"] == "3.10"
    make(tmp_path, {".python-version": "3.13.1\n"})
    assert analyze.analyze(tmp_path)["stack"]["python_version"] == "3.13"


@pytest.mark.parametrize("reqs, ok", [("psycopg\n", True), ("psycopg2\n", False), ("psycopg[binary]\n", True)])
def test_postgres_driver_on_slim_images(tmp_path, reqs, ok):
    make(tmp_path, {"requirements.txt": "fastapi\n" + reqs, "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"})
    r = analyze.analyze(tmp_path)
    if ok:
        assert r["stack"]["extra_packages"].count("psycopg[binary]") == (reqs == "psycopg\n")
    else:
        blocked(r, "psycopg2-binary")


# ------------------------------------------------------------------ Django


def test_startproject(tmp_path):
    r = django_project(tmp_path)
    s = r["stack"]
    assert r["deployable"], r["blockers"]
    assert (s["template"], s["module"], s["settings_module"], s["port"]) == ("python-django", "mysite.wsgi:application",
                                                                            "mysite.settings", 8000)
    assert s["db_engine"] == "sqlite" and r["databases"] == ["postgresql"]
    assert s["check_routes"] == ["/admin/login/", "/static/admin/css/base.css"]
    assert "DATABASE_URL=sqlite:////tmp/local-check.sqlite3" in s["local_env"]
    assert s["extra_packages"] == ["gunicorn", "whitenoise", "psycopg[binary]"]
    assert s["collectstatic"] and s["runtime_env"] == {"DJANGO_ALLOWED_HOSTS": "{domain}"}
    assert any("SECRET_KEY" in w for w in r["warnings"]) and any("SQLite" in w for w in r["warnings"])


def test_managed_variables_are_never_asked(tmp_path):
    settings = SETTINGS + "import os\nX = os.environ.get('DJANGO_SECRET_KEY')\nY = os.getenv('STRIPE_KEY')\nZ = os.getenv('DATABASE_URL')\n"
    r = django_project(tmp_path, settings=settings)
    assert r["env_vars"]["in_code"] == ["DATABASE_URL", "STRIPE_KEY"]  # DATABASE_URL: asked only for an external database
    assert "DJANGO_SECRET_KEY" in r["env_vars"]["managed"] and "DATABASE_URL" not in r["env_vars"]["managed"]


def test_django_with_package_json(tmp_path):
    make(tmp_path, {"package.json": json.dumps({"devDependencies": {"vite": "^7"}, "scripts": {"build": "vite build"}})})
    blocked(django_project(tmp_path), "frontend build")


def test_django_with_package_json_without_build(tmp_path):
    make(tmp_path, {"package.json": json.dumps({"devDependencies": {"tailwindcss": "^4"}})})
    r = django_project(tmp_path)
    assert r["stack"]["template"] == "python-django"
    assert any("package.json is ignored" in w for w in r["warnings"])


@pytest.mark.parametrize("file", ["manage.py", "mysite/wsgi.py"])
def test_assigned_settings_module_blocks(tmp_path, file):
    text = "import os\nos.environ['DJANGO_SETTINGS_MODULE'] = 'mysite.settings'\n"
    blocked(django_project(tmp_path, {file: text + (MANAGE if file == "manage.py" else WSGI).format(module="mysite.settings")}),
            "os.environ.setdefault")


def test_wsgi_settings_win_over_manage(tmp_path):
    settings = SETTINGS.replace("mysite.", "config.")
    files = {"manage.py": MANAGE.format(module="config.settings.local"), "config/__init__.py": "",
             "config/settings/__init__.py": "", "config/settings/base.py": settings,
             "config/settings/local.py": "from .base import *  # noqa\nDEBUG = True\n",
             "config/settings/production.py": "from .base import *  # noqa\nfrom os import environ\nK = environ['SENTRY_DSN']\n",
             "config/wsgi.py": WSGI.format(module="config.settings.production"), "config/urls.py": URLS,
             "requirements.txt": "django==5.2.4\n"}
    make(tmp_path, files)
    r = analyze.analyze(tmp_path)
    s = r["stack"]
    assert (s["settings_module"], s["module"]) == ("config.settings.production", "config.wsgi:application")
    assert "SENTRY_DSN" in s["warning_import_env"] and "config.settings.production" in s["warning_settings"]
    assert s["collectstatic"]  # INSTALLED_APPS read through `from .base import *`


@pytest.mark.parametrize("spec, lock, ok", [(">=3.2,<5", None, True), ("==3.2.25", None, False), ("<4.2", None, False),
                                            ("^3.2", None, False), (">=3.2", "4.2.16", True), (">=4", "4.1.0", False)])
def test_django_versions(tmp_path, spec, lock, ok):
    extra = {}
    if lock:
        extra = {"uv.lock": f'[[package]]\nname = "django"\nversion = "{lock}"\n',
                 "pyproject.toml": f'[project]\nname = "x"\ndependencies = ["django{spec}"]\n'}
    r = django_project(tmp_path, extra, reqs=None if lock else f"django{spec}\n")
    if ok:
        assert r["stack"]["template"] == "python-django"
    else:
        blocked(r, "older than 4.2")


def test_django_6_needs_python_3_12(tmp_path):
    r = django_project(tmp_path, {"pyproject.toml": '[project]\nrequires-python = ">=3.10"\n'}, reqs="django>=6.0\n")
    assert r["stack"]["python_version"] == "3.12" and "warning_python" in r["stack"]


def test_django_project_layout_problems(tmp_path):
    make(tmp_path, {"requirements.txt": "django\n", "app.py": ""})
    blocked(analyze.analyze(tmp_path), "manage.py is not at the repository root")
    r = django_project(tmp_path / "b", {"manage.py": MANAGE.format(module="missing.settings")})
    blocked(r, "settings module")


def test_django_warnings_and_static(tmp_path):
    settings = (SETTINGS.replace("'django.contrib.staticfiles', ", "") + "MEDIA_ROOT = BASE_DIR / 'media'\n"
                "ASGI_APPLICATION = 'mysite.asgi.application'\n")
    r = django_project(tmp_path, settings=settings, reqs="django\ncelery\n")
    s = r["stack"]
    assert not s["collectstatic"] and "whitenoise" not in s["extra_packages"]
    assert s["check_routes"] == ["/admin/login/"]  # no static check without staticfiles
    assert {"warning_media", "warning_asgi", "warning_celery"} <= set(s)


def test_remote_static_storage_skips_collectstatic(tmp_path):
    settings = SETTINGS + "STORAGES = {'staticfiles': {'BACKEND': 'storages.backends.s3.S3Storage'}}\n"
    s = django_project(tmp_path, settings=settings)["stack"]
    assert not s["collectstatic"] and "remote storage" in s["warning_static"]


def test_custom_admin_and_static_urls(tmp_path):
    urls = "from django.conf import settings\nfrom django.contrib import admin\nfrom django.urls import path\n" \
           "urlpatterns = [path(settings.ADMIN_URL, admin.site.urls)]\n"
    assert django_project(tmp_path, {"mysite/urls.py": urls})["stack"]["check_routes"] == []
    s = django_project(tmp_path / "b", {"mysite/urls.py": URLS.replace("'admin/'", "'backoffice/'")},
                       settings=SETTINGS.replace("'static/'", "'/assets/'"))["stack"]
    assert s["check_routes"] == ["/backoffice/login/", "/assets/admin/css/base.css"]


def test_postgres_project_has_no_sqlite_local_check(tmp_path):
    settings = SETTINGS.replace("django.db.backends.sqlite3", "django.db.backends.postgresql")
    s = django_project(tmp_path, settings=settings, reqs="django\npsycopg[binary]\n")["stack"]
    assert s["db_engine"] == "postgresql" and not any(e.startswith("DATABASE_URL") for e in s["local_env"])
    assert "psycopg[binary]" not in s["extra_packages"]


def test_poetry_django_project(tmp_path):
    pyproject = '[tool.poetry.dependencies]\npython = "^3.12"\nDjango = "^5.2"\npsycopg = {extras = ["binary"], version = "^3.2"}\n'
    r = django_project(tmp_path, {"pyproject.toml": pyproject, "poetry.lock": ""}, reqs=None)
    assert r["stack"]["deps"] == "poetry" and "psycopg[binary]" not in r["stack"]["extra_packages"]


# ------------------------------------------------------------------ prepare.py


def test_django_files_render(tmp_path):
    django_project(tmp_path)
    analysis = analyze.analyze(tmp_path)
    v = prepare.values(analysis, {})
    docker = prepare.render((TEMPLATES / "python-django.Dockerfile").read_text(), v)
    assert "collectstatic --noinput" in docker and "DJANGO_SETTINGS_MODULE=coolify_settings" in docker
    assert '"gunicorn" "whitenoise" "psycopg[binary]"' in docker and "mysite.wsgi:application" in docker
    assert "HEALTHCHECK --interval=5s" in docker and "{{" not in docker
    overlay = prepare.render((TEMPLATES / "django-settings.py.tmpl").read_text(), v)
    assert "from mysite.settings import *" in overlay and "{{" not in overlay


@pytest.mark.parametrize("var", ["SETTINGS_MODULE=a;b", "MODULE=x y:app", "INSTALL=rm -rf /", "DEPS_FILES=../x",
                                 'EXTRA_PACKAGES="a" ; b', "PYTHON_VERSION=3.12 && x", "COLLECTSTATIC=RUN x",
                                 "PORT=8000; x", "PORT=80 80"])
def test_unsafe_python_values_are_rejected(tmp_path, var):
    django_project(tmp_path)
    with pytest.raises(ValueError):
        prepare.values(analyze.analyze(tmp_path), dict([var.split("=", 1)]))


def test_prepare_writes_the_overlay(tmp_path, monkeypatch, capsys):
    django_project(tmp_path)
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(tmp_path)])
    prepare.main()
    out = json.loads(capsys.readouterr().out)
    assert set(out["created"]) == {"Dockerfile", ".dockerignore", "coolify_settings.py"}


# ------------------------------------------------------------------ the generated overlay


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    """Render coolify_settings.py over a fake settings module and import it with a given environment."""
    def load(env: dict, settings: str = "MIDDLEWARE = ['django.middleware.security.SecurityMiddleware']\n"
                                        "INSTALLED_APPS = ['django.contrib.staticfiles']\n"):
        make(tmp_path, {"fakesite/__init__.py": "", "fakesite/settings.py": settings,
                        "coolify_settings.py": prepare.render((TEMPLATES / "django-settings.py.tmpl").read_text(),
                                                              {"SETTINGS_MODULE": "fakesite.settings"}),
                        "whitenoise/__init__.py": ""})
        for k in ("DJANGO_SECRET_KEY", "DJANGO_DEBUG", "DJANGO_ALLOWED_HOSTS", "DJANGO_INSECURE_COOKIES", "DATABASE_URL"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.syspath_prepend(str(tmp_path))
        for name in ("coolify_settings", "fakesite.settings", "fakesite", "whitenoise"):
            sys.modules.pop(name, None)
        return importlib.import_module("coolify_settings")
    return load


def test_overlay_defaults(overlay):
    s = overlay({"DJANGO_SECRET_KEY": "k", "DJANGO_ALLOWED_HOSTS": "shop.example.org", "DJANGO_INSECURE_COOKIES": "0"})
    assert s.SECRET_KEY == "k" and s.DEBUG is False and s.SECURE_SSL_REDIRECT is False
    assert s.ALLOWED_HOSTS == ["shop.example.org", "localhost", "127.0.0.1"]
    assert s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE  # «0» never turns secure cookies off
    assert s.MIDDLEWARE == ["django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware"]
    assert s.STATIC_ROOT.endswith("staticfiles") and "django" in s.LOGGING["loggers"]
    assert not hasattr(s, "DATABASES")  # DATABASE_URL unset: the project's DATABASES (none here) stay


def test_overlay_needs_the_secret_key(overlay):
    with pytest.raises(KeyError):
        overlay({})


def test_overlay_database_urls(overlay):
    s = overlay({"DJANGO_SECRET_KEY": "k", "DATABASE_URL": "postgres://app:p%40ss@db1:5432/app"})
    assert s.DATABASES["default"] == {"ENGINE": "django.db.backends.postgresql", "NAME": "app", "USER": "app",
                                      "PASSWORD": "p@ss", "HOST": "db1", "PORT": "5432"}
    assert s.database_from_url("sqlite:////tmp/x.sqlite3")["NAME"] == "/tmp/x.sqlite3"
    with pytest.raises(ValueError) as e:
        s.database_from_url("mysql://u:secret@h/db")
    assert "secret" not in str(e.value)


def test_overlay_middleware_once(overlay):
    s = overlay({"DJANGO_SECRET_KEY": "k"})
    assert s.with_whitenoise(["a", "whitenoise.middleware.WhiteNoiseMiddleware"]) == ["a", "whitenoise.middleware.WhiteNoiseMiddleware"]
    assert s.with_whitenoise(["a"])[0] == "whitenoise.middleware.WhiteNoiseMiddleware"


# ------------------------------------------------------------------ coolify.py env-generate


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(coolify, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(coolify, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(coolify, "REGISTRY", tmp_path / "apps.json")
    monkeypatch.setattr(coolify.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    coolify.write_json(coolify.CONFIG, {"url": "http://coolify.test:8000", "base_domain": "example.org",
                                        "server_uuid": "srv", "github_app_uuid": "gh", "reserved_subdomains": []})
    return tmp_path


def test_env_generate_creates_only_missing_keys_and_never_prints_values(config, monkeypatch, capsys):
    sent = []

    def fake(method, path, body=None, query=None):
        if method == "GET":
            return [{"key": "OLD_SECRET", "is_preview": False}]
        sent.append(body)
        return {}
    monkeypatch.setattr(coolify, "api", fake)
    r = coolify.cmd_env_generate(argparse.Namespace(app=APP_UUID, keys=["DJANGO_SECRET_KEY", "OLD_SECRET"]))
    assert r == {"ok": True, "env_generated": {"DJANGO_SECRET_KEY": "created", "OLD_SECRET": "kept"}, "env_errors": []}
    assert len(sent) == 1 and len(sent[0]["value"]) >= 50 and sent[0]["is_shown_once"] and not sent[0]["is_buildtime"]
    assert sent[0]["value"] not in json.dumps(r)


def test_create_app_generated_env_failure_keeps_the_uuid(config, monkeypatch):
    def fake(method, path, body=None, query=None):
        if path == "/applications" or method == "GET":
            return []
        if path.endswith("/envs"):
            raise coolify.Error("HTTP 500")
        return {"uuid": APP_UUID}
    monkeypatch.setattr(coolify, "api", fake)
    a = argparse.Namespace(project="p", repo="o/r", branch="main", port="8000", domain="web", name="web",
                           environment="production", cpus=None, memory=None, dockerfile=None, base_dir=None,
                           no_autodeploy=False, env_domain=None, env_generate=["DJANGO_SECRET_KEY"])
    r = coolify.cmd_create_app(a)
    assert r["ok"] and r["app_uuid"] == APP_UUID and r["env_errors"][0]["key"] == "DJANGO_SECRET_KEY"


def test_verify_accept_4xx():
    import verify
    assert verify.answered_ok(404, accept_4xx=True) and not verify.answered_ok(404)
    assert not verify.answered_ok(502, accept_4xx=True)
    assert not verify.answered_ok(400, accept_4xx=True)  # Django: domain not in ALLOWED_HOSTS
