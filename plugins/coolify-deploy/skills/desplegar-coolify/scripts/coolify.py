#!/usr/bin/env python3
"""Cliente mínimo de la API de Coolify v4 para la skill «desplegar-coolify».

Solo biblioteca estándar. Toda la salida es JSON (una línea) para que Claude la lea.
Nunca imprime el token ni contraseñas: los valores sensibles salen enmascarados.

Configuración (fuera del repo):
  ~/.config/coolify-deploy/config.json   url, server_uuid, github_app_uuid, dominio_base, …
  Token: variable COOLIFY_TOKEN o Llavero de macOS (servicio «coolify-api-token»).

Uso:  coolify.py <orden> [opciones]      (coolify.py --help para la lista)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("COOLIFY_DEPLOY_HOME", Path.home() / ".config" / "coolify-deploy"))
CONFIG = CONFIG_DIR / "config.json"
REGISTRO = CONFIG_DIR / "apps.json"
SERVICIO_LLAVERO = "coolify-api-token"
ESTADOS_FINALES = {"finished", "failed", "cancelled-by-user", "cancelled"}


# ---------------------------------------------------------------- utilidades


class Error(Exception):
    """Error controlado: se imprime como JSON con ok=false."""


def salida(datos: dict, codigo: int = 0) -> None:
    print(json.dumps(datos, ensure_ascii=False, default=str))
    sys.exit(codigo)


def enmascarar(texto: str) -> str:
    """Oculta contraseñas en URLs (proto://user:PASS@host) y tokens tipo Bearer."""
    texto = re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1****@", texto)
    return re.sub(r"(?i)(bearer\s+)\S+", r"\1****", texto)


def leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text())
    except FileNotFoundError:
        return defecto


def escribir_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n")
    tmp.chmod(0o600)
    tmp.replace(ruta)


def config() -> dict:
    cfg = leer_json(CONFIG, None)
    if not cfg:
        raise Error(f"Falta la configuración en {CONFIG}. Ejecuta: coolify.py config-init --url URL --dominio DOMINIO")
    return cfg


def token() -> str:
    if os.environ.get("COOLIFY_TOKEN"):
        return os.environ["COOLIFY_TOKEN"]
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", SERVICIO_LLAVERO, "-w"],
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise Error("No encuentro el token. Guárdalo en el Llavero: "
                    f"security add-generic-password -a \"$USER\" -s {SERVICIO_LLAVERO} -w") from None


def contrasena(longitud: int = 32) -> str:
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(longitud))


# ---------------------------------------------------------------- HTTP


def api(metodo: str, ruta: str, cuerpo: dict | list | None = None, consulta: dict | None = None):
    cfg = config()
    url = cfg["url"].rstrip("/") + "/api/v1" + ruta
    if consulta:
        url += "?" + urllib.parse.urlencode({k: v for k, v in consulta.items() if v is not None})
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(url, data=datos, method=metodo, headers={
        "Authorization": f"Bearer {token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(peticion, timeout=60) as r:
            texto = r.read().decode() or "{}"
            try:
                return json.loads(texto)
            except json.JSONDecodeError:
                return {"texto": texto}
    except urllib.error.HTTPError as e:
        detalle = e.read().decode(errors="replace")[:800]
        pistas = {401: "token inválido o caducado", 403: "el token no tiene permiso o tu IP no está en «Allowed IPs»",
                  404: "no existe (uuid o ruta)", 422: "datos rechazados por Coolify"}
        raise Error(f"HTTP {e.code} en {metodo} {ruta} ({pistas.get(e.code, 'error')}): {enmascarar(detalle)}") from None
    except urllib.error.URLError as e:
        raise Error(f"No llego a Coolify en {cfg['url']}: {e.reason}. ¿Estás en casa o con la VPN? ¿API activada?") from None


# ---------------------------------------------------------------- registro local de apps


def registro() -> dict:
    return leer_json(REGISTRO, {})


def guardar_en_registro(nombre: str, datos: dict) -> None:
    reg = registro()
    reg[nombre] = {**reg.get(nombre, {}), **datos, "actualizado": time.strftime("%Y-%m-%d %H:%M")}
    escribir_json(REGISTRO, reg)


def resolver_app(nombre_o_uuid: str) -> str:
    """Acepta el nombre del registro local o un uuid de Coolify."""
    reg = registro()
    if nombre_o_uuid in reg and reg[nombre_o_uuid].get("app_uuid"):
        return reg[nombre_o_uuid]["app_uuid"]
    return nombre_o_uuid


def host_de(url_o_host: str) -> str:
    h = url_o_host.strip()
    if "://" in h:
        h = urllib.parse.urlparse(h).hostname or h
    return h.lower().rstrip(".")


# ---------------------------------------------------------------- órdenes


def cmd_comprobar(_a):
    version = api("GET", "/version")
    proyectos = api("GET", "/projects")
    cfg = config()
    return {"ok": True, "coolify": version.get("texto", version), "url": cfg["url"],
            "proyectos": len(proyectos) if isinstance(proyectos, list) else None}


def cmd_config_init(a):
    """Descubre server_uuid y github_app_uuid y guarda la configuración."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    previa = leer_json(CONFIG, {})
    cfg = {**previa, "url": a.url or previa.get("url"), "dominio_base": a.dominio or previa.get("dominio_base")}
    if not cfg["url"] or not cfg["dominio_base"]:
        raise Error("Indica --url y --dominio la primera vez.")
    escribir_json(CONFIG, cfg)  # para que api() pueda leer la url
    servidores = api("GET", "/servers")
    if not servidores:
        raise Error("Coolify no devuelve ningún servidor.")
    servidor = next((s for s in servidores if s.get("name") == (a.servidor or "localhost")), servidores[0])
    apps_gh = api("GET", "/github-apps")
    gh = [g for g in apps_gh if not g.get("is_public")] if isinstance(apps_gh, list) else []
    if not gh:
        raise Error("No hay ninguna GitHub App privada conectada en Coolify (Sources).")
    gh_app = next((g for g in gh if g.get("name") == a.github_app), gh[0])
    cfg.update({
        "server_uuid": servidor["uuid"], "server_name": servidor.get("name"),
        "github_app_uuid": gh_app["uuid"], "github_app_id": gh_app.get("id"), "github_app_name": gh_app.get("name"),
        "subdominios_reservados": sorted(set(previa.get("subdominios_reservados", []) + (a.reservado or []))),
        "ssh": a.ssh or previa.get("ssh"),
        "carpeta_proyectos": a.proyectos or previa.get("carpeta_proyectos") or "~/Projects",
        "limites_defecto": previa.get("limites_defecto", {"cpus": "1", "memoria": "512m"}),
    })
    escribir_json(CONFIG, cfg)
    return {"ok": True, "config": str(CONFIG), "servidor": cfg["server_name"], "github_app": cfg["github_app_name"],
            "dominio_base": cfg["dominio_base"], "reservados": cfg["subdominios_reservados"],
            "carpeta_proyectos": cfg["carpeta_proyectos"]}


def _apps() -> list[dict]:
    r = api("GET", "/applications")
    return r if isinstance(r, list) else []


def _autodeploy(ap: dict):
    """El listado no trae «settings»; si falta, se pide el detalle de la app."""
    ajustes = ap.get("settings") or (api("GET", f"/applications/{ap['uuid']}") or {}).get("settings") or {}
    return ajustes.get("is_auto_deploy_enabled")


def cmd_estado(_a):
    apps = []
    for ap in _apps():
        apps.append({"nombre": ap.get("name"), "uuid": ap.get("uuid"), "estado": ap.get("status"),
                     "dominios": ap.get("fqdn"), "repo": ap.get("git_repository"), "rama": ap.get("git_branch"),
                     "autodeploy": _autodeploy(ap)})
    dbs = [{"nombre": d.get("name"), "uuid": d.get("uuid"), "tipo": d.get("database_type"), "estado": d.get("status"),
            "publica": d.get("is_public")} for d in (api("GET", "/databases") or [])]
    return {"ok": True, "apps": apps, "bases_de_datos": dbs, "registro_local": sorted(registro())}


def dominios_en_uso() -> set[str]:
    usados = set()
    for ap in _apps():
        for d in (ap.get("fqdn") or "").split(","):
            if d.strip():
                usados.add(host_de(d))
    return usados


def cmd_dominio_libre(a):
    cfg = config()
    host = host_de(a.host)
    base = cfg["dominio_base"]
    if "." not in host:
        host = f"{host}.{base}"
    sub = host[: -len(base) - 1] if host.endswith("." + base) else None
    motivos = []
    if not host.endswith("." + base):
        motivos.append(f"no es un subdominio de {base}")
    if sub in cfg.get("subdominios_reservados", []):
        motivos.append(f"«{sub}» está reservado")
    if sub and not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", sub):
        motivos.append("nombre no válido (solo minúsculas, números y guiones)")
    if host in dominios_en_uso():
        motivos.append("ya lo usa otra app")
    return {"ok": True, "host": host, "libre": not motivos, "motivos": motivos}


def cmd_crear_proyecto(a):
    for p in api("GET", "/projects") or []:
        if p.get("name") == a.nombre:
            return {"ok": True, "proyecto_uuid": p["uuid"], "creado": False}
    r = api("POST", "/projects", {"name": a.nombre, "description": a.descripcion or ""})
    return {"ok": True, "proyecto_uuid": r["uuid"], "creado": True}


def cmd_crear_postgres(a):
    cfg = config()
    clave = contrasena()
    usuario = re.sub(r"[^a-z0-9_]", "_", a.nombre.lower())[:30] or "app"
    cuerpo = {"server_uuid": cfg["server_uuid"], "project_uuid": a.proyecto, "environment_name": a.entorno,
              "name": f"{a.nombre}-db", "image": a.imagen, "postgres_user": usuario, "postgres_password": clave,
              "postgres_db": usuario, "is_public": False, "instant_deploy": True,
              "limits_memory": a.memoria}
    r = api("POST", "/databases/postgresql", cuerpo)
    uuid = r["uuid"]
    url_interna = f"postgres://{usuario}:{clave}@{uuid}:5432/{usuario}"
    guardar_en_registro(a.app or a.nombre, {"db_uuid": uuid, "proyecto_uuid": a.proyecto})
    if a.app_uuid:  # conectar directamente a la app como DATABASE_URL (secreta, solo runtime)
        _poner_variable(a.app_uuid, "DATABASE_URL", url_interna, secreta=True)
    return {"ok": True, "db_uuid": uuid, "host_interno": uuid, "usuario": usuario,
            "database_url": enmascarar(url_interna), "conectada_a_app": bool(a.app_uuid)}


def cmd_crear_app(a):
    cfg = config()
    libre = cmd_dominio_libre(argparse.Namespace(host=a.dominio))
    if not libre["libre"]:
        raise Error(f"Dominio {libre['host']} no disponible: {', '.join(libre['motivos'])}")
    lim = cfg.get("limites_defecto", {})
    cuerpo = {
        "project_uuid": a.proyecto, "server_uuid": cfg["server_uuid"], "environment_name": a.entorno,
        "github_app_uuid": cfg["github_app_uuid"], "git_repository": a.repo, "git_branch": a.rama,
        "build_pack": "dockerfile", "ports_exposes": str(a.puerto), "name": a.nombre,
        "domains": f"https://{libre['host']}", "is_auto_deploy_enabled": not a.sin_autodeploy,
        "is_force_https_enabled": True, "health_check_enabled": False, "instant_deploy": False,
        "limits_cpus": a.cpus or lim.get("cpus", "1"), "limits_memory": a.memoria or lim.get("memoria", "512m"),
    }
    if a.dockerfile:
        cuerpo["dockerfile_location"] = a.dockerfile
    if a.base:
        cuerpo["base_directory"] = a.base
    r = api("POST", "/applications/private-github-app", cuerpo)
    uuid = r["uuid"]
    guardar_en_registro(a.nombre, {"app_uuid": uuid, "proyecto_uuid": a.proyecto, "dominio": libre["host"],
                                   "repo": a.repo, "rama": a.rama})
    return {"ok": True, "app_uuid": uuid, "url": f"https://{libre['host']}"}


def _poner_variable(app_uuid: str, clave: str, valor: str, secreta: bool) -> dict:
    """Crea o actualiza una variable. Secreta = solo en ejecución, literal y oculta en la UI."""
    cuerpo = {"key": clave, "value": valor, "is_preview": False, "is_literal": True,
              "is_buildtime": not secreta, "is_runtime": True}
    if secreta:
        cuerpo["is_shown_once"] = True
    existentes = api("GET", f"/applications/{app_uuid}/envs") or []
    if any(e.get("key") == clave and not e.get("is_preview") for e in existentes):
        api("PATCH", f"/applications/{app_uuid}/envs", cuerpo)
        return {"clave": clave, "accion": "actualizada"}
    api("POST", f"/applications/{app_uuid}/envs", cuerpo)
    return {"clave": clave, "accion": "creada"}


def cmd_variable(a):
    app = resolver_app(a.app)
    if "=" not in a.par:
        raise Error("Formato: CLAVE=valor")
    clave, valor = a.par.split("=", 1)
    if a.desde_stdin:
        valor = sys.stdin.read().rstrip("\n")
    return {"ok": True, **_poner_variable(app, clave.strip(), valor, secreta=a.secreta)}


PREFIJOS_PUBLICOS = ("NEXT_PUBLIC_", "VITE_", "PUBLIC_", "NUXT_PUBLIC_", "REACT_APP_")


def cmd_variables_fichero(a):
    """Sube las variables de un fichero KEY=valor sin que los valores pasen por el chat.

    Las públicas (NEXT_PUBLIC_*, VITE_*…) se marcan también para la build (se incrustan en el JS del navegador);
    el resto, solo en ejecución y ocultas. Devuelve solo los nombres.
    """
    app = resolver_app(a.app)
    ruta = Path(a.fichero).expanduser()
    if not ruta.exists():
        raise Error(f"No existe {ruta}")
    resultado = []
    for linea in ruta.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.removeprefix("export ").split("=", 1)
        clave, valor = clave.strip(), valor.strip().strip("\"'")
        publica = clave.startswith(PREFIJOS_PUBLICOS)
        resultado.append({**_poner_variable(app, clave, valor, secreta=not publica), "publica": publica})
    return {"ok": True, "variables": resultado}


def cmd_variables(a):
    app = resolver_app(a.app)
    envs = api("GET", f"/applications/{app}/envs") or []
    # Coolify crea una copia de cada variable para los despliegues de preview: no se muestran
    return {"ok": True, "variables": [{"clave": e.get("key"), "build": e.get("is_buildtime"),
                                       "runtime": e.get("is_runtime")} for e in envs if not e.get("is_preview")]}


def cmd_borrar_variable(a):
    """Borra una variable (y su copia de preview). Exige --confirmado."""
    if not a.confirmado:
        raise Error("Borrar una variable necesita --confirmado (pregunta antes al usuario).")
    app = resolver_app(a.app)
    envs = [e for e in (api("GET", f"/applications/{app}/envs") or []) if e.get("key") == a.clave]
    if not envs:
        raise Error(f"La app no tiene la variable {a.clave}")
    for e in envs:
        api("DELETE", f"/applications/{app}/envs/{e['uuid']}")
    return {"ok": True, "clave": a.clave, "borradas": len(envs)}


def cmd_desplegar(a):
    app = resolver_app(a.app)
    r = api("POST", "/deploy", consulta={"uuid": app, "force": "true" if a.forzar else "false"})
    deps = r.get("deployments") or []
    if not deps:
        raise Error(f"Coolify no ha creado ningún despliegue: {r}")
    return {"ok": True, "deployment_uuid": deps[0].get("deployment_uuid"), "mensaje": deps[0].get("message")}


def _ultimas_lineas(logs_json: str | None, n: int) -> list[str]:
    try:
        entradas = json.loads(logs_json or "[]")
    except json.JSONDecodeError:
        return [enmascarar(l) for l in (logs_json or "").splitlines()[-n:]]
    lineas = [e.get("output", "") for e in entradas if not e.get("hidden")]
    return [enmascarar(l) for l in "\n".join(lineas).splitlines()[-n:]]


def cmd_esperar(a):
    inicio = time.time()
    while True:
        d = api("GET", f"/deployments/{a.deployment}")
        estado = d.get("status")
        if estado in ESTADOS_FINALES:
            res = {"ok": estado == "finished", "estado": estado, "segundos": int(time.time() - inicio),
                   "commit": (d.get("commit") or "")[:7]}
            if estado != "finished":
                res["ultimas_lineas"] = _ultimas_lineas(d.get("logs"), a.lineas)
            return res
        if time.time() - inicio > a.timeout:
            return {"ok": False, "estado": estado, "timeout": True, "ultimas_lineas": _ultimas_lineas(d.get("logs"), 20)}
        time.sleep(5)


def cmd_ultimo_despliegue(a):
    app = resolver_app(a.app)
    deps = api("GET", f"/deployments/applications/{app}", consulta={"take": 1})
    lista = deps.get("deployments", deps) if isinstance(deps, dict) else deps
    if not lista:
        return {"ok": True, "despliegue": None}
    d = lista[0]
    return {"ok": True, "deployment_uuid": d.get("deployment_uuid"), "estado": d.get("status"),
            "commit": (d.get("commit") or "")[:7], "webhook": d.get("is_webhook"), "creado": d.get("created_at")}


def cmd_logs(a):
    app = resolver_app(a.app)
    r = api("GET", f"/applications/{app}/logs", consulta={"lines": a.lineas})
    return {"ok": True, "logs": enmascarar(r.get("logs", "") if isinstance(r, dict) else str(r))}


def cmd_rollback(a):
    if not a.confirmado:
        raise Error("Rollback requiere --confirmado (el usuario debe aprobarlo antes).")
    app = resolver_app(a.app)
    if not a.imagen:
        return {"ok": True, "imagenes_disponibles": api("GET", f"/applications/{app}/rollback-images")}
    return {"ok": True, **api("POST", f"/applications/{app}/rollback", {"docker_tag": a.imagen})}


def _esperar_borrado(ruta: str, timeout: int = 180) -> bool:
    """Coolify borra en segundo plano: espera a que el recurso dé 404 (limpieza del servidor terminada)."""
    limite = time.time() + timeout
    while time.time() < limite:
        try:
            api("GET", ruta)
        except Error as e:
            if "HTTP 404" in str(e):
                return True
            raise
        time.sleep(3)
    return False


def cmd_retirar(a):
    if not a.confirmado:
        raise Error("Retirar requiere --confirmado (el usuario debe aprobarlo antes).")
    nombre = a.app
    reg = registro()
    app = resolver_app(nombre)
    api("DELETE", f"/applications/{app}", consulta={"delete_configurations": "true", "delete_volumes": "true",
                                                      "docker_cleanup": "true", "delete_connected_networks": "true"})
    borrado = {"app": app}
    pendientes = [f"/applications/{app}"]
    if a.con_bd and reg.get(nombre, {}).get("db_uuid"):
        api("DELETE", f"/databases/{reg[nombre]['db_uuid']}", consulta={"delete_volumes": "true"})
        borrado["db"] = reg[nombre]["db_uuid"]
        pendientes.append(f"/databases/{reg[nombre]['db_uuid']}")
    # Si se borra el proyecto antes de que Coolify termine, su limpieza falla y deja volúmenes,
    # imágenes y carpetas huérfanos en el servidor. Por eso se espera a que cada recurso desaparezca.
    sin_terminar = [r for r in pendientes if not _esperar_borrado(r)]
    if sin_terminar:
        borrado["aviso"] = "Coolify no terminó a tiempo de borrar: " + ", ".join(sin_terminar) + \
                           " (el proyecto no se borra; repite más tarde)"
    elif a.con_proyecto and reg.get(nombre, {}).get("proyecto_uuid"):
        try:
            api("DELETE", f"/projects/{reg[nombre]['proyecto_uuid']}")
            borrado["proyecto"] = reg[nombre]["proyecto_uuid"]
        except Error as e:
            borrado["proyecto_no_borrado"] = str(e)
    if nombre in reg:
        del reg[nombre]
        escribir_json(REGISTRO, reg)
    return {"ok": True, "borrado": borrado}


# ---------------------------------------------------------------- CLI


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coolify.py", description="Cliente de Coolify para la skill desplegar-coolify")
    s = p.add_subparsers(dest="orden", required=True)

    s.add_parser("comprobar", help="versión de Coolify y validez del token").set_defaults(f=cmd_comprobar)

    c = s.add_parser("config-init", help="crear/actualizar ~/.config/coolify-deploy/config.json")
    c.add_argument("--url"); c.add_argument("--dominio"); c.add_argument("--ssh")
    c.add_argument("--servidor"); c.add_argument("--github-app", dest="github_app")
    c.add_argument("--reservado", action="append", help="subdominio que no se puede usar (repetible)")
    c.add_argument("--proyectos", help="carpeta donde se clonan los proyectos (por defecto ~/Projects)")
    c.set_defaults(f=cmd_config_init)

    s.add_parser("estado", help="apps y bases de datos").set_defaults(f=cmd_estado)

    c = s.add_parser("dominio-libre"); c.add_argument("host"); c.set_defaults(f=cmd_dominio_libre)

    c = s.add_parser("crear-proyecto"); c.add_argument("nombre"); c.add_argument("--descripcion")
    c.set_defaults(f=cmd_crear_proyecto)

    c = s.add_parser("crear-app")
    for arg in ("--proyecto", "--repo", "--rama", "--puerto", "--dominio", "--nombre"):
        c.add_argument(arg, required=True)
    c.add_argument("--entorno", default="production"); c.add_argument("--cpus"); c.add_argument("--memoria")
    c.add_argument("--dockerfile"); c.add_argument("--base")
    c.add_argument("--sin-autodeploy", dest="sin_autodeploy", action="store_true")
    c.set_defaults(f=cmd_crear_app)

    c = s.add_parser("crear-postgres")
    c.add_argument("--proyecto", required=True); c.add_argument("--nombre", required=True)
    c.add_argument("--app", help="nombre de la app en el registro"); c.add_argument("--app-uuid", dest="app_uuid")
    c.add_argument("--entorno", default="production"); c.add_argument("--imagen", default="postgres:17-alpine")
    c.add_argument("--memoria", default="512m")
    c.set_defaults(f=cmd_crear_postgres)

    c = s.add_parser("variable", help="CLAVE=valor (con --desde-stdin el valor se lee de la entrada)")
    c.add_argument("app"); c.add_argument("par"); c.add_argument("--secreta", action="store_true")
    c.add_argument("--desde-stdin", dest="desde_stdin", action="store_true")
    c.set_defaults(f=cmd_variable)

    c = s.add_parser("variables"); c.add_argument("app"); c.set_defaults(f=cmd_variables)

    c = s.add_parser("borrar-variable"); c.add_argument("app"); c.add_argument("clave")
    c.add_argument("--confirmado", action="store_true"); c.set_defaults(f=cmd_borrar_variable)

    c = s.add_parser("variables-fichero", help="sube KEY=valor de un fichero (los valores no salen por pantalla)")
    c.add_argument("app"); c.add_argument("fichero"); c.set_defaults(f=cmd_variables_fichero)

    c = s.add_parser("desplegar"); c.add_argument("app"); c.add_argument("--forzar", action="store_true")
    c.set_defaults(f=cmd_desplegar)

    c = s.add_parser("esperar"); c.add_argument("deployment"); c.add_argument("--timeout", type=int, default=900)
    c.add_argument("--lineas", type=int, default=40); c.set_defaults(f=cmd_esperar)

    c = s.add_parser("ultimo-despliegue"); c.add_argument("app"); c.set_defaults(f=cmd_ultimo_despliegue)

    c = s.add_parser("logs"); c.add_argument("app"); c.add_argument("--lineas", type=int, default=100)
    c.set_defaults(f=cmd_logs)

    c = s.add_parser("rollback"); c.add_argument("app"); c.add_argument("--imagen")
    c.add_argument("--confirmado", action="store_true"); c.set_defaults(f=cmd_rollback)

    c = s.add_parser("retirar"); c.add_argument("app"); c.add_argument("--confirmado", action="store_true")
    c.add_argument("--con-bd", dest="con_bd", action="store_true")
    c.add_argument("--con-proyecto", dest="con_proyecto", action="store_true")
    c.set_defaults(f=cmd_retirar)
    return p


def main(argv=None) -> None:
    args = parser().parse_args(argv)
    try:
        salida(args.f(args))
    except Error as e:
        salida({"ok": False, "error": str(e)}, 1)


if __name__ == "__main__":
    main()
