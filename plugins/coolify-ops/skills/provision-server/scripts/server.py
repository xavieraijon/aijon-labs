#!/usr/bin/env python3
"""Read-only checks to prepare a server for Coolify. Never runs sudo, never changes anything on the server.

Usage:  server.py diagnose <user@host>          system, CPU, RAM, disk, Docker, Coolify, ports in use, hardening
        server.py dns <domain> [--expect-ip IP]  does the wildcard *.<domain> resolve (public resolver), to which IP
        server.py ports <host> [--ports 80 443] [--private 8000 6001 6002]
                                                 reachability from the Internet (check-host.net)
        server.py health [--url URL] [--ssh user@host]
                                                 Coolify answering and its containers healthy
                                                 (defaults from ~/.config/coolify-ops/config.json)
All commands print JSON.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "coolify-ops-provision/1.0 (+https://github.com/xavieraijon/aijon-labs)"
CONFIG = Path(os.environ.get("COOLIFY_OPS_HOME") or Path.home() / ".config" / "coolify-ops") / "config.json"
COOLIFY_PORTS = [80, 443, 8000, 6001, 6002]  # proxy http/https, panel, realtime/websockets
COOLIFY_CONTAINERS = ["coolify", "coolify-db", "coolify-redis", "coolify-proxy"]  # required
OPTIONAL_CONTAINERS = ["coolify-realtime", "coolify-sentinel"]  # depend on the Coolify version
MIN_RAM_MB, RECOMMENDED_RAM_MB = 1800, 3800  # «2 GB» / «4 GB» machines report a bit less
MIN_DISK_GB = 20
RATE_LIMIT_RETRIES, RATE_LIMIT_WAIT = 6, 20  # check-host: up to ~2 minutes of back-off per port
# Addresses that only exist inside a network: a public DNS record pointing at one cannot work
LOCAL_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
                                                 "127.0.0.0/8", "169.254.0.0/16")]


class Error(Exception):
    pass


def emit(data: dict, code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(code)


# ---------------------------------------------------------------- ssh


REMOTE_FACTS = r"""
echo OS="$(. /etc/os-release 2>/dev/null; echo "$ID $VERSION_ID")"
echo ARCH="$(uname -m)"
echo CPUS="$(nproc 2>/dev/null)"
echo MEM_MB="$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo 2>/dev/null)"
echo DISK_FREE_GB="$(df -P -BG / 2>/dev/null | awk 'NR==2{gsub("G","",$4); print $4}')"
echo DISK_USED_PCT="$(df -P / 2>/dev/null | awk 'NR==2{gsub("%","",$5); print $5}')"
echo DOCKER="$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ,)"
echo DOCKER_ACCESS="$(docker info >/dev/null 2>&1 && echo yes || echo no)"
echo COOLIFY="$(docker inspect -f '{{.State.Health.Status}}' coolify 2>/dev/null)"
echo COOLIFY_DIR="$(test -d /data/coolify && echo yes || echo no)"
echo LISTEN="$(ss -Hltn 2>/dev/null | awk '$4 !~ /^(127\.|\[::1\])/ {print $4}' | sed 's/.*://' | sort -un | tr '\n' ',')"
echo PUBLIC_IP="$(curl -4 -s --max-time 6 https://ifconfig.me 2>/dev/null)"
echo LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
F="/etc/ssh/sshd_config.d/*.conf /etc/ssh/sshd_config"  # sshd keeps the first value it reads; conf.d is included first
echo SSH_PASSWORD="$(grep -hEi '^[[:space:]]*PasswordAuthentication[[:space:]]' $F 2>/dev/null | head -1 | awk '{print tolower($2)}')"
echo UFW="$(systemctl is-active ufw 2>/dev/null)"
echo UNATTENDED="$(dpkg -s unattended-upgrades >/dev/null 2>&1 && echo yes || echo no)"
"""


def ssh(target: str, command: str, timeout: int = 40) -> str:
    """Run a read-only command over ssh with key auth only (BatchMode: never prompts for a password)."""
    try:
        # The script goes to «sh -s» on stdin: same POSIX shell whatever the user's login shell (bash, zsh, fish…)
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, "sh -s"],
                           input=command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Error(f"ssh to {target} did not answer in {timeout} s") from None
    except FileNotFoundError:
        raise Error("ssh is not installed on this machine") from None
    if r.returncode != 0:
        err = r.stderr.strip()
        if "Host key verification failed" in err:
            raise Error(f"Unknown host key for {target}. Connect once by hand to check and accept it: ssh {target}")
        if "Permission denied" in err:
            raise Error(f"Key login refused by {target}. Copy your key first: ssh-copy-id {target}")
        raise Error(f"ssh to {target} failed: {err[-300:] or 'exit ' + str(r.returncode)}")
    return r.stdout


def parse_facts(text: str) -> dict:
    facts = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            facts[k.strip()] = v.strip()
    return facts


def _int(value: str | None) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def evaluate(facts: dict) -> dict:
    """Turn raw facts into checks, blockers, warnings and the install stage. Pure function (tested)."""
    checks, blockers, warnings = [], [], []

    def check(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    os_name = facts.get("OS") or "unknown"
    os_id = os_name.split()[0] if os_name.strip() else ""
    check("os", os_id in {"debian", "ubuntu", "raspbian"}, os_name)
    if os_id not in {"debian", "ubuntu", "raspbian"}:
        warnings.append(f"OS «{os_name}»: the guide assumes Debian or Ubuntu; Coolify may still work")

    arch = facts.get("ARCH", "")
    arch_ok = arch in {"x86_64", "amd64", "aarch64", "arm64"}
    check("architecture", arch_ok, arch or "unknown")
    if not arch_ok:
        blockers.append(f"architecture «{arch}»: Coolify needs a 64-bit system (x86_64 or ARM64)")

    mem = _int(facts.get("MEM_MB"))
    check("ram", mem is not None and mem >= MIN_RAM_MB, f"{mem} MB" if mem is not None else "unknown")
    if mem is not None and mem < MIN_RAM_MB:
        blockers.append(f"only {mem} MB of RAM: Coolify needs at least 2 GB")
    elif mem is not None and mem < RECOMMENDED_RAM_MB:
        warnings.append(f"{mem} MB of RAM: enough for Coolify and small apps; 4 GB is more relaxed for Node/Angular builds")

    disk = _int(facts.get("DISK_FREE_GB"))
    check("disk", disk is not None and disk >= MIN_DISK_GB, f"{disk} GB free" if disk is not None else "unknown")
    if disk is not None and disk < MIN_DISK_GB:
        warnings.append(f"only {disk} GB free on /: images and builds need room (20 GB or more recommended)")

    installed = facts.get("COOLIFY_DIR") == "yes" or bool(facts.get("COOLIFY"))
    coolify_health = facts.get("COOLIFY") or None
    listening = {p for p in (_int(x) for x in facts.get("LISTEN", "").split(",")) if p}
    busy = sorted(p for p in COOLIFY_PORTS if p in listening)
    if installed:
        check("coolify", coolify_health == "healthy", coolify_health or "installed, container not found")
    else:
        check("ports_free", not busy, "free" if not busy else f"in use: {busy}")
        if busy:
            blockers.append(f"ports {busy} are already used by another service: Coolify needs "
                            f"{COOLIFY_PORTS} (stop that service or use a clean machine)")

    docker = facts.get("DOCKER") or None
    check("docker", True if docker else None, docker or "not installed (the Coolify installer adds it)")
    if docker and facts.get("DOCKER_ACCESS") != "yes":
        warnings.append("this ssh user cannot run docker without sudo: health checks will use the HTTP endpoint only")

    pwd = facts.get("SSH_PASSWORD") or "yes (default)"
    check("ssh_password_login_disabled", pwd == "no", f"PasswordAuthentication {pwd}")
    if pwd != "no":
        warnings.append("ssh still accepts passwords: disable them (hardening, «Key-only ssh» block)")
    ufw = facts.get("UFW") == "active"
    check("firewall", ufw, "ufw active" if ufw else "ufw not active")
    if not ufw:
        warnings.append("no active ufw firewall: optional extra layer. On a VPS the provider's firewall is what "
                        "protects Docker ports (ufw does not); at home the router does. Check with «ports».")
    unattended = facts.get("UNATTENDED") == "yes"
    check("automatic_updates", unattended, "unattended-upgrades installed" if unattended else "not installed")
    if not unattended:
        warnings.append("automatic security updates are not installed (hardening, «Automatic security updates» block)")

    public_ip = facts.get("PUBLIC_IP") or None
    lan_ip = facts.get("LAN_IP") or None
    behind_nat = bool(public_ip and lan_ip and public_ip != lan_ip)

    if installed:
        stage = "installed" if coolify_health == "healthy" else "installed-unhealthy"
    else:
        stage = "not-installed"
    return {"stage": stage, "public_ip": public_ip, "lan_ip": lan_ip, "behind_nat": behind_nat,
            "cgnat_hint": ("the server sees the Internet as " + public_ip + ": compare it with the WAN IP on your "
                           "router; if they differ you are behind CGNAT and port forwarding will not work")
            if behind_nat else None,
            "checks": checks, "warnings": warnings, "blockers": blockers,
            "ready_to_install": stage == "not-installed" and not blockers,
            "listening": sorted(listening)}  # TCP ports in use, except localhost-only: candidates for «ports --private»


def cmd_diagnose(a) -> dict:
    facts = parse_facts(ssh(a.target, REMOTE_FACTS))
    return {"ok": True, "target": a.target, **evaluate(facts)}


# ---------------------------------------------------------------- dns


def doh(name: str) -> list[str]:
    """A records from a public DNS-over-HTTPS resolver (avoids local caches and router overrides)."""
    q = urllib.parse.urlencode({"name": name, "type": "A"})
    req = urllib.request.Request(f"https://dns.google/resolve?{q}", headers={"User-Agent": USER_AGENT,
                                                                            "Accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)
    return [x["data"] for x in data.get("Answer", []) if x.get("type") == 1]


def local_resolve(name: str) -> list[str]:
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(name, None, socket.AF_INET)})
    except socket.gaierror:
        return []


def evaluate_dns(domain: str, public: list[str], local: list[str], expect_ip: str | None) -> dict:
    ok = bool(public) and (expect_ip is None or expect_ip in public)
    private = [ip for ip in public if any(ipaddress.ip_address(ip) in n for n in LOCAL_NETS)]
    res = {"ok": ok and not private, "domain": domain, "wildcard_resolves": bool(public), "public_resolver": public,
           "local_resolver": local, "expected_ip": expect_ip}
    hints = []
    if not public:
        hints.append(f"*.{domain} does not resolve: add an A record «*.{domain}» pointing at the server's public IP "
                     "(or enable the wildcard in your dynamic DNS service) and wait for it to propagate")
    elif expect_ip and expect_ip not in public:
        hints.append(f"*.{domain} points at {public}, not at {expect_ip}: update the record "
                     "(or your dynamic DNS client) and wait for it to propagate")
    if private:
        hints.append(f"the public record points at a private address {private}: Let's Encrypt and visitors cannot "
                     "reach it; use the public IP")
    if public and local and set(public) != set(local):
        hints.append("this machine resolves differently from the public DNS (cache or router override); "
                     "usually harmless, it clears up on its own")
    res["hints"] = hints
    return res


def cmd_dns(a) -> dict:
    domain = a.domain.lower().strip(".").removeprefix("*.")
    probe = f"check-{secrets.token_hex(3)}.{domain}"  # a name nobody created: only a wildcard answers it
    try:
        public = doh(probe)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise Error(f"public DNS resolver unavailable: {e}") from None
    return {"probe": probe, **evaluate_dns(domain, public, local_resolve(probe), a.expect_ip)}


# ---------------------------------------------------------------- ports


def _check_host(path: str) -> dict:
    req = urllib.request.Request(f"https://check-host.net/{path}",
                                 headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def classify_tcp(results: dict) -> dict:
    """check-host TCP results → open / closed (refused: reachable but nothing listens) / filtered / unknown."""
    states = []
    for node in results.values():
        if not node:
            states.append("unknown")
            continue
        entry = node[0] if isinstance(node, list) else node
        if isinstance(entry, dict) and "address" in entry and "error" not in entry:
            states.append("open")
        elif isinstance(entry, dict) and "refused" in str(entry.get("error", "")).lower():
            states.append("closed")
        elif isinstance(entry, dict) and entry.get("error"):
            states.append("filtered")
        else:
            states.append("unknown")
    for s in ("open", "closed", "filtered"):
        if s in states:
            return {"state": s, "nodes": states}
    return {"state": "unknown", "nodes": states}


def tcp_from_internet(host: str, ports: list[int], timeout: int = 60) -> dict[int, dict]:
    """Ask check-host for every port at once, then poll until all nodes answered or the timeout expires."""
    rids = {}
    for i, port in enumerate(ports):
        if i:
            time.sleep(3)  # check-host rate-limits bursts of requests
        q = urllib.parse.urlencode({"host": f"{host}:{port}", "max_nodes": 3})
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            answer = _check_host(f"check-tcp?{q}")
            if "request_id" in answer or answer.get("error") != "limit_exceeded":
                break
            if attempt < RATE_LIMIT_RETRIES:
                time.sleep(RATE_LIMIT_WAIT)  # back off and retry instead of giving up
        if "request_id" not in answer:
            if answer.get("error") == "limit_exceeded":
                raise Error("check-host.net rate limit reached (too many checks in a short time): "
                            "wait a few minutes and try again")
            raise Error(f"check-host.net refused the check: {answer.get('error') or answer}")
        rids[port] = answer["request_id"]
    results: dict[int, dict] = {port: {} for port in ports}
    deadline = time.time() + timeout
    pending = set(ports)
    while pending and time.time() < deadline:
        time.sleep(3)
        for port in list(pending):
            data = _check_host(f"check-result/{rids[port]}")
            results[port] = data or {}
            if data and all(v is not None for v in data.values()):
                pending.discard(port)
    return {port: classify_tcp(results[port]) for port in ports}


def cmd_ports(a) -> dict:
    result, ok, hints = {}, True, []
    try:
        states = tcp_from_internet(a.host, list(a.ports) + list(a.private))
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError) as e:
        raise Error(f"check-host.net unavailable: {e}") from None
    for p in a.ports:
        r = states[p]
        result[str(p)] = r
        if r["state"] == "filtered":
            ok = False
            hints.append(f"port {p} does not reach the server from the Internet: forward it on the router "
                         "(home) or open it in the provider's firewall (VPS); behind CGNAT it cannot work")
        elif r["state"] == "closed":
            hints.append(f"port {p} reaches the server but nothing listens yet (normal before installing Coolify)")
        elif r["state"] == "unknown":
            ok = False
            hints.append(f"port {p}: check-host gave no clear answer (it may be busy), try again in a minute")
    for p in a.private:
        r = states[p]
        result[str(p)] = {**r, "should_be_private": True}
        if r["state"] == "open":
            ok = False
            hints.append(f"port {p} (Coolify panel/realtime) is open to the whole Internet: close it in the "
                         "VPS provider's firewall (ufw does not help: Docker bypasses it) or stop forwarding it "
                         "on the router, and reach the panel over the LAN, a VPN or an ssh tunnel")
        elif r["state"] != "filtered" and getattr(a, "require_filtered", False):
            ok = False
            hints.append(f"port {p} reaches the server ({r['state']}): no firewall blocks it, so it will be public as "
                         "soon as Coolify listens on it. Add the VPS provider's firewall (only 22, 80, 443) first")
    return {"ok": ok, "host": a.host, "ports": result, "hints": hints}


# ---------------------------------------------------------------- health


def http_health(url: str) -> dict:
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/health", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read(200).decode(errors="ignore").strip()
            return {"ok": r.status == 200, "code": r.status, "body": body}
    except urllib.error.HTTPError as e:
        return {"ok": False, "code": e.code}
    except (urllib.error.URLError, OSError) as e:
        return {"ok": False, "error": str(getattr(e, "reason", e))}


def parse_containers(text: str) -> dict:
    states = {name: "missing" for name in COOLIFY_CONTAINERS}
    for line in text.splitlines():
        if "=" in line:
            name, state = line.split("=", 1)
            if name in states or (name in OPTIONAL_CONTAINERS and state.strip()):
                states[name] = state.strip() or "missing"
    return states


def containers_ok(states: dict) -> bool:
    """Required containers healthy/running; optional ones only count if they exist."""
    return all(s in {"healthy", "running"} for s in states.values())


def cmd_health(a) -> dict:
    cfg = {}
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text())
        except json.JSONDecodeError:
            pass
    url, target = a.url or cfg.get("url"), a.ssh or cfg.get("ssh")
    if not url and not target:
        raise Error("Pass --url (e.g. http://192.168.1.10:8000) and/or --ssh user@host")
    res: dict = {}
    if url:
        res["http"] = {"url": url, **http_health(url)}
    if target:
        cmd = "; ".join(f"echo {c}=$(docker inspect -f '{{{{if .State.Health}}}}{{{{.State.Health.Status}}}}"
                        f"{{{{else}}}}{{{{.State.Status}}}}{{{{end}}}}' {c} 2>/dev/null)" for c in COOLIFY_CONTAINERS + OPTIONAL_CONTAINERS)
        try:
            states = parse_containers(ssh(target, cmd))
            res["containers"] = states
            res["containers_ok"] = containers_ok(states)
        except Error as e:
            res["containers_error"] = str(e)
    parts = [res.get("http", {}).get("ok")] if url else []
    if "containers_ok" in res:
        parts.append(res["containers_ok"])
    res["ok"] = bool(parts) and all(parts)
    return res


# ---------------------------------------------------------------- main


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("diagnose")
    s.add_argument("target", help="user@host")
    s = sub.add_parser("dns")
    s.add_argument("domain")
    s.add_argument("--expect-ip", dest="expect_ip")
    s = sub.add_parser("ports")
    s.add_argument("host")
    s.add_argument("--ports", nargs="*", type=int, default=[80, 443])
    s.add_argument("--private", nargs="*", type=int, default=[8000, 6001, 6002])  # panel and realtime
    s.add_argument("--require-filtered", dest="require_filtered", action="store_true",
                   help="private ports must be filtered by a firewall, not just closed (VPS before installing)")
    s = sub.add_parser("health")
    s.add_argument("--url")
    s.add_argument("--ssh")
    a = p.parse_args()
    try:
        emit({"diagnose": cmd_diagnose, "dns": cmd_dns, "ports": cmd_ports, "health": cmd_health}[a.cmd](a))
    except Error as e:
        emit({"ok": False, "error": str(e)}, 1)


if __name__ == "__main__":
    main()
