# Coolify from scratch

A step-by-step guide to running your own [Coolify](https://coolify.io) server — a self-hosted alternative to
Heroku/Vercel — so you can later use the `coolify-ops` plugin to deploy your projects to it. You do not need to
know Docker or server administration beforehand; every command is given in full.

Once it is running, the `provision-server` skill of this plugin can check most of the steps below for you
(read-only diagnosis, DNS, open ports, Coolify health) and walk you through the ones that need your `sudo`
password or a browser — which it never does for you. This guide works just as well by itself, by hand.

## 1 · What you need

- A machine that stays on: a **VPS** (a few euros/dollars a month) or a **computer at home** (a Raspberry Pi 4/5,
  an old laptop, a mini-PC). 2 GB of RAM is a comfortable minimum for Coolify itself, plus whatever your apps need
  — 4 GB is more relaxed if you plan to build Node or Angular apps on it.
- Any 64-bit CPU: x86_64 or ARM64 both work (Coolify and this toolkit's Docker templates support both).
- Debian or Ubuntu (other Linux distributions mostly work too; this guide assumes one of these two).
- A domain name you control, even a free one (see step 3). You do **not** need a static IP on the machine itself
  if you use a dynamic DNS service, only a domain that always points at it.
- `ssh` access to the machine as a user who can run `sudo`.

## 2 · Choose where it runs

| | VPS | Home server |
|---|---|---|
| Public IP | Fixed, given by the provider | Usually changes; needs dynamic DNS |
| Setup | Faster: ports are open by default | You open ports on your router |
| Cost | Monthly fee | Electricity only, hardware you may already own |
| Reliability | Provider's uptime | Depends on your power and internet |

**On a VPS**, any provider that gives you root SSH access to a fresh Debian/Ubuntu machine works. Note its public
IP; you will point your domain at it.

**At home**, two things matter first:
- **Check you are not behind CGNAT.** Some ISPs do not give you a real public IP, even if your router shows one.
  From the server, run `curl -4 ifconfig.me` and compare it with what your router's WAN page shows. If they
  differ, you are behind CGNAT and cannot forward ports without asking your ISP for a public IP (sometimes free
  on request) or using a tunnel (e.g. Cloudflare Tunnel, outside the scope of this guide).
- **Give the server a fixed address on your LAN** (a DHCP reservation in your router, or a static IP on the
  machine) so port forwarding keeps working after a reboot.
- **Forward ports 80 and 443** on your router to that LAN address. These are the only ports that must be public;
  Coolify's panel (port 8000) should stay private (see step 5).
- If you want to browse the panel from inside your own network using the public domain name, your router needs
  **NAT loopback / hairpinning**. Most consumer routers support it; if a `https://your-domain` request from
  inside the LAN does not reach the server, that is usually why — browsing by LAN IP works around it meanwhile.

## 3 · DNS: a domain with a wildcard

You need one domain name that resolves to the server, with a **wildcard** record so that every app gets its own
subdomain automatically (`shop.example.org`, `blog.example.org`, …) without touching DNS again.

- **Your own domain** (recommended if you plan to keep this server around): at your registrar, add an `A` record
  `*.example.org` pointing at the server's public IP. One record covers every future subdomain.
- **Free option**: [DuckDNS](https://www.duckdns.org) gives you `yourname.duckdns.org` for free, including a
  wildcard (`*.yourname.duckdns.org`) and a small client that keeps the IP updated if it changes (useful at
  home). Any similar dynamic DNS service with wildcard support works the same way.

Wait for the DNS change to propagate (minutes to a couple of hours) and confirm it with:
```bash
dig +short anything.example.org
```
It should print the server's public IP.

## 4 · Harden the server first

Do this before installing anything else — it takes a few minutes and avoids the most common way these boxes get
compromised.

```bash
# Create a non-root user if you only have root, then as that user:
sudo apt update && sudo apt upgrade -y

# SSH: key-based login only
ssh-copy-id user@server                      # from your own machine, if not done yet
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh

# Firewall: only SSH, HTTP and HTTPS from the outside
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable

# Automatic security updates
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```
Keep Coolify's panel port (8000) **closed** to the outside — rule 80/443 above does not open it. You will reach
the panel over SSH tunnel or VPN until you decide otherwise (see step 5).

## 5 · Install Coolify

Coolify installs itself with one official script, which sets up Docker if it is missing:
```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```
It takes a few minutes. At the end it prints a URL like `http://<server-ip>:8000`.

- **First boot**: open that URL — from inside your network, or through an SSH tunnel if you hardened the
  firewall already (`ssh -L 8000:localhost:8000 user@server`, then open `http://localhost:8000` on your own
  machine). Create the admin account on this first visit; anyone who reaches that URL before you do can create it
  instead, so do this immediately after install.
- Keep the panel reachable only from your LAN, a VPN, or an SSH tunnel — not from the public internet — unless
  you explicitly want to manage Coolify from outside and are comfortable opening port 8000 (or proxying it
  through 443 with its own auth in front).
- In Coolify's settings, set its own domain/IP if you plan to use a name for the panel itself (optional; the apps
  it deploys get their own domains regardless).

## 6 · Proxy and HTTPS

Coolify runs its own reverse proxy (Traefik) that requests and renews Let's Encrypt certificates automatically
for every app domain, as long as ports 80 and 443 reach the server (step 2/4) and DNS already resolves (step 3).
You do not configure certificates by hand.

Known rough edge: if you open ports 80/443 **after** a deployment has already failed to get a certificate,
Traefik sometimes does not retry on its own. Restarting its container nudges it:
```bash
docker restart coolify-proxy
```
See [troubleshooting.md](../../plugins/coolify-ops/skills/deploy-app/reference/troubleshooting.md) for this and
other certificate issues.

## 7 · Connect GitHub (as a GitHub App)

The `deploy-app` skill deploys from GitHub repositories using a **GitHub App**, not a personal token — it is
scoped to only the repos you choose and Coolify uses it to clone, read commits and receive push webhooks.

1. In Coolify: *Sources → Add → GitHub App*. Coolify prepares the manifest for you.
2. Follow its link to GitHub, name the app, and let GitHub create it; Coolify receives the credentials
   automatically.
3. Install the app on your account/organization, choosing **either** all repositories or only the ones you plan
   to deploy (you can add more later).
4. One setting needs a public address even on a home server: GitHub → *Settings → Developer settings → GitHub
   Apps → your app → Webhook URL* must be your server's public URL ending in
   `/webhooks/source/github/events` (e.g. `https://coolify.example.org/webhooks/source/github/events`), not a
   private IP. This is the only inbound path from GitHub; it does not expose anything else.

## 8 · Enable the API

The skills in this plugin talk to Coolify only through its API, never through the browser.

1. *Settings → Advanced → API access*: turn it **on**.
2. In the same screen, set **Allowed IPs** to the network you will call the API from (e.g. your home LAN
   `192.168.1.0/24`, or your own IP if calling from outside). Leaving this unset/open is not recommended.
3. *Security → API tokens → Create*: give it a name and the permissions `read`, `write`, `deploy` and **`delete`**
   (`delete` is a separate permission from `write`; without it, every delete call returns a 403). Permissions
   cannot be edited after creation — if you forget one, create a new token.
4. Copy the token now; Coolify shows it only once. Store it with one of these (never in a file inside this repo
   or any repo you will push):
   - macOS Keychain: `security add-generic-password -U -a "$USER" -s coolify-api-token -w "<paste here>"`
   - Any OS: save it to `~/.config/coolify-ops/token` and run `chmod 600` on it.
   - Or export it as `COOLIFY_TOKEN` in your shell profile.

## 9 · Connect the skill and deploy the example app

Back in Claude Code, with the `coolify-ops` plugin installed:
```
Set up coolify-ops: my Coolify is at http://<server-ip-or-domain>:8000, my base domain is example.org,
I can reach it over ssh as user@server, and new projects go in ~/Projects.
```
This runs `coolify.py init`, which discovers your server and GitHub App through the API and saves
`~/.config/coolify-ops/config.json` (outside the repo — never committed).

Then try the example project that ships with this repo. Coolify deploys from a GitHub repository, so copy it
into its own folder first (the skill will offer to create a private repo for it):
```bash
cp -r examples/hello-fastapi ~/Projects/hello-fastapi
```
```
Deploy ~/Projects/hello-fastapi
```
The skill analyzes it, builds and tests it locally with Docker, shows you one summary to confirm, and — after
your "yes" — creates the app on Coolify with an HTTPS domain and auto-deploy on every push.

## 10 · Backups and maintenance

- **Coolify itself** keeps its configuration in its own database inside Docker; Coolify's UI has a built-in
  backup/restore for it (*Settings → Backup*). Enable scheduled backups there.
- **Your apps' databases** (e.g. the PostgreSQL ones this plugin creates): Coolify can schedule backups per
  database too (*the database → Backups*); point them at S3-compatible storage if you want them off the server.
- **System updates**: `sudo apt upgrade` regularly; Coolify updates itself from its own UI (*Settings → Update*).
- **Disk space**: Docker images pile up over time; `docker system prune` reclaims space from old, unused images
  and build cache (review what it would remove first with `docker system df`).

## 11 · Common issues

See [troubleshooting.md](../../plugins/coolify-ops/skills/deploy-app/reference/troubleshooting.md) for the
issues found deploying real apps: wrong listening address, health checks on minimal images, old Node/Angular
versions, SPA routing, build-time vs runtime variables, certificates, webhooks, API permissions, and leftovers
after deleting an app.
