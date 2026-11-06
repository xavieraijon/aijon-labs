#!/usr/bin/env python3
"""Genera los ficheros de despliegue (Dockerfile, .dockerignore, nginx.conf) a partir de las plantillas.

Nunca sobrescribe un fichero existente salvo con --sobrescribir. No toca la lógica de la app.

Uso:  preparar.py <ruta> [--var CLAVE=valor ...] [--sobrescribir] [--simular]
      Los valores salen del análisis (analizar.py); --var permite corregirlos (p. ej. --var PUERTO=8080).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PLANTILLAS = AQUI.parent / "plantillas"
sys.path.insert(0, str(AQUI))
from analizar import analizar  # noqa: E402

NGINX = {"spa-nginx": "nginx-spa.conf", "static-nginx": "nginx-static.conf"}


def valores(analisis: dict, extra: dict) -> dict:
    s = analisis.get("stack", {})
    v = {"PUERTO": str(s.get("puerto", "")), "NODE_VERSION": s.get("node_version", "22"),
         "PYTHON_VERSION": s.get("python_version", "3.12"), "MODULO": s.get("modulo", "main:app"),
         "BUILD_CMD": s.get("build_cmd", "npm run build"), "BUILD_DIR": s.get("build_dir", "dist"),
         "PHP_VERSION": "8.3"}
    v.update(extra)
    return v


def rellenar(texto: str, v: dict) -> str:
    resultado = re.sub(r"\{\{(\w+)\}\}", lambda m: str(v.get(m.group(1), m.group(0))), texto)
    faltan = re.findall(r"\{\{(\w+)\}\}", resultado)
    if faltan:
        raise ValueError(f"faltan valores para: {', '.join(sorted(set(faltan)))}")
    return resultado


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("ruta")
    p.add_argument("--var", action="append", default=[], help="CLAVE=valor")
    p.add_argument("--plantilla", help="forzar una plantilla concreta")
    p.add_argument("--sobrescribir", action="store_true")
    p.add_argument("--simular", action="store_true", help="no escribe: muestra qué haría")
    a = p.parse_args()

    raiz = Path(a.ruta).expanduser().resolve()
    analisis = analizar(raiz)
    if not analisis.get("ok"):
        print(json.dumps(analisis, ensure_ascii=False)); sys.exit(1)
    plantilla = a.plantilla or analisis.get("stack", {}).get("plantilla")
    if not plantilla:
        motivo = "ya tiene Dockerfile" if analisis.get("stack", {}).get("dockerfile_existente") else "no hay plantilla para este proyecto"
        print(json.dumps({"ok": True, "creados": [], "omitidos": [], "motivo": motivo}, ensure_ascii=False))
        return
    extra = dict(x.split("=", 1) for x in a.var)
    v = valores(analisis, extra)

    planes = [("Dockerfile", PLANTILLAS / f"{plantilla}.Dockerfile"), (".dockerignore", PLANTILLAS / "dockerignore")]
    if plantilla in NGINX:
        planes.append(("nginx.conf", PLANTILLAS / NGINX[plantilla]))

    creados, omitidos = [], []
    try:
        for destino, origen in planes:
            ruta = raiz / destino
            if ruta.exists() and not a.sobrescribir:
                omitidos.append(destino)
                continue
            contenido = rellenar(origen.read_text(), v)
            if not a.simular:
                ruta.write_text(contenido)
            creados.append(destino)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)); sys.exit(1)
    print(json.dumps({"ok": True, "plantilla": plantilla, "valores": v, "creados": creados, "omitidos": omitidos,
                      "simulado": a.simular}, ensure_ascii=False))


if __name__ == "__main__":
    main()
