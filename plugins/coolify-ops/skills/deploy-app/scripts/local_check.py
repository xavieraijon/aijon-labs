#!/usr/bin/env python3
"""Build the image locally, run it and probe its routes. Always cleans up afterwards.

Catches most build and start-up errors before anything reaches the server. Note that the local machine and the
server may differ in CPU architecture (e.g. Apple Silicon vs. an x86 VPS); the build then runs again on the
server, which only matters for native dependencies. Variables are passed with --env (test values only).

Build-time variables (e.g. SvelteKit $env/static) go with --build-env: as Coolify does, an «ARG KEY» line is added
after every FROM of a temporary copy of the Dockerfile (the project's file is not touched) and the value is passed
with --build-arg. --expect TEXT checks that the body of the first route contains TEXT (e.g. a server-rendering mark).

Usage:  local_check.py <path> --port 8000 [--routes / /health] [--env KEY=value ...] [--build-env KEY=value ...]
                       [--expect TEXT] [--wait 60]
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import with_build_args  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(*cmd: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)


def body(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read(2_000_000).decode(errors="ignore")
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return ""


def fetch(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "")
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return 0, ""


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("path"); p.add_argument("--port", type=int, required=True)
    p.add_argument("--routes", nargs="*", default=["/"]); p.add_argument("--env", action="append", default=[])
    p.add_argument("--wait", type=int, default=60, help="seconds to wait for the app to answer")
    p.add_argument("--build-timeout", dest="build_timeout", type=int, default=1200)
    p.add_argument("--build-env", dest="build_env", action="append", default=[], help="KEY=value at build time")
    p.add_argument("--expect", help="text the body of the first route must contain")
    return p.parse_args(argv)


def check(a: argparse.Namespace) -> dict:
    root = Path(a.path).expanduser().resolve()
    name = "coolify-ops-check-" + re.sub(r"[^a-z0-9-]", "-", root.name.lower())
    res: dict = {"ok": False, "image": name}
    if run("docker", "info").returncode != 0:
        return {"ok": False, "error": "Docker is not running on this machine (start Docker Desktop or the Docker daemon)"}
    tmp = None
    try:
        build_args: list[str] = []
        if a.build_env:
            keys = [e.split("=", 1)[0] for e in a.build_env]
            if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) for k in keys):
                res["error"] = "invalid --build-env name"
                return res
            if not (root / "Dockerfile").is_file():
                res["error"] = "no Dockerfile in the project (run prepare.py first)"
                return res
            content = with_build_args((root / "Dockerfile").read_text(), keys)
            tmp = tempfile.NamedTemporaryFile("w", suffix=".Dockerfile", delete=False)
            tmp.write(content)
            tmp.close()
            build_args = ["-f", tmp.name] + [x for e in a.build_env for x in ("--build-arg", e)]
        t0 = time.time()
        b = run("docker", "build", "-t", name, *build_args, str(root), timeout=a.build_timeout)
        res["build_seconds"] = int(time.time() - t0)
        if b.returncode != 0:
            res["stage"] = "build"
            res["build_error"] = (b.stderr or b.stdout).splitlines()[-40:]
            return res
        local = free_port()
        envs = [x for e in a.env for x in ("-e", e)]
        r = run("docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{local}:{a.port}", *envs, name)
        if r.returncode != 0:
            res["stage"] = "start"
            res["error"] = r.stderr.strip()[-800:]
            return res
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
        if a.expect:
            res["marker_found"] = a.expect in body(base + a.routes[0])
            res["ok"] = res["ok"] and res["marker_found"]
        if not res["ok"]:
            res["stage"] = "routes"
            logs = run("docker", "logs", "--tail", "40", name)
            res["container_logs"] = (logs.stdout.splitlines() + logs.stderr.splitlines())[-40:]
    finally:
        if tmp:
            Path(tmp.name).unlink(missing_ok=True)
        run("docker", "rm", "-f", name)
        run("docker", "image", "rm", "-f", name)
        res["cleaned_up"] = True
    return res


def main(argv=None) -> None:
    res = check(parse_args(argv))
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
