#!/usr/bin/env python3
"""Build the image locally, run it and probe its routes. Always cleans up afterwards.

Catches most build and start-up errors before anything reaches the server. Note that the local machine and the
server may differ in CPU architecture (e.g. Apple Silicon vs. an x86 VPS); the build then runs again on the
server, which only matters for native dependencies. Variables are passed with --env (test values only).

Usage:  local_check.py <path> --port 8000 [--routes / /health] [--env KEY=value ...] [--wait 60]
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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(*cmd: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)


def fetch(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "")
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return 0, ""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("path"); p.add_argument("--port", type=int, required=True)
    p.add_argument("--routes", nargs="*", default=["/"]); p.add_argument("--env", action="append", default=[])
    p.add_argument("--wait", type=int, default=60, help="seconds to wait for the app to answer")
    p.add_argument("--build-timeout", dest="build_timeout", type=int, default=1200)
    a = p.parse_args()

    root = Path(a.path).expanduser().resolve()
    name = "coolify-ops-check-" + re.sub(r"[^a-z0-9-]", "-", root.name.lower())
    res: dict = {"ok": False, "image": name}
    if run("docker", "info").returncode != 0:
        print(json.dumps({"ok": False, "error": "Docker is not running on this machine (start Docker Desktop "
                                                "or the Docker daemon)"}, ensure_ascii=False))
        return
    try:
        t0 = time.time()
        b = run("docker", "build", "-t", name, str(root), timeout=a.build_timeout)
        res["build_seconds"] = int(time.time() - t0)
        if b.returncode != 0:
            res["stage"] = "build"
            res["build_error"] = (b.stderr or b.stdout).splitlines()[-40:]
            return
        local = free_port()
        envs = [x for e in a.env for x in ("-e", e)]
        r = run("docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{local}:{a.port}", *envs, name)
        if r.returncode != 0:
            res["stage"] = "start"
            res["error"] = r.stderr.strip()[-800:]
            return
        base = f"http://127.0.0.1:{local}"
        deadline = time.time() + a.wait
        while time.time() < deadline and fetch(base + a.routes[0])[0] == 0:
            time.sleep(1)
        routes = {}
        for route in a.routes:
            code, ctype = fetch(base + route)
            routes[route] = {"code": code, "type": ctype.split(";")[0]}
        res["routes"] = routes
        res["ok"] = all(0 < v["code"] < 500 for v in routes.values())
        if not res["ok"]:
            res["stage"] = "routes"
            logs = run("docker", "logs", "--tail", "40", name)
            res["container_logs"] = (logs.stdout.splitlines() + logs.stderr.splitlines())[-40:]
    finally:
        run("docker", "rm", "-f", name)
        run("docker", "image", "rm", "-f", name)
        res["cleaned_up"] = True
        print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
