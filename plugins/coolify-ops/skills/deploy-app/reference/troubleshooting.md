# Troubleshooting

Learned deploying real apps with Coolify v4.6 on a Raspberry Pi 5 (ARM64) and applicable to any server.

| Symptom | Cause | Fix |
|---|---|---|
| 502 / 503 / «no available server» | The app listens on `127.0.0.1`/`localhost`, or Coolify's port (`ports_exposes`) differs from the app's | Listen on `0.0.0.0`; the Dockerfile `EXPOSE` and `--port` must match |
| The deployment fails although the app works | Coolify health check enabled on a `slim`/`alpine` image without `curl` or `wget` | Keep `health_check_enabled=false` (what `create-app` does) or install `curl` in the image |
| Old Angular builds fail with OpenSSL or dependency errors | Angular ≤ 14 needs Node 16; Angular 15–16 needs Node 18 | `analyze.py` picks Node from the Angular version; force it with `--var NODE_VERSION=16` |
| Reloading an SPA route (e.g. `/cart`) returns 404 | The server does not fall back to `index.html` | The SPA template's `nginx.conf` uses `try_files $uri $uri/ /index.html` |
| Angular ≥ 17 outputs to `dist/<app>/browser` | The `application` builder adds `/browser` | `analyze.py` accounts for it; check `BUILD_DIR` if the build folder is not found |
| `NEXT_PUBLIC_*` / `VITE_*` variables are empty in the browser | They are inlined at build time; runtime-only variables never reach the bundle | `env-push` also marks them for build time |
| No HTTPS certificate | Let's Encrypt needs ports 80 and 443 reaching the server and DNS pointing at the public IP | `verify.py` waits up to 2 minutes; then check router/firewall ports and DNS |
| Traefik does not retry a certificate after opening the ports | Traefik does not retry while its configuration is unchanged | Restart Coolify's proxy (`docker restart coolify-proxy` on the server) |
| `git push` blocked from Claude Code | By design | The user runs the command with `!` |
| GitHub webhooks never arrive | The GitHub App's Webhook URL points to a private address | GitHub → Developer settings → GitHub Apps → the app → public Webhook URL (path `/webhooks/source/github/events`) |
| The API returns 403 | The client IP is not in «Allowed IPs» or the token lacks a permission | Settings → Advanced → API access; token with `read`, `write`, `deploy`, `delete` |
| 403 «Missing required permissions: delete» | `delete` is separate from `write` | Create a new token including it (permissions cannot be edited) |
| Volumes, images or folders left on the server after deleting | Coolify marks the resource deleted at once (the API already answers 404) and cleans the server in a background job a second later. If the project is deleted in between, the job fails with «Attempt to read property "project" on null» and leaves everything behind | `decommission` watches the server over ssh until no containers or volumes with the uuid remain, and only then deletes the project (without ssh it waits 45 s). Old leftovers: `docker volume rm`, `docker image rm` and, with sudo, `/data/coolify/{applications,databases}/<uuid>` |
| The API does not answer | Not on the server's network/VPN, or API access disabled | Connect the VPN or enable API access |
| A deployment interrupts a long-running task in the app | Every deployment restarts the container | For apps with long tasks, create with `--no-autodeploy` and deploy manually |
| The server gets hot while building | Heavy Node/Angular builds | Normal for 1–2 minutes; if it often exceeds 80 °C, improve cooling |
