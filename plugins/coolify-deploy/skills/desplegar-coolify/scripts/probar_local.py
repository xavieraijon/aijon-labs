#!/usr/bin/env python3
"""Construye la imagen en el Mac, la arranca y comprueba sus rutas. Siempre limpia al terminar.

El Mac con Apple Silicon y la Raspberry Pi comparten arquitectura (ARM64): si funciona aquí, la build
funcionará allí. Las variables se pasan con --env (para pruebas: nunca secretos de producción).

Uso:  probar_local.py <ruta> --puerto 8000 [--rutas / /health] [--env CLAVE=valor ...] [--espera 60]
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ejecutar(*cmd: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)


def pedir(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "")
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return 0, ""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("ruta"); p.add_argument("--puerto", type=int, required=True)
    p.add_argument("--rutas", nargs="*", default=["/"]); p.add_argument("--env", action="append", default=[])
    p.add_argument("--espera", type=int, default=60); p.add_argument("--timeout-build", type=int, default=1200)
    a = p.parse_args()

    raiz = Path(a.ruta).expanduser().resolve()
    nombre = "coolify-prueba-" + re.sub(r"[^a-z0-9-]", "-", raiz.name.lower())
    res: dict = {"ok": False, "imagen": nombre}
    if ejecutar("docker", "info").returncode != 0:
        print(json.dumps({"ok": False, "error": "Docker no está arrancado en el Mac (abre Docker Desktop)"}, ensure_ascii=False))
        return
    try:
        t0 = time.time()
        b = ejecutar("docker", "build", "-t", nombre, str(raiz), timeout=a.timeout_build)
        res["build_segundos"] = int(time.time() - t0)
        if b.returncode != 0:
            res["fase"] = "build"
            res["error_build"] = (b.stderr or b.stdout).splitlines()[-40:]
            return
        local = puerto_libre()
        envs = [x for e in a.env for x in ("-e", e)]
        r = ejecutar("docker", "run", "-d", "--name", nombre, "-p", f"127.0.0.1:{local}:{a.puerto}", *envs, nombre)
        if r.returncode != 0:
            res["fase"] = "arranque"; res["error"] = r.stderr.strip()[-800:]
            return
        base = f"http://127.0.0.1:{local}"
        limite = time.time() + a.espera
        while time.time() < limite and pedir(base + a.rutas[0])[0] == 0:
            time.sleep(1)
        rutas = {}
        for ruta in a.rutas:
            codigo, tipo = pedir(base + ruta)
            rutas[ruta] = {"codigo": codigo, "tipo": tipo.split(";")[0]}
        res["rutas"] = rutas
        res["ok"] = all(0 < v["codigo"] < 500 for v in rutas.values())
        if not res["ok"]:
            res["fase"] = "rutas"
            res["logs_contenedor"] = ejecutar("docker", "logs", "--tail", "40", nombre).stdout.splitlines()[-40:] + \
                ejecutar("docker", "logs", "--tail", "40", nombre).stderr.splitlines()[-40:]
    finally:
        ejecutar("docker", "rm", "-f", nombre)
        ejecutar("docker", "image", "rm", "-f", nombre)
        res["limpio"] = True
        print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
