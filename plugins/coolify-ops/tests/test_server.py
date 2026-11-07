"""Tests for provision-server's server.py (pure functions; no ssh, no network)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "provision-server" / "scripts"))

import server  # noqa: E402

FRESH_VPS = """OS=ubuntu 24.04
ARCH=x86_64
CPUS=2
MEM_MB=3900
DISK_FREE_GB=70
DISK_USED_PCT=5
DOCKER=
DOCKER_ACCESS=no
COOLIFY=
COOLIFY_DIR=no
LISTEN=22,53,
PUBLIC_IP=203.0.113.10
LAN_IP=203.0.113.10
SSH_PASSWORD=no
UFW=active
UNATTENDED=yes
"""


def facts(**changes) -> dict:
    f = server.parse_facts(FRESH_VPS)
    f.update(changes)
    return f


def names(result: dict, ok: bool) -> set[str]:
    return {c["name"] for c in result["checks"] if c["ok"] is ok}


# ------------------------------------------------------------------ diagnose


def test_clean_vps_is_ready_to_install():
    r = server.evaluate(facts())
    assert r["stage"] == "not-installed"
    assert r["ready_to_install"] and not r["blockers"] and not r["warnings"]
    assert not r["behind_nat"] and r["cgnat_hint"] is None


def test_32_bit_and_low_ram_block():
    r = server.evaluate(facts(ARCH="armv7l", MEM_MB="900"))
    assert not r["ready_to_install"]
    assert any("64-bit" in b for b in r["blockers"])
    assert any("RAM" in b for b in r["blockers"])


def test_busy_ports_block_only_before_installing():
    r = server.evaluate(facts(LISTEN="22,80,443,"))
    assert any("[80, 443]" in b for b in r["blockers"])
    installed = server.evaluate(facts(LISTEN="22,80,443,8000,", COOLIFY="healthy", COOLIFY_DIR="yes"))
    assert installed["stage"] == "installed" and not installed["blockers"]


def test_unhealthy_install_is_reported():
    r = server.evaluate(facts(COOLIFY="unhealthy", COOLIFY_DIR="yes"))
    assert r["stage"] == "installed-unhealthy"
    assert "coolify" in names(r, False)


def test_hardening_warnings():
    r = server.evaluate(facts(SSH_PASSWORD="", UFW="inactive", UNATTENDED="no"))
    assert {"ssh_password_login_disabled", "firewall", "automatic_updates"} <= names(r, False)
    assert len(r["warnings"]) == 3
    assert r["ready_to_install"]  # warnings never block


def test_home_server_gets_cgnat_hint():
    r = server.evaluate(facts(PUBLIC_IP="198.51.100.7", LAN_IP="192.168.1.20"))
    assert r["behind_nat"] and "198.51.100.7" in r["cgnat_hint"]


def test_missing_facts_do_not_crash():
    r = server.evaluate({})
    assert r["stage"] == "not-installed"
    assert any("architecture" in b for b in r["blockers"])


# ------------------------------------------------------------------ dns


def test_dns_ok_and_mismatch():
    assert server.evaluate_dns("example.org", ["203.0.113.10"], ["203.0.113.10"], "203.0.113.10")["ok"]
    wrong = server.evaluate_dns("example.org", ["203.0.113.99"], [], "203.0.113.10")
    assert not wrong["ok"] and "not at 203.0.113.10" in wrong["hints"][0]


def test_dns_missing_wildcard_and_private_ip():
    missing = server.evaluate_dns("example.org", [], [], None)
    assert not missing["ok"] and "*.example.org" in missing["hints"][0]
    private = server.evaluate_dns("example.org", ["192.168.1.20"], [], None)
    assert not private["ok"] and any("private" in h for h in private["hints"])


def test_dns_strips_wildcard_prefix(monkeypatch):
    seen = []
    monkeypatch.setattr(server, "doh", lambda name: seen.append(name) or ["203.0.113.10"])
    monkeypatch.setattr(server, "local_resolve", lambda name: [])
    r = server.cmd_dns(argparse.Namespace(domain="*.Example.org.", expect_ip=None))
    assert r["domain"] == "example.org" and seen[0].endswith(".example.org") and r["ok"]


# ------------------------------------------------------------------ ports


def test_classify_tcp_states():
    assert server.classify_tcp({"a": [{"time": 0.1, "address": "1.2.3.4"}], "b": None})["state"] == "open"
    assert server.classify_tcp({"a": [{"error": "Connection refused"}]})["state"] == "closed"
    assert server.classify_tcp({"a": [{"error": "Connection timed out"}]})["state"] == "filtered"
    assert server.classify_tcp({"a": None, "b": None})["state"] == "unknown"


def test_public_panel_is_flagged(monkeypatch):
    states = {80: "open", 443: "open", 8000: "open"}
    monkeypatch.setattr(server, "tcp_from_internet", lambda host, p: {"state": states[p], "nodes": [states[p]]})
    r = server.cmd_ports(argparse.Namespace(host="example.org", ports=[80, 443], private=[8000]))
    assert not r["ok"] and any("8000" in h for h in r["hints"])


def test_closed_before_install_is_fine(monkeypatch):
    monkeypatch.setattr(server, "tcp_from_internet", lambda host, p: {"state": "filtered" if p == 8000 else "closed"})
    r = server.cmd_ports(argparse.Namespace(host="example.org", ports=[80, 443], private=[8000]))
    assert r["ok"]


# ------------------------------------------------------------------ health


def test_containers_required_and_optional():
    states = server.parse_containers("coolify=healthy\ncoolify-db=healthy\ncoolify-redis=healthy\n"
                                     "coolify-proxy=running\ncoolify-realtime=\ncoolify-sentinel=healthy\n")
    assert "coolify-realtime" not in states and states["coolify-sentinel"] == "healthy"
    assert server.containers_ok(states)
    assert not server.containers_ok(server.parse_containers("coolify=healthy\n"))  # db, redis, proxy missing


def test_health_needs_url_or_ssh(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "CONFIG", tmp_path / "none.json")
    with pytest.raises(server.Error):
        server.cmd_health(argparse.Namespace(url=None, ssh=None))


def test_ssh_explains_unknown_host_key(monkeypatch):
    class R:
        returncode, stdout, stderr = 255, "", "Host key verification failed."
    monkeypatch.setattr(server.subprocess, "run", lambda *a, **k: R())
    with pytest.raises(server.Error, match="accept it"):
        server.ssh("user@host", "true")
