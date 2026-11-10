# coolify-ops

*[Leer en castellano](README.es.md)*

Claude Code skills to run your own [Coolify](https://coolify.io) server: tell Claude «deploy this project» and it
analyzes it, writes a Dockerfile if missing, builds and tests it on your machine, shows you **one summary** to
confirm and, after your «yes», publishes it with an HTTPS domain, a database if needed and auto-deploy on every
push. Everything goes through the Coolify API: no browser automation.

| Skill | Invoke | What it does |
|---|---|---|
| `deploy-app` | `/coolify-ops:deploy-app` | Deploy and manage apps (status, logs, update, env vars, rollback, PostgreSQL backups and restore, decommission) |
| `provision-server` | `/coolify-ops:provision-server` | Set up Coolify on a VPS or home server step by step, checking each step (never handles passwords or `sudo`) |

```
> set up Coolify on my VPS user@203.0.113.10 with the domain example.org
> /coolify-ops:provision-server diagnose user@my-server
> /coolify-ops:provision-server check
> deploy ~/Projects/my-shop
> /coolify-ops:deploy-app status
> /coolify-ops:deploy-app logs my-shop
> /coolify-ops:deploy-app backups my-shop
> /coolify-ops:deploy-app decommission test-app
```

## What it can deploy

| Project | Template |
|---|---|
| Python with FastAPI | `python-fastapi` (uvicorn) |
| Python with Flask | `python-flask` (gunicorn) |
| Django (settings in `coolify_settings.py`, static files with WhiteNoise, migrations on start, PostgreSQL) | `python-django` (gunicorn) |
| Laravel 11+ (Apache, Composer, Vite front end built in the image, migrations on start, PostgreSQL) | `php-laravel` / `php-laravel-api` |
| Node server (Express, Hono, Fastify, NestJS; Remix, classic or with a `start` script) | `node-server` |
| Next.js | `nextjs` |
| SPA: Angular, Vite (React/Vue/Svelte), Create React App | `spa-nginx` |
| Nuxt, Astro, SvelteKit, Angular SSR, React Router (framework mode) with a Node server | `node-ssr` |
| The same frameworks built as a static site, and Next.js with `output: 'export'` | `spa-nginx` |
| Static website | `static-nginx` |
| Plain PHP | `php-apache` |
| Any single-service project with its own `Dockerfile` (any framework) | used as is |

Python dependencies are installed from `requirements.txt`, `uv.lock`, `poetry.lock` or a plain `pyproject.toml`.
Optionally with a private PostgreSQL (always created for Django and Laravel). A repository with **several apps in
subfolders** (e.g. `backend/` + `frontend/`, nothing at the root) is deployed one app per folder: each with its own
domain, in one Coolify project per repository, and redeployed only when its own folder changes.
**Not** covered yet (the skill stops and explains): workspaces (npm/yarn/pnpm workspaces, Turborepo, Nx, uv…), a
root app plus several app folders, multi-service apps, apps that import code from outside their folder, apps that need MySQL/MariaDB, MongoDB or Redis, and — unless they bring their own `Dockerfile` — Django
with a frontend build (`package.json`), Pipenv projects, Symfony, Laravel 10 or older (or with the pre-11 structure, Laravel Mix or private Composer repositories), Nuxt 2, Angular Universal, Remix with Vite and no `start` script, SolidStart, Qwik City, Vike, TanStack Start, Analog, and projects
built for another platform (e.g. SvelteKit `adapter-auto`, `@astrojs/vercel`): the skill says what to change.

New to Coolify? Start with [Coolify from scratch](../../docs/en/coolify-from-scratch.md)
([en castellano](../../docs/es/coolify-desde-cero.md)) before the setup below, or let the `provision-server` skill guide you.

## Requirements

- Python 3.10+, `git`, [`gh`](https://cli.github.com) signed in, and Docker (for the local build check).
- A server running Coolify v4 with a GitHub App source, a wildcard domain (`*.example.org`) pointing at it and
  ports 80/443 open for HTTPS.
- Network access from your machine to the Coolify API (same LAN or VPN, or a public panel URL).

## Setup (once)

1. **Enable the API** in Coolify: *Settings → Advanced → API access → Enabled*, set *Allowed IPs* to your
   network (e.g. `192.168.1.0/24`) and press *Save*.
2. **Create a token** in *Keys & Tokens → API Tokens* (`/security/api-tokens`) with `read`, `read:sensitive` (for logs), `write`, `deploy` and `delete`.
3. **Store the token** (it never goes into a repo or the chat). Pick one:
   - macOS Keychain (copy the token first):
     `security add-generic-password -U -a "$USER" -s coolify-api-token -w "$(pbpaste)" && pbcopy < /dev/null`
   - Any OS: write it to `~/.config/coolify-ops/token` and `chmod 600` it.
   - Or export `COOLIFY_TOKEN`.
4. Ask Claude «set up coolify-ops». It runs:
   ```bash
   coolify.py init --url http://<coolify-ip>:<port> --domain example.org --ssh user@server --reserved hooks --projects-dir ~/Projects
   ```
   which discovers the server and the GitHub App and saves `~/.config/coolify-ops/config.json`.

### Recommended Claude Code permissions

To make the flow hands-off, add to `permissions.allow` in `~/.claude/settings.json`:

```json
"Bash(docker build *)", "Bash(docker run *)", "Bash(docker rm *)", "Bash(docker image rm *)",
"Bash(docker info)", "Bash(ssh user@server *)"
```

The skill already allows its own scripts. **`git push` is never automated**: the skill prepares the commit and
gives you the command to run yourself (`! git push`).

## Local files

| Path | Contents |
|---|---|
| `~/.config/coolify-ops/config.json` | Coolify URL, base domain, server and GitHub App uuids, ssh, projects folder, default limits |
| `~/.config/coolify-ops/apps.json` | Registry of deployed apps (name → uuids, domain) |
| `~/.config/coolify-ops/secrets/<app>.env` | Variable values for each app (`chmod 600`; `coolify.py env-template` creates it with empty keys, and empty values are never uploaded) |
| `~/.config/coolify-ops/backups/<app>/` | Database copies downloaded with `coolify.py backup-download` (folder 700, files 600); they hold all the app's data |

Override the folder with `COOLIFY_OPS_HOME`. A v0.1 configuration in `~/.config/coolify-deploy/` is migrated
automatically.

## Safety

- One confirmation per deployment; rollback, decommission, restoring a database backup, keeping fewer backups and
  deleting variables always ask.
- New PostgreSQL databases get daily backups on the server (last 7 kept; never unlimited). A restore first takes
  a backup of the current data (unless the database is empty) and puts it back if the restore fails (it needs `ssh` in the configuration). Downloaded copies never go into a git repository.
- Databases always private; never opens ports or uses reserved or taken subdomains.
- Scans the files that would be pushed for secrets and stops if it finds any.
- Passwords and tokens are masked in all output; variable values are never shown.
- CPU and memory limits on every app.
- Optional user and password on an app's domain (`coolify.py protect`); the password is generated and kept in
  `~/.config/coolify-ops/secrets/<app>.access`.

## Scripts

All print JSON and can be used by hand. They live in `skills/deploy-app/scripts/`:

| Script | Use |
|---|---|
| `coolify.py` | API client (`coolify.py --help` lists the commands) |
| `repo.py state\|init\|commit <path>` | Local git for the skill: state, `git init` with a `.gitignore`, commit after a secrets scan. It has no push |
| `analyze.py <path>` | Project analysis; `--secrets` only scans for secrets |
| `prepare.py <path>` | Writes Dockerfile, `.dockerignore` and `nginx.conf` from the templates |
| `local_check.py <path> --port N` | Local Docker build and run; always cleans up |
| `verify.py https://host` | Certificate, redirect, routes, `--external` (check-host.net) and `--server` (ssh) |

And in `skills/provision-server/scripts/`:

| Script | Use |
|---|---|
| `server.py diagnose user@host` | Read-only server diagnosis: OS, arch, RAM, disk, Docker, Coolify, ports in use, hardening |
| `server.py dns example.org` | Wildcard DNS check on a public resolver |
| `server.py ports 203.0.113.10 --private 8000` | Reachability of 80/443 from the Internet, panel port closed (`--require-filtered` on a VPS: blocked by a firewall) |
| `server.py health` | Coolify `/api/health` and its containers |

See also [troubleshooting](skills/deploy-app/reference/troubleshooting.md) and the
[API reference](skills/deploy-app/reference/coolify-api.md).
