#!/usr/bin/env python3
"""Verifica una app ya desplegada: certificado HTTPS, redirección HTTP→HTTPS, rutas, acceso desde Internet
(check-host.net, opcional) y temperatura del servidor por SSH (opcional, según la configuración).

Uso:  verificar.py <https://host> [--rutas / /health] [--externo] [--servidor] [--espera 120]
      verificar.py --servidor                 (solo salud del servidor: temperatura, disco, Coolify)
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coolify import CONFIG, leer_json  # noqa: E402

CABECERAS = {"Accept": "application/json", "User-Agent": "coolify-deploy-verificar/1.0 (+https://github.com)"}


class SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def pedir(url: str, seguir: bool = True) -> tuple[int, str]:
    abridor = urllib.request.build_opener() if seguir else urllib.request.build_opener(SinRedireccion)
    try:
        with abridor.open(urllib.request.Request(url, headers={"User-Agent": "coolify-deploy-verificar"}), timeout=10) as r:
            return r.status, r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")
    except (urllib.error.URLError, OSError):
        return 0, ""


def certificado(host: str) -> dict:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=10) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            c = t.getpeercert()
        emisor = dict(x[0] for x in c["issuer"])
        caduca = datetime.strptime(c["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        return {"valido": True, "emisor": emisor.get("organizationName"), "caduca": caduca.date().isoformat(),
                "dias_restantes": (caduca - datetime.now(timezone.utc)).days}
    except ssl.SSLCertVerificationError as e:
        return {"valido": False, "error": e.verify_message}
    except OSError as e:
        return {"valido": False, "error": str(e)}


def externo(url: str) -> dict:
    """Pide a check-host.net que abra la URL desde 3 países y devuelve sus códigos."""
    try:
        q = urllib.parse.urlencode({"host": url, "max_nodes": 3})
        r = urllib.request.urlopen(urllib.request.Request(f"https://check-host.net/check-http?{q}",
                                                          headers=CABECERAS), timeout=20)
        rid = json.load(r)["request_id"]
        for _ in range(20):
            time.sleep(3)
            datos = json.load(urllib.request.urlopen(urllib.request.Request(
                f"https://check-host.net/check-result/{rid}", headers=CABECERAS), timeout=20))
            if all(datos.values()):
                return {n.split(".")[0]: (v[0][3] if v and v[0] and len(v[0]) > 3 else None) for n, v in datos.items()}
        return {"error": "check-host no respondió a tiempo"}
    except Exception as e:  # noqa: BLE001 - servicio externo: cualquier fallo se informa sin romper
        return {"error": f"check-host no disponible: {e}"}


def servidor() -> dict:
    cfg = leer_json(CONFIG, {}) or {}
    destino = cfg.get("ssh")
    if not destino:
        return {"omitido": "sin «ssh» en la configuración"}
    orden = ("echo T=$(vcgencmd measure_temp 2>/dev/null | grep -o '[0-9.]*' || "
             "awk '{print $1/1000}' /sys/class/thermal/thermal_zone0/temp); "
             "echo D=$(df -P / | awk 'NR==2{print $5}'); "
             "echo C=$(docker inspect -f '{{.State.Health.Status}}' coolify 2>/dev/null)")
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", destino, orden],
                           capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {"error": "ssh sin respuesta"}
    if r.returncode != 0:
        return {"error": "no puedo entrar por ssh (¿clave autorizada?)"}
    v = dict(l.split("=", 1) for l in r.stdout.split() if "=" in l)
    temp = float(v["T"]) if v.get("T") else None
    disco = int(v["D"].rstrip("%")) if v.get("D") else None
    return {"temperatura": temp, "disco_usado_pct": disco, "coolify": v.get("C"),
            "ok": (temp is None or temp < 80) and (disco is None or disco < 90) and v.get("C") == "healthy"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("url", nargs="?"); p.add_argument("--rutas", nargs="*", default=["/"])
    p.add_argument("--externo", action="store_true"); p.add_argument("--servidor", action="store_true")
    p.add_argument("--espera", type=int, default=120, help="segundos máximos esperando a que responda")
    a = p.parse_args()
    res: dict = {}
    if a.url:
        url = a.url if "://" in a.url else f"https://{a.url}"
        host = urllib.parse.urlparse(url).hostname
        limite = time.time() + a.espera
        while time.time() < limite:  # el certificado y el contenedor pueden tardar unos segundos
            cert = certificado(host)
            if cert["valido"] and 0 < pedir(url)[0] < 500:
                break
            time.sleep(5)
        res["certificado"] = certificado(host)
        cod, destino = pedir(f"http://{host}/", seguir=False)
        res["http_a_https"] = {"codigo": cod, "ok": cod in (301, 302, 307, 308) and destino.startswith("https://")}
        res["rutas"] = {r: pedir(url.rstrip("/") + r)[0] for r in a.rutas}
        if a.externo:
            res["externo"] = externo(url.rstrip("/") + a.rutas[0])
        res["ok"] = (res["certificado"]["valido"] and res["http_a_https"]["ok"]
                     and all(200 <= c < 400 for c in res["rutas"].values())
                     and (not a.externo or "error" in res["externo"]
                          or all(str(c).startswith(("2", "3")) for c in res["externo"].values())))
        if a.externo and "error" in res["externo"]:
            res["externo_no_verificado"] = True
    if a.servidor:
        res["servidor"] = servidor()
        res["ok"] = res.get("ok", True) and res["servidor"].get("ok", False)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
