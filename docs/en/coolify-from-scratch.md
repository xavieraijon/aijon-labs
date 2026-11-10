# Coolify from scratch

A step-by-step guide to running your own [Coolify](https://coolify.io) server — a self-hosted alternative to
Heroku/Vercel — so you can later use the `coolify-ops` plugin to deploy your projects to it. You do not need to
know Docker or server administration beforehand; every command is given in full.

The `provision-server` skill of this plugin follows this same guide with you: it checks each step (read-only
diagnosis, DNS, ports seen from the Internet, Coolify health) and walks you through the ones that need your
`sudo` password or a browser — which it never does for you. This guide also works by itself, by hand.

## 1 · What you need

**The server**
- A machine that stays on: a **VPS** (a few euros/dollars a month) or a **computer at home** (a Raspberry Pi 4/5,
  an old laptop, a mini-PC). 2 GB of RAM is the minimum for Coolify itself plus small apps; 4 GB is more relaxed
  if you plan to build Node or Angular apps on it. 20 GB of free disk or more.
- A 64-bit CPU: x86_64 or ARM64 both work (Coolify and this plugin's Docker templates support both).
- Debian or Ubuntu (other Linux distributions mostly work too; this guide assumes one of these two).
- `ssh` access as a user who can run `sudo`.
- A domain name you control, even a free one (step 3).

**Your own computer** (where Claude Code runs)
- [Claude Code](https://code.claude.com), Python 3.10+, `git`, the GitHub CLI [`gh`](https://cli.github.com)
  signed in (`gh auth login`) and Docker (Docker Desktop on macOS/Windows) for the local build check.
- The plugin, from Claude Code:
  ```
  /plugin marketplace add xavieraijon/aijon-labs
  /plugin install coolify-ops@aijon-labs
  ```

## 2 · Choose where it runs

| | VPS | Home server |
|---|---|---|
| Public IP | Fixed, given by the provider | Usually changes; needs dynamic DNS |
| Setup | Faster: nothing to configure on a router | You forward two ports on your router |
| Firewall | The **provider's firewall** (step 4) | Your router: only what you forward is reachable |
| Cost | Monthly fee | Electricity only, hardware you may already own |
| Reliability | Provider's uptime | Depends on your power and internet |

**On a VPS**, any provider that gives you root SSH access to a fresh Debian/Ubuntu machine works. Note its public
IP; you will point your domain at it. Pick one that offers a **network firewall** in its control panel (most do:
Hetzner, DigitalOcean, Vultr, OVH, AWS, …) — you will need it in step 4.

**At home**, check these before anything else:
- **You are not behind CGNAT.** Some ISPs do not give you a real public IP. From the server, run
  `curl -4 ifconfig.me` and compare it with the WAN IP on your router's status page. If they differ, you are
  behind CGNAT and port forwarding cannot work: ask your ISP for a public IP (often free on request) or use a
  tunnel (e.g. Cloudflare Tunnel, outside the scope of this guide).
- **Give the server a fixed address on your LAN** (a DHCP reservation in the router) so port forwarding keeps
  working after a reboot.
- **Forward ports 80 and 443 only** on your router to that LAN address. Never forward Coolify's panel port.
- To open your apps from inside your own network by their public name, the router needs **NAT loopback**
  (hairpinning). Most routers support it; if `https://<your-domain>` does not load from inside the LAN but works
  from your phone's mobile data, that is the reason.

## 3 · DNS: a domain with a wildcard

You need one domain that resolves to the server, with a **wildcard** record so that every app gets its own
subdomain automatically (`shop.example.org`, `blog.example.org`, …) without touching DNS again.

- **Your own domain** (recommended if you plan to keep this server): at your DNS provider, add an `A` record
  `*.example.org` pointing at the server's public IP. One record covers every future subdomain.
- **Free option**: [DuckDNS](https://www.duckdns.org) gives you `yourname.duckdns.org`, where every subdomain
  (`*.yourname.duckdns.org`) resolves too, plus a small client that keeps the IP updated if it changes — useful
  at home. Any dynamic DNS service with wildcard support works the same way.

Wait for it to propagate (minutes to a couple of hours) and check it:
```bash
dig +short anything.example.org
```
It must print the server's **public** IP.

## 4 · Harden the server first

Do this before installing Coolify. Run it in an ssh session on the server.

**SSH with keys only.** First, from your own computer, copy your key and check that it logs you in without a
password:
```bash
ssh-copy-id user@server
ssh user@server            # must not ask for the account password
```
Then, on the server, disable password logins with a drop-in file (on many VPS images a file in
`/etc/ssh/sshd_config.d/` sets `PasswordAuthentication yes`, and sshd keeps the first value it reads, so editing
`sshd_config` alone is not enough; the `00-` prefix makes this file win):
```bash
echo "PasswordAuthentication no" | sudo tee /etc/ssh/sshd_config.d/00-key-only.conf
sudo systemctl restart ssh
```
Keep that session open and check from a **new** terminal that you can still log in before closing it.

**Firewall.** Important: **Docker bypasses `ufw`.** Ports published by containers — Coolify's panel (8000) and
its realtime ports (6001, 6002) — stay reachable from the Internet even if `ufw` says they are closed. So:
- **VPS:** use the **provider's firewall** (it filters before traffic reaches the machine) and allow only
  inbound **22, 80 and 443**. You may still enable `ufw` as an extra layer for non-Docker services.
- **Home server:** your router already blocks everything except the ports you forward (80 and 443). `ufw` is
  optional.

**Automatic security updates:**
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

## 5 · Install Coolify

Coolify installs with one official script, which also installs Docker if it is missing:
```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```
It takes a few minutes and prints a URL like `http://<server-ip>:8000` at the end.

**Create the admin account immediately** — whoever opens the panel first can register it. Open it:
- **Home server:** from your LAN, `http://<server-lan-ip>:8000`.
- **VPS:** the panel is (and should stay) closed by the provider's firewall, so open it through an ssh tunnel:
  ```bash
  ssh -L 8000:localhost:8000 -L 6001:localhost:6001 -L 6002:localhost:6002 user@server
  ```
  and browse to `http://localhost:8000` while that session is open (6001/6002 carry live logs and the terminal).

In the onboarding, choose to deploy on **this machine** (`localhost`). Do **not** give the panel itself a public
domain in Coolify's settings unless you want the whole panel reachable from the Internet.

## 6 · Proxy and HTTPS

Coolify runs a reverse proxy (Traefik) that requests and renews Let's Encrypt certificates automatically for
every app domain, as long as ports 80 and 443 reach the server and the DNS resolves (steps 2–3). You never
configure certificates by hand.

Known rough edge: if a certificate request failed because the ports were not open yet, Traefik may not retry by
itself. Restart it (on the server):
```bash
docker restart coolify-proxy
```

## 7 · Connect GitHub

Coolify deploys from GitHub through a **GitHub App** — limited to the repositories you choose — and redeploys on
every push thanks to its **webhooks**. GitHub must be able to reach one URL on your server, but the panel must
stay private, so we publish **only the webhook path** on a dedicated subdomain, `hooks`.

1. **Expose only the webhook.** In Coolify: *Servers → localhost → Proxy → Dynamic Configurations → Add*, name
   it `github-webhooks.yaml` and paste (replace `example.org` with your domain):
   ```yaml
   http:
     routers:
       github-webhooks:
         entryPoints: [https]
         rule: "Host(`hooks.example.org`) && Path(`/webhooks/source/github/events`) && Method(`POST`)"
         service: github-webhooks
         tls:
           certResolver: letsencrypt
     services:
       github-webhooks:
         loadBalancer:
           servers:
             - url: "http://coolify:8080"
   ```
   Any other path on `hooks.example.org` returns an error page: the panel is not exposed. Check it **from
   outside your network** — on a home server, a check from inside the LAN goes through NAT loopback and proves
   nothing. Open `https://hooks.example.org/` on your phone with Wi-Fi off, or run from any machine outside it
   `curl -s -o /dev/null -w '%{http_code}\n' https://hooks.example.org/`. Expected: an error code (404 or 503),
   **never 200** and never Coolify's login page. If the login page shows, remove the configuration and check the
   `rule` line.
2. **Create the GitHub App.** *Sources → Add → GitHub App*, follow the link to GitHub and let it create the app;
   Coolify receives the credentials automatically. Install it on your account choosing **only the repositories**
   you will deploy (you can add more later).
3. **Point the webhooks at the public URL.** On GitHub: *Settings → Developer settings → GitHub Apps → your app →
   Webhook URL* = `https://hooks.example.org/webhooks/source/github/events`. Save.

From now on, `hooks` is a reserved subdomain: never deploy an app on it (step 9 tells the plugin).

## 8 · Enable the API

The plugin talks to Coolify only through its API, which is served on the **same port as the panel**.

1. *Settings → Advanced* (`/settings/advanced`), section *API*: enable **API access** and set **Allowed IPs** to
   the network Claude Code calls from — e.g. your LAN `192.168.1.0/24` (home), or your VPN range (VPS, below).
   Press **Save**.
2. *Keys & Tokens → API Tokens* (`/security/api-tokens`): create a token with **`read`, `read:sensitive`,
   `write`, `deploy` and `delete`**. `delete` is separate from `write` (without it every delete returns 403), and
   `read:sensitive` is needed to read an app's logs; permissions cannot be edited later — if you forget one,
   create a new token.
3. Copy the token (it is shown only once) and store it **without pasting it into the chat or the shell history**:
   - **macOS** (Keychain), right after copying:
     ```bash
     security add-generic-password -U -a "$USER" -s coolify-api-token -w "$(pbpaste)" && pbcopy < /dev/null
     ```
   - **Linux and others**: create the file with your editor, paste the token, save:
     ```bash
     mkdir -p ~/.config/coolify-ops && chmod 700 ~/.config/coolify-ops
     nano ~/.config/coolify-ops/token && chmod 600 ~/.config/coolify-ops/token
     ```

**VPS: how Claude Code reaches the API.** With the panel closed by the firewall, your computer cannot reach port
8000 either. The simplest safe option is a private network between your computer and the server, such as
[Tailscale](https://tailscale.com) or WireGuard: install it on both, then use the server's VPN address
(`http://100.x.y.z:8000`) as the Coolify URL and the VPN range as *Allowed IPs*. Opening port 8000 to the whole
Internet is not recommended. (On a home server on the same LAN as your computer, there is nothing to do.)

## 9 · Connect the plugin and deploy the example app

In Claude Code:
```
Set up coolify-ops: my Coolify is at http://<server-address>:8000, my base domain is example.org,
I reach the server over ssh as user@server, reserve the subdomain hooks, and new projects go in ~/Projects.
```
This runs `coolify.py init`, which checks the token, discovers your server and GitHub App and saves
`~/.config/coolify-ops/config.json` (outside any repository). The ssh access is optional but lets the plugin
check the server's health, clean up thoroughly when you delete an app, and restore or download database backups.

Then try the example app that ships with this repository. Coolify deploys from a GitHub repository, so copy it into
its own folder first (the plugin will create a private repo for it and give you the push command):
```bash
cp -r examples/hello-fastapi ~/Projects/hello-fastapi
```
```
Deploy ~/Projects/hello-fastapi
```
The plugin analyzes it, writes a Dockerfile, builds and tests it locally with Docker, shows you one summary to
confirm and — after your «yes» — creates the app with an HTTPS domain and auto-deploy on every push. When you no
longer need it: `/coolify-ops:deploy-app decommission hello-fastapi`.

## 10 · Backups and maintenance

- **Coolify's own data** (settings, apps, encrypted secrets): *Settings → Backup* (`/settings/backup`) — enable scheduled backups,
  ideally to S3-compatible storage outside the server.
- **Your apps' databases**: the PostgreSQL databases `deploy-app` creates get a daily backup on the server (the
  last 7 are kept). Ask Claude «do I have backups of hello-fastapi?», «back it up now», «restore yesterday's data»
  (it always asks first, backs up the current data before restoring and puts it back if the restore fails; restoring needs the ssh access of step 9) or «download a copy» (to
  `~/.config/coolify-ops/backups/`). These backups live on the same server: for a copy that survives losing the
  server, download one now and then, or add an S3 destination in the database's *Backups* tab in Coolify.
- **Updates:** `unattended-upgrades` covers security patches; run `sudo apt upgrade` now and then. Coolify
  updates from its panel (*Settings → Updates*, `/settings/updates`, where you can also enable auto-update).
- **Disk space:** Docker images pile up with every deployment. Coolify cleans them up on its own — check the
  schedule and disk threshold in *Servers → localhost → Docker Cleanup*; it keeps a few recent images per app for
  rollback.

## 11 · Common issues

See [troubleshooting](../../plugins/coolify-ops/skills/deploy-app/reference/troubleshooting.md) for the issues
found deploying real apps: wrong listening address, health checks on minimal images, old Node/Angular
versions, SPA routing, build-time vs runtime variables, certificates, webhooks, API permissions and leftovers
after deleting an app.
