"""Tests de los scripts de la skill desplegar-coolify (sin red ni Docker: la API se simula)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "desplegar-coolify" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analizar  # noqa: E402
import coolify  # noqa: E402
import preparar  # noqa: E402

# ------------------------------------------------------------------ utilidades


def crear(raiz: Path, ficheros: dict[str, str]) -> Path:
    for ruta, contenido in ficheros.items():
        p = raiz / ruta
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido)
    return raiz


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Configuración aislada en una carpeta temporal y API simulada."""
    monkeypatch.setattr(coolify, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(coolify, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(coolify, "REGISTRO", tmp_path / "apps.json")
    coolify.escribir_json(coolify.CONFIG, {"url": "http://coolify.test:8000", "dominio_base": "ejemplo.org",
                                           "server_uuid": "srv", "github_app_uuid": "gh",
                                           "subdominios_reservados": ["hooks"]})
    return tmp_path


# ------------------------------------------------------------------ coolify.py


def test_enmascarar_oculta_contrasenas_y_tokens():
    assert coolify.enmascarar("postgres://u:secreta@db:5432/x") == "postgres://u:****@db:5432/x"
    assert "abc123" not in coolify.enmascarar("Authorization: Bearer abc123")


def test_dominio_libre(config, monkeypatch):
    monkeypatch.setattr(coolify, "_apps", lambda: [{"fqdn": "https://tienda.ejemplo.org"}])
    libre = lambda h: coolify.cmd_dominio_libre(argparse.Namespace(host=h))  # noqa: E731
    assert libre("blog")["libre"] is True
    assert libre("blog")["host"] == "blog.ejemplo.org"
    assert libre("tienda")["libre"] is False            # en uso
    assert libre("hooks")["libre"] is False             # reservado
    assert libre("Mal_Nombre")["libre"] is False        # nombre no válido
    assert libre("algo.otrodominio.com")["libre"] is False


def test_variables_fichero_marca_publicas_y_secretas(config, monkeypatch, tmp_path):
    llamadas = []
    monkeypatch.setattr(coolify, "_poner_variable",
                        lambda app, k, v, secreta: llamadas.append((k, v, secreta)) or {"clave": k, "accion": "creada"})
    f = crear(tmp_path, {"vars.env": "# comentario\nDATABASE_URL=postgres://a:b@c/d\nexport NEXT_PUBLIC_URL='https://x'\n\n"})
    r = coolify.cmd_variables_fichero(argparse.Namespace(app="uuid-app", fichero=str(f / "vars.env")))
    assert r["ok"]
    assert ("DATABASE_URL", "postgres://a:b@c/d", True) in llamadas
    assert ("NEXT_PUBLIC_URL", "https://x", False) in llamadas
    assert "postgres://a:b@c/d" not in json.dumps(r)    # los valores nunca salen en la respuesta


def test_retirar_y_rollback_exigen_confirmacion(config):
    with pytest.raises(coolify.Error):
        coolify.cmd_retirar(argparse.Namespace(app="x", confirmado=False, con_bd=False, con_proyecto=False))
    with pytest.raises(coolify.Error):
        coolify.cmd_rollback(argparse.Namespace(app="x", confirmado=False, imagen=None))


def test_registro_resuelve_nombres(config):
    coolify.guardar_en_registro("tienda", {"app_uuid": "u-123"})
    assert coolify.resolver_app("tienda") == "u-123"
    assert coolify.resolver_app("otro-uuid") == "otro-uuid"


# ------------------------------------------------------------------ analizar.py


def test_fastapi(tmp_path):
    crear(tmp_path, {"requirements.txt": "fastapi\npsycopg[binary]\n",
                     "main.py": "import os\nfrom fastapi import FastAPI\napp = FastAPI()\nos.getenv('DATABASE_URL')\n"})
    r = analizar.analizar(tmp_path)
    assert r["desplegable"]
    assert r["stack"]["plantilla"] == "python-fastapi"
    assert r["stack"]["modulo"] == "main:app"
    assert "postgresql" in r["bases_de_datos"]
    assert "DATABASE_URL" in r["variables"]["en_codigo"]


def test_angular_antiguo_usa_node_16(tmp_path):
    crear(tmp_path, {
        "package.json": json.dumps({"dependencies": {"@angular/core": "~13.0.0"}, "scripts": {"build": "ng build"}}),
        "package-lock.json": "{}",
        "angular.json": json.dumps({"projects": {"tienda": {"architect": {"build": {
            "builder": "@angular-devkit/build-angular:browser", "options": {"outputPath": "dist/tienda"}}}}}}),
    })
    s = analizar.analizar(tmp_path)["stack"]
    assert (s["plantilla"], s["node_version"], s["build_dir"], s["puerto"]) == ("spa-nginx", "16", "dist/tienda", 80)


def test_angular_moderno_publica_en_browser(tmp_path):
    crear(tmp_path, {
        "package.json": json.dumps({"dependencies": {"@angular/core": "^19.0.0"}}),
        "angular.json": json.dumps({"projects": {"web": {"architect": {"build": {
            "builder": "@angular/build:application", "options": {"outputPath": "dist/web"}}}}}}),
    })
    assert analizar.analizar(tmp_path)["stack"]["build_dir"] == "dist/web/browser"


def test_monorepo_bloquea(tmp_path):
    crear(tmp_path, {"nx.json": "{}", "package.json": json.dumps({"dependencies": {"@angular/core": "21"}})})
    r = analizar.analizar(tmp_path)
    assert not r["desplegable"]
    assert any("monorepo" in b for b in r["bloqueos"])


def test_secretos_bloquean_sin_mostrar_valor(tmp_path):
    token = "ghp_" + "a" * 36
    crear(tmp_path, {"index.html": "<h1>hola</h1>", ".env": "CLAVE=valor-real\n", "config.js": f"const t = '{token}'\n",
                     ".env.example": "CLAVE=\n"})
    r = analizar.analizar(tmp_path)
    tipos = {(s["fichero"], s["tipo"]) for s in r["secretos"]}
    assert (".env", "fichero sensible") in tipos
    assert ("config.js", "token de GitHub") in tipos
    assert not any(s["fichero"] == ".env.example" for s in r["secretos"])
    assert token not in json.dumps(r)
    assert not r["desplegable"]


def test_supabase_no_pide_postgres_propio(tmp_path):
    crear(tmp_path, {"package.json": json.dumps({"dependencies": {"next": "16", "@supabase/supabase-js": "2"}}),
                     "src/x.ts": "process.env.NEXT_PUBLIC_SUPABASE_URL"})
    r = analizar.analizar(tmp_path)
    assert r["stack"]["plantilla"] == "nextjs"
    assert "postgresql" not in r["bases_de_datos"]


def test_pago_sin_login_avisa(tmp_path):
    crear(tmp_path, {"requirements.txt": "flask\nopenai\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
    r = analizar.analizar(tmp_path)
    assert r["stack"]["plantilla"] == "python-flask"
    assert any("servicios de pago" in a for a in r["avisos"])


def test_dockerfile_existente_respeta_su_puerto(tmp_path):
    crear(tmp_path, {"requirements.txt": "fastapi\n", "main.py": "app = FastAPI()\n", "Dockerfile": "FROM x\nEXPOSE 9000\n"})
    s = analizar.analizar(tmp_path)["stack"]
    assert s["dockerfile_existente"] and s["puerto"] == 9000 and s["plantilla"] is None


# ------------------------------------------------------------------ preparar.py


def test_rellenar_detecta_valores_que_faltan():
    assert preparar.rellenar("FROM node:{{NODE_VERSION}}", {"NODE_VERSION": "22"}) == "FROM node:22"
    with pytest.raises(ValueError):
        preparar.rellenar("EXPOSE {{PUERTO}}", {})


def test_todas_las_plantillas_se_rellenan_con_los_valores_por_defecto():
    v = preparar.valores({"stack": {"puerto": 8000}}, {})
    for p in (SCRIPTS.parent / "plantillas").glob("*.Dockerfile"):
        assert "{{" not in preparar.rellenar(p.read_text(), v), p.name
