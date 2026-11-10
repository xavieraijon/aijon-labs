# Server setup blocks

The exact blocks `provision-server` hands to the user. They mirror the guide «Coolify from scratch»
(https://github.com/xavieraijon/aijon-labs/blob/main/docs/en/coolify-from-scratch.md), which is not installed with
the plugin. Give only the lines the user still needs; **the user runs them**, never Claude.

## CGNAT (home server, step B)

If the server's public IP (`curl -4 ifconfig.me`) differs from the WAN IP on the router's status page, the ISP uses
CGNAT and port forwarding cannot work. Options:
- ask the ISP for a public IP (often free on request), then re-run the diagnosis;
- use a tunnel such as Cloudflare Tunnel (outside the scope of this skill);
- use a VPS instead.

## No ssh key yet (step A)

On the user's own computer, if `ls ~/.ssh/id_ed25519.pub` finds nothing:
```bash
ssh-keygen -t ed25519            # accept the default path; a passphrase is recommended
```

## Key-only ssh (step C)

First, **from the user's own computer** (not the server), copy the key and check it logs in without a password:
```bash
ssh-copy-id user@server
ssh user@server            # must not ask for the account password
```
A fresh VPS that only has `root` with a password: the user runs `ssh-copy-id root@server` themselves (typing the
password in their terminal, never in the chat), then the steps below. If that password was ever pasted in a chat
or sent by e-mail, change it once logged in: `passwd`.

**Working as root:** minimal images often have no `sudo`; as root, run the blocks **without** the `sudo` prefix.
Recommended: create a normal user for everyday ssh and for this plugin, then log in as that user:
```bash
adduser deploy && usermod -aG sudo deploy          # as root; install sudo first if missing: apt install -y sudo
mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/ && chown -R deploy: /home/deploy/.ssh
```
After Coolify is installed (it installs Docker), `sudo usermod -aG docker <user>` (without `sudo` as root;
`<user>` = the ssh user of the plugin) lets the plugin's checks see the containers, from the next ssh login. **The docker group is equivalent to root.** For least privilege, give the plugin a separate ssh user
without `sudo` and without the docker group: the checks then rely on the panel's health URL instead.

Then, **on the server**, disable password logins with a drop-in. sshd keeps the first value it reads and
`sshd_config.d/*.conf` is included first, so editing `sshd_config` alone is not enough; the `00-` prefix wins:
```bash
echo "PasswordAuthentication no" | sudo tee /etc/ssh/sshd_config.d/00-key-only.conf
sudo systemctl restart ssh
```
Keep that session open and check from a **new** terminal that login still works before closing it.

## Dynamic DNS (home, step D)

A home IP changes from time to time; DNS must follow it. Best: the router's own dynamic DNS setting, if it
supports the provider. Otherwise, for DuckDNS, on the server (the token is on duckdns.org; paste it in the file,
never in a chat):
```bash
mkdir -p ~/.duckdns && chmod 700 ~/.duckdns
nano ~/.duckdns/token && chmod 600 ~/.duckdns/token       # paste the token, save
(crontab -l 2>/dev/null; echo '*/5 * * * * curl -fsS "https://www.duckdns.org/update?domains=<name>&token=$(cat ~/.duckdns/token)" >/dev/null') | crontab -
```
`<name>` is the part before `.duckdns.org`. The wildcard (`*.<name>.duckdns.org`) needs no extra record.

## Automatic security updates (step C)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

## Firewall (step C)

Docker bypasses `ufw`: Coolify's panel (8000) and realtime ports (6001, 6002) stay reachable even if `ufw` says
they are closed.
- **VPS:** in the provider's control panel, a firewall allowing inbound **22, 80 and 443 only**.
- **Home server:** the router forwards **80 and 443 only**; `ufw` is optional.

## Private network for the API (VPS, step F)

The panel and the API share port 8000, which the provider's firewall keeps closed. Tailscale gives the user's
computer and the server private addresses (`100.x.y.z`) without opening any port.
1. On the server (the user, in their ssh session):
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up            # prints a login URL: open it and sign in
   tailscale ip -4              # the server's tailnet address
   ```
2. On the user's computer: install Tailscale from https://tailscale.com/download and sign in with the same
   account.
3. In Coolify, *Settings → Advanced*: *Allowed IPs* = `100.64.0.0/10` (Tailscale's range), **Save**.
4. The panel/API URL for `coolify.py init` is `http://<tailnet address>:8000`. The provider's firewall stays as
   it is (22, 80, 443): Tailscale does not need any inbound port.

## GitHub webhooks only (step G1)

In Coolify: *Servers → localhost → Proxy → Dynamic Configurations → Add*, name `github-webhooks.yaml`, content
(replace `example.org` with the user's base domain, in the `Host` rule only):
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
Do not change the `Path`, `Method` or `service` parts: they are what keeps the panel private.

**Check from outside the LAN** (on a home server, NAT loopback makes a check from inside meaningless): the user
opens `https://hooks.<domain>/` on a phone **with Wi-Fi off**, or runs from any machine outside their network
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://hooks.<domain>/
```
Expected: an error code (404/503), **never 200** and never Coolify's login page. If the login page shows, stop:
the panel is exposed — remove the dynamic configuration and check the `rule` line.

## Example app (step H)

The example `hello-fastapi` is not installed with the plugin. The user gets it with:
```bash
d=$(mktemp -d) && git clone --depth 1 https://github.com/xavieraijon/aijon-labs "$d/aijon-labs" \
  && cp -r "$d/aijon-labs/examples/hello-fastapi" <projects_dir>/hello-fastapi && rm -rf "$d"
```
