---
name: provision-server
description: Guide the user step by step through setting up a self-hosted Coolify server (VPS or home server) and connecting it to Claude Code — read-only diagnosis over SSH, wildcard DNS, ports reachable from the Internet, hardening, the official install, admin account, GitHub App, API token — checking every step and never handling passwords or sudo. Use when the user wants to install or set up Coolify, prepare a server or VPS for self-hosting, check the health or Internet exposure (open ports, DNS) of an existing Coolify server, or when deploy-app finds no Coolify configuration. Also triggers on Spanish requests such as «instala Coolify», «prepara mi servidor» or «monta Coolify en mi VPS».
argument-hint: "[user@host] [domain] | diagnose <user@host> | check"
allowed-tools: Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 -I ${CLAUDE_SKILL_DIR}/../deploy-app/scripts/coolify.py *), Bash(python3 -I ${CLAUDE_SKILL_DIR}/../deploy-app/scripts/verify.py *)
---

# Provision a Coolify server

Takes the user from a bare machine to a Coolify server that `deploy-app` can use. It follows the written guide «Coolify from scratch»
(https://github.com/xavieraijon/aijon-labs/blob/main/docs/en/coolify-from-scratch.md; Spanish:
https://github.com/xavieraijon/aijon-labs/blob/main/docs/es/coolify-desde-cero.md) and **checks** each step
instead of trusting it was done. The guide is not installed with the plugin: every block the user must run
(hardening, webhook proxy configuration, example app) is in `${CLAUDE_SKILL_DIR}/reference/server-setup.md` —
use those exact blocks, never write them from memory.

Scripts (all print JSON, all read-only):

| Command | Purpose |
|---|---|
| `S diagnose <user@host>` | OS, architecture, RAM, disk, Docker, Coolify state, ports in use, ssh password login, firewall, automatic updates, public/LAN IP |
| `S dns <domain> [--expect-ip IP]` | Does a random `*.domain` name resolve on a public resolver, and to which IP |
| `S ports <host> [--ports 80 443] [--private 8000 6001 6002] [--require-filtered]` | TCP reachability from 3 check-host.net nodes abroad: `open`, `closed` (reaches the server, nothing listens), `filtered` (blocked). `--require-filtered` (VPS): private ports must be `filtered`, not just not open |
| `S health [--url URL] [--ssh user@host]` | `/api/health` answers and Coolify's containers are healthy |
| `C check`, `C init …` | Coolify API (from `deploy-app`): token valid, server and GitHub App discovered |

`S` = `python3 -I ${CLAUDE_SKILL_DIR}/scripts/server.py`, `C` = `python3 -I ${CLAUDE_SKILL_DIR}/../deploy-app/scripts/coolify.py`.
**Always type the full command.**

**Language:** talk to the user in the language they write in; script output is English, translate it.

## Fixed rules

1. **Never run anything with `sudo` and never ask for, receive or type a password.** Commands that need root are
   given to the user to run **in their own terminal, inside an `ssh` session** — not with `!`, because `!` cannot
   answer a password prompt. Then verify with a script. If the user pastes or offers a password: do not repeat it,
   use it or store it; tell them to change it, since it is now in the chat history; and go on with key login
   (they run `ssh-copy-id` themselves, see `reference/server-setup.md`).
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
(own domain or a dynamic DNS name such as DuckDNS). If they have no domain yet, explain the two options — a
domain of their own with a wildcard `A` record `*.domain` → public IP, or a free dynamic DNS name with wildcard
support such as DuckDNS (best for a home server whose IP changes) — and continue with A–B meanwhile.
If ssh does not work yet: no key pair or only a root password → the blocks «No ssh key yet» and «Key-only ssh»
of `reference/server-setup.md`; for an unknown host key, rule 3.

### B · Diagnose
`S diagnose <user@host>` and present `checks` as a ✔/✘ table, then `blockers` and `warnings`.
- `blockers` (32-bit system, < 2 GB RAM, Coolify ports taken by another service): stop and explain.
- `stage` = `installed` → Coolify is already there, but the earlier phases may not be done. Still: offer C if its
  warnings apply; run D1 (DNS) and D3 (ports); ask the user to confirm the admin account exists (if not, step E's
  «immediately» applies now). Then `C check`: `ok` → the API is connected, skip to G (or H if `C init` also
  succeeds); no configuration or an error → continue at F. `installed-unhealthy` → `S health --ssh …` and show what
  is wrong (see troubleshooting) before anything else.
- Home server (`behind_nat`): show `cgnat_hint` and ask the user to compare with their router's WAN IP. CGNAT
  means port forwarding cannot work: stop and explain the options («CGNAT» in `reference/server-setup.md`).
  On a VPS ignore `behind_nat`: some providers use NAT, and the provider's public IP is the one that counts.

### C · Harden (if warnings mention ssh passwords, firewall or automatic updates)
Give the user the blocks «Key-only ssh», «Automatic security updates» and «Firewall» from
`reference/server-setup.md`, only the lines they still need, to run in their own ssh
session. Warn before the ssh line: they must have key login working first or they will lock themselves out
(keeping the current session open while testing a new one is the safe way).
**Docker bypasses ufw**: Coolify's panel (8000) and realtime ports (6001, 6002) stay reachable even with ufw.
On a **VPS** the real protection is the **provider's firewall** allowing only 22, 80 and 443 — make sure the user
sets it; ufw is only an extra layer. On a **home server** the router already blocks everything but the forwarded
ports, so a missing ufw is just a warning. Never tell the user ufw protects the panel.
If the user created a new account (e.g. `deploy`), check that key login works for it, then use `<newuser>@host`
for **every** later command and for `--ssh` (never keep `root@host` in the configuration).
Then `S diagnose …` again (with the new user if there is one) and show the new ✔.

### D · DNS and ports
1. `S dns <domain> --expect-ip <public_ip from B>` → if not ok, follow `hints` (wildcard record, dynamic DNS
   client, propagation). The wildcard record must be **DNS only, not proxied** (Cloudflare: grey cloud): a proxied
   record answers with the proxy's addresses, and every later check would test the proxy instead of the server.
   Home server with a changing IP: the updater is the user's — the router's dynamic DNS setting or the
   «Dynamic DNS (home)» block in `reference/server-setup.md`; never write one from memory, never ask for the
   token in the chat. Re-check when the user says it is done.
2. Home server: in the router, reserve the server's LAN IP (`lan_ip` from B) in DHCP («DHCP reservation» /
   «static lease»), then forward **only** TCP 80 → `<lan_ip>`:80 and TCP 443 → `<lan_ip>`:443 (menu usually
   called «Port forwarding», «Virtual server» or «NAT»); never a range and never the panel port. VPS: the
   provider's firewall allows 22, 80 and 443 only.
3. `S ports <public_ip from B>` (the bare base domain may not point at the server: only `*.domain` does; checks
   80/443 open and 8000, 6001, 6002 private; pass `--private <port> 6001 6002` if the panel uses another port).
   **On a VPS add `--require-filtered`.**
   - before installing, `closed` on 80/443 is the **good** answer (reaches the server, nothing listens yet);
     `filtered` means the forward/firewall is missing.
   - the panel ports must not be `open`. On a VPS before installing they must be **`filtered`**: `closed` means
     the packets reach the machine, so there is no provider firewall and the panel would be public the moment
     Coolify starts. Do not go to E until they are `filtered` (ufw does not help: Docker bypasses it).

### E · Install Coolify
Give the user the official command to run in their own ssh session:
```
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```
Explain it takes a few minutes and installs Docker if needed. When they say it finished:
`S health` until `ok` (allow a couple of minutes): home server `--url http://<lan_ip>:8000 --ssh <user@host>`;
**VPS** `--ssh <user@host>` only (port 8000 is closed by the firewall), or `--url http://localhost:8000` while the
user's ssh tunnel (below) is open. Read the parts separately: `http.ok` (panel answers) and `containers_ok`; a
`containers_error` means the ssh user cannot run `docker` (not in the docker group): `ok` then never becomes true
with `--ssh` alone. Either the user adds the docker group (`usermod -aG docker <user>` from «Key-only ssh», with
its warning) and you re-run, or, on a VPS, check with `--url http://localhost:8000` while their ssh tunnel is
open and rely on `http.ok`.
Then, **immediately**, the user opens the panel (LAN, VPN, or on a VPS an ssh tunnel:
`ssh -L 8000:localhost:8000 -L 6001:localhost:6001 -L 6002:localhost:6002 user@host` and `http://localhost:8000`)
and creates the admin account — whoever opens it first owns it — and picks **this machine** (`localhost`) in the
onboarding. Tell them not to give the panel a public domain.
Re-run `S ports …`: 80/443 should now be `open`, 8000/6001/6002 not.

### F · Connect the API
Browser steps for the user:
1. *Settings → Advanced* (`/settings/advanced`): **API access** on, *Allowed IPs* = the network Claude Code
   calls from (home: the LAN, e.g. `192.168.1.0/24`; **VPS: `100.64.0.0/10`**, the private network set up in
   step 2 below), **Save**.
2. *Keys & Tokens → API Tokens* (`/security/api-tokens`): create a token with `read`, `read:sensitive` (logs), `write`, `deploy`,
   `delete`.
   **VPS:** the API shares the panel's port, which the firewall closes, so Claude Code needs a private network to
   reach it: follow «Private network for the API (VPS)» in `reference/server-setup.md` (Tailscale; URL
   `http://<server's tailnet address>:8000`, *Allowed IPs* = `100.64.0.0/10`). Do not suggest opening 8000 to the
   Internet, and do not rely on the ssh tunnel for the API (untested with *Allowed IPs*).
3. Store the token **without pasting it in the chat**. Copy it, then:
   - macOS: `! security add-generic-password -U -a "$USER" -s coolify-api-token -w "$(pbpaste)" && pbcopy < /dev/null`
   - Linux and others: in their own terminal, `mkdir -p ~/.config/coolify-ops && chmod 700 ~/.config/coolify-ops`
     and `nano ~/.config/coolify-ops/token && chmod 600 ~/.config/coolify-ops/token` (paste, save).
4. Verify: `C init --url http://<panel address>:<port> --domain <domain> --ssh <user@host>` will fail with «No
   private GitHub App» until G is done — that failure already proves the token and the API work. Any other error
   (401, 403, connection) → see troubleshooting and fix it first.

### G · GitHub App and webhooks
The panel stays private, so only the webhook path is published, on the reserved subdomain `hooks`:
1. The user adds the configuration «GitHub webhooks only» from `reference/server-setup.md` (*Servers → localhost →
   Proxy → Dynamic Configurations*), with their domain in the `Host` rule. The user checks it **from outside
   their network** as that section explains: it must **not** answer 200. If Coolify's login shows, stop: the panel
   is exposed.
2. *Sources → Add → GitHub App*, create it on GitHub, install it on the repos to deploy only.
3. On GitHub, the app's **Webhook URL** = `https://hooks.<domain>/webhooks/source/github/events`.
Ask where they keep their projects (default `~/Projects`). Verify: `C init --url … --domain … --ssh … --reserved hooks [--projects-dir <folder>]` → `ok`; its `projects_dir` is the `<projects_dir>` of H.

### H · First deployment
Hand over to `deploy-app`: suggest the example app — the user copies it into its own folder with the commands
in «Example app» of `reference/server-setup.md` (`deploy-app` then gives the user the command to create its GitHub
repository) — or a project of theirs.
After it works: `python3 -I ${CLAUDE_SKILL_DIR}/../deploy-app/scripts/verify.py --server` for the final health
picture. Offer to decommission the example app afterwards (through `deploy-app`, which confirms first).

## Wrap-up
Summarize: server (OS, arch, RAM), domain, what is public (80/443) and private (panel), Coolify version
(`C check`), and the pending recommendations (e.g. server backups, «Backups and maintenance» in the guide).

## Modes
| Request | What to do |
|---|---|
| `diagnose <user@host>` | Phase B only, read-only, no follow-up questions |
| `check`, «which ports are open?» | `C check` gives `url`, `base_domain` and `ssh` (the panel port is the port in `url`), also when it fails for another reason than a missing configuration (`ok: false` with `error`: show the API row as ✘ with it and go on). Ask «VPS or home server?» unless the user said it. Then: `S health --url <url> --ssh <ssh>`; `S diagnose <ssh>` for the server's `public_ip` and `listening` (TCP ports in use); `S dns <base_domain> --expect-ip <public_ip>` (a different answer — e.g. a proxied record — is its own ✘ row; explain it as in D1, not as a wrong IP); `S ports <public_ip>` with `--private <panel port> 6001 6002 <the other `listening` ports except 22, 80, 443>` and, on a VPS, `--require-filtered`. check-host.net limits bursts: at most **8 ports per `S ports` run** (80, 443 and the panel ports first); with more, run the rest in another run a few minutes later. One ✔/✘ table that **names the ports tested** (others were not). No `ssh`: skip `health --ssh` and `diagnose`, ask the user for the server's public IP (router status page at home, provider console on a VPS) and use it for `S dns --expect-ip` and `S ports`, and show those rows as ✘ «no ssh in the configuration». **No configuration** (`C check` fails for that reason): ask for the base domain and `user@host` (and the panel URL if they know it), run the `S` commands with them, and show the API row as «not configured» (offer phase F) — do not run `C init` in this read-only mode |

See also `${CLAUDE_SKILL_DIR}/../deploy-app/reference/troubleshooting.md`.
