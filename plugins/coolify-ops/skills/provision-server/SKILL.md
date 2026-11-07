---
name: provision-server
description: Guide the user step by step through setting up a self-hosted Coolify server (VPS or home server) and connecting it to Claude Code — read-only diagnosis over SSH, wildcard DNS, ports reachable from the Internet, hardening, the official install, admin account, GitHub App, API token — checking every step and never handling passwords or sudo. Use when the user wants to install or set up Coolify, prepare a server or VPS for self-hosting, or when deploy-app finds no Coolify configuration. Also triggers on Spanish requests such as «instala Coolify», «prepara mi servidor» or «monta Coolify en mi VPS».
argument-hint: "[user@host] [domain] | diagnose <user@host> | check"
allowed-tools: Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 -I ${CLAUDE_SKILL_DIR}/../deploy-app/scripts/coolify.py *), Bash(python3 -I ${CLAUDE_SKILL_DIR}/../deploy-app/scripts/verify.py *)
---

# Provision a Coolify server

Takes the user from a bare machine to a Coolify server that `deploy-app` can use. It follows the written guide
(`docs/en/coolify-from-scratch.md` in the repo root, `docs/es/coolify-desde-cero.md` in Spanish) and **checks**
each step instead of trusting it was done.

Scripts (all print JSON, all read-only):

| Command | Purpose |
|---|---|
| `S diagnose <user@host>` | OS, architecture, RAM, disk, Docker, Coolify state, ports in use, ssh password login, firewall, automatic updates, public/LAN IP |
| `S dns <domain> [--expect-ip IP]` | Does a random `*.domain` name resolve on a public resolver, and to which IP |
| `S ports <host> [--ports 80 443] [--private <panel port>]` | TCP reachability from 3 countries (check-host.net): `open`, `closed` (reaches the server, nothing listens), `filtered` (blocked) |
| `S health [--url URL] [--ssh user@host]` | `/api/health` answers and Coolify's containers are healthy |
| `C check`, `C init …` | Coolify API (from `deploy-app`): token valid, server and GitHub App discovered |

`S` = `python3 -I ${CLAUDE_SKILL_DIR}/scripts/server.py`, `C` = `python3 -I ${CLAUDE_SKILL_DIR}/../deploy-app/scripts/coolify.py`.
**Always type the full command.**

**Language:** talk to the user in the language they write in; script output is English, translate it.

## Fixed rules

1. **Never run anything with `sudo` and never ask for, receive or type a password.** Commands that need root are
   given to the user to run **in their own terminal, inside an `ssh` session** — not with `!`, because `!` cannot
   answer a password prompt. Then verify with a script.
2. **Never change the server yourself.** The only remote commands are the scripts' read-only ones over ssh with
   key authentication (`BatchMode`, it never prompts).
3. **Never accept an unknown ssh host key on the user's behalf.** If the script says the key is unknown, ask the
   user to connect once by hand (`ssh user@host`) and check the fingerprint.
4. **Browser steps are the user's** (admin account, GitHub App, API settings, token). Explain exactly where to
   click, then verify through the API. Never automate the browser.
5. **The API token never goes through the chat.** Give the user the command to store it (step F).
6. **One phase at a time.** At the end of each phase, show what was verified (✔/✘) and ask before moving on.
   Skip phases already done (a server with Coolify healthy jumps straight to F).
7. Never open router ports, never make the Coolify panel public, never disable a firewall.

## Phases

### A · Gather
Ask (in one message) only what is missing: VPS or home server, `user@host` for ssh, and the domain they will use
(own domain or a dynamic DNS name such as DuckDNS). If they have no domain yet, explain the two options from step 3
of the guide and continue with A–B meanwhile.
If ssh does not work yet: for a key error give `ssh-copy-id user@host`; for an unknown key, rule 3.

### B · Diagnose
`S diagnose <user@host>` and present `checks` as a ✔/✘ table, then `blockers` and `warnings`.
- `blockers` (32-bit system, < 2 GB RAM, Coolify ports taken by another service): stop and explain.
- `stage` = `installed` → tell the user and jump to F. `installed-unhealthy` → `S health --ssh …` and show what
  is wrong (see troubleshooting) before anything else.
- Home server (`behind_nat`): show `cgnat_hint` and ask the user to compare with their router's WAN IP. CGNAT
  means port forwarding cannot work: stop and explain the options from step 2 of the guide.

### C · Harden (if warnings mention ssh passwords, firewall or automatic updates)
Give the user the block from step 4 of the guide, only the lines they still need, to run in their own ssh
session. Warn before the ssh line: they must have key login working first or they will lock themselves out
(keeping the current session open while testing a new one is the safe way).
On a **home server**, the router already blocks everything but the forwarded ports, so a missing ufw is a
warning, not a requirement; on a **VPS** recommend it strongly (or the provider's firewall).
Then `S diagnose …` again and show the new ✔.

### D · DNS and ports
1. `S dns <domain> --expect-ip <public_ip from B>` → if not ok, follow `hints` (wildcard record, dynamic DNS
   client, propagation). Re-check when the user says it is done.
2. Home server: ask the user to forward **80 and 443 only** to the server's LAN IP (`lan_ip` from B) on their
   router (and to reserve that IP in DHCP). VPS: usually nothing to do.
3. `S ports <domain or public IP> --private <panel port, 8000 by default>`:
   - before installing, `closed` on 80/443 is the **good** answer (reaches the server, nothing listens yet);
     `filtered` means the forward/firewall is missing.
   - the panel port must not be `open`.

### E · Install Coolify
Give the user the official command to run in their own ssh session:
```
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```
Explain it takes a few minutes and installs Docker if needed. When they say it finished:
`S health --url http://<lan or public IP>:8000 --ssh <user@host>` until `ok` (allow a couple of minutes).
Then, **immediately**, the user opens the panel (LAN, VPN or `ssh -L 8000:localhost:8000 user@host` and
`http://localhost:8000`) and creates the admin account — whoever opens it first owns it.
Re-run `S ports … --private 8000`: 80/443 should now be `open`, 8000 not.

### F · Connect the API
Browser steps for the user (step 8 of the guide):
1. *Settings → Advanced → API access* on, and *Allowed IPs* = the network Claude Code runs from.
2. *Security → API tokens → Create* with `read`, `write`, `deploy` and `delete`.
3. Store the token **without pasting it in the chat**. Copy it, then:
   - macOS: `! security add-generic-password -U -a "$USER" -s coolify-api-token -w "$(pbpaste)" && pbcopy < /dev/null`
   - Linux and others: `! umask 077 && mkdir -p ~/.config/coolify-ops && <paste command of their clipboard tool> > ~/.config/coolify-ops/token`
     (e.g. `xclip -o -selection clipboard`, `wl-paste`), or ask them to create the file with their editor.
4. Verify: `C init --url http://<panel address>:<port> --domain <domain> --ssh <user@host>` will fail with «No
   private GitHub App» until G is done — that failure already proves the token and the API work. Any other error
   (401, 403, connection) → see troubleshooting and fix it first.

### G · GitHub App
Browser steps (step 7 of the guide): *Sources → Add → GitHub App*, create it on GitHub, install it on the repos to
deploy, and set the **Webhook URL** to a **public** address ending in `/webhooks/source/github/events`.
Verify: `C init --url … --domain … --ssh … [--reserved <subdomains to keep>] [--projects-dir <folder>]` → `ok`.

### H · First deployment
Hand over to `deploy-app`: suggest the example app of this repo — the user copies it into its own folder
(`cp -r <repo>/examples/hello-fastapi <projects_dir>/hello-fastapi`, the skill then creates its GitHub repo) —
or a project of theirs.
After it works: `python3 -I ${CLAUDE_SKILL_DIR}/../deploy-app/scripts/verify.py --server` for the final health
picture. Offer to decommission the example app afterwards (through `deploy-app`, which confirms first).

## Wrap-up
Summarize: server (OS, arch, RAM), domain, what is public (80/443) and private (panel), Coolify version
(`C check`), and the pending recommendations (e.g. backups, step 10 of the guide).

## Modes
| Request | What to do |
|---|---|
| `diagnose <user@host>` | Phase B only, read-only, no follow-up questions |
| `check` | `S health`, `C check`, `S dns <base_domain>`, `S ports <base_domain> --private <panel port>` with the values of `~/.config/coolify-ops/config.json`; one ✔/✘ table |

See also `${CLAUDE_SKILL_DIR}/../deploy-app/reference/troubleshooting.md`.
