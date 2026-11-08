#!/usr/bin/env python3
"""Verify a deployed app: HTTPS certificate, HTTP→HTTPS redirect, routes, reachability from the Internet
(check-host.net, optional) and server health over SSH (optional, needs «ssh» in the configuration).

Usage:  verify.py <https://host> [--routes / /health] [--external] [--server] [--wait 120] [--protected]
        verify.py --server                 (server health only: temperature, disk, Coolify)
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
from coolify import config  # noqa: E402

USER_AGENT = "coolify-ops-verify/1.0 (+https://github.com/xavieraijon/aijon-labs)"
HEADERS = {"Accept": "application/json", "User-Agent": USER_AGENT}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def body(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read(2_000_000).decode(errors="ignore")
    except (urllib.error.URLError, OSError):
        return ""


def fetch(url: str, follow: bool = True) -> tuple[int, str]:
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=10) as r:
            return r.status, r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")
    except (urllib.error.URLError, OSError):
        return 0, ""


def certificate(host: str) -> dict:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=10) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            c = t.getpeercert()
        issuer = dict(x[0] for x in c["issuer"])
        expires = datetime.strptime(c["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        return {"valid": True, "issuer": issuer.get("organizationName"), "expires": expires.date().isoformat(),
                "days_left": (expires - datetime.now(timezone.utc)).days}
    except ssl.SSLCertVerificationError as e:
        return {"valid": False, "error": e.verify_message}
    except OSError as e:
        return {"valid": False, "error": str(e)}


def external(url: str) -> dict:
    """Ask check-host.net to open the URL from 3 countries and return their status codes."""
    try:
        q = urllib.parse.urlencode({"host": url, "max_nodes": 3})
        r = urllib.request.urlopen(urllib.request.Request(f"https://check-host.net/check-http?{q}",
                                                          headers=HEADERS), timeout=20)
        rid = json.load(r)["request_id"]
        for _ in range(20):
            time.sleep(3)
            data = json.load(urllib.request.urlopen(urllib.request.Request(
                f"https://check-host.net/check-result/{rid}", headers=HEADERS), timeout=20))
            if all(data.values()):
                return {n.split(".")[0]: (v[0][3] if v and v[0] and len(v[0]) > 3 else None) for n, v in data.items()}
        return {"error": "check-host did not answer in time"}
    except Exception as e:  # noqa: BLE001 - external service: report any failure without crashing
        return {"error": f"check-host unavailable: {e}"}


def answered_ok(code, protected: bool = False, accept_4xx: bool = False) -> bool:
    """2xx/3xx; an app protected with basic auth must answer 401 instead (anything else is a failure).
    With accept_4xx (an app with no page at /) 401/403/404/405 also prove it is up; 400 does not (Django answers
    400 when its domain is not allowed)."""
    if protected:
        return str(code) == "401"
    return str(code).startswith(("2", "3")) or (accept_4xx and str(code) in ("401", "403", "404", "405"))


def external_ok(external: dict, protected: bool = False, accept_4xx: bool = False) -> bool:
    """Nodes that gave no answer (None) are ignored; any node that answered must have got a good code.
    If check-host failed altogether, the external check is «unverified», not failed."""
    if "error" in external:
        return True
    codes = [c for c in external.values() if c is not None]
    return all(answered_ok(c, protected, accept_4xx) for c in codes)


def server() -> dict:
    try:
        target = config().get("ssh")
    except Exception:  # noqa: BLE001 - no configuration yet
        target = None
    if not target:
        return {"skipped": "no «ssh» in the configuration"}
    command = ("echo T=$(vcgencmd measure_temp 2>/dev/null | grep -o '[0-9.]*' || "
               "awk '{print $1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null); "
               "echo D=$(df -P / | awk 'NR==2{print $5}'); "
               "echo C=$(docker inspect -f '{{.State.Health.Status}}' coolify 2>/dev/null)")
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, "sh -s"],
                           input=command, capture_output=True, text=True, timeout=30)  # POSIX sh, any login shell
    except subprocess.TimeoutExpired:
        return {"error": "ssh did not answer"}
    if r.returncode != 0:
        return {"error": "cannot log in over ssh (is your key authorized?)"}
    v = dict(l.split("=", 1) for l in r.stdout.split() if "=" in l)
    temp = float(v["T"]) if v.get("T") else None
    disk = int(v["D"].rstrip("%")) if v.get("D") else None
    return {"temperature_c": temp, "disk_used_pct": disk, "coolify": v.get("C"),
            "ok": (temp is None or temp < 80) and (disk is None or disk < 90) and v.get("C") == "healthy"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("url", nargs="?"); p.add_argument("--routes", nargs="*", default=["/"])
    p.add_argument("--external", action="store_true"); p.add_argument("--server", action="store_true")
    p.add_argument("--wait", type=int, default=120, help="max seconds waiting for the app to answer")
    p.add_argument("--protected", action="store_true", help="the app has basic auth: routes must answer 401")
    p.add_argument("--expect", help="text the body of the first route must contain (not checked with --protected)")
    p.add_argument("--accept-4xx", dest="accept_4xx", action="store_true",
                   help="any answer below 500 counts (an app with no page at /)")
    a = p.parse_args()
    res: dict = {}
    if a.url:
        url = a.url if "://" in a.url else f"https://{a.url}"
        host = urllib.parse.urlparse(url).hostname
        deadline = time.time() + a.wait
        while time.time() < deadline:  # the certificate and the container may take a few seconds
            if certificate(host)["valid"] and 0 < fetch(url)[0] < 500:
                break
            time.sleep(5)
        res["certificate"] = certificate(host)
        code, location = fetch(f"http://{host}/", follow=False)
        res["http_to_https"] = {"code": code, "ok": code in (301, 302, 307, 308) and location.startswith("https://")}
        res["routes"] = {r: fetch(url.rstrip("/") + r)[0] for r in a.routes}
        if a.external:
            res["external"] = external(url.rstrip("/") + a.routes[0])
        res["ok"] = (res["certificate"]["valid"] and res["http_to_https"]["ok"]
                     and all(answered_ok(c, a.protected, a.accept_4xx) for c in res["routes"].values())
                     and (not a.external or external_ok(res["external"], a.protected, a.accept_4xx)))
        if a.expect and a.protected:
            res["marker_found"] = None  # behind basic auth the body is the 401 page: cannot be checked
        elif a.expect:
            res["marker_found"] = a.expect in body(url.rstrip("/") + a.routes[0])
            res["ok"] = res["ok"] and res["marker_found"]
        if a.external and ("error" in res["external"] or not any(res["external"].values())):
            res["external_unverified"] = True
        elif a.external and None in res["external"].values():
            res["external_partial"] = True  # some check-host nodes gave no answer: not a failure of the app
    if a.server:
        res["server"] = server()
        res["ok"] = res.get("ok", True) and res["server"].get("ok", "skipped" in res["server"])
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
