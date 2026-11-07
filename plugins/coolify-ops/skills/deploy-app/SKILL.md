---
name: deploy-app
description: Prepare and deploy the user's own projects (local folder or GitHub repo) to a self-hosted Coolify server through its API — Dockerfile from templates, local build check, HTTPS domain, optional PostgreSQL and auto-deploy on every push — and manage deployed apps (status, logs, update, env vars, rollback, decommission). Use when the user asks to deploy, publish or ship an app or website to their server or to Coolify, or to manage apps already running there. Also triggers on Spanish requests such as «despliega», «publica» or «sube a mi servidor».
argument-hint: "[path | owner/repo | status | logs <app> | update <app> | env <app> | rollback <app> | decommission <app>]"
allowed-tools: Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*), Bash(git status*), Bash(git -C *), Bash(git add *), Bash(git commit *), Bash(git log *), Bash(gh repo view *), Bash(gh repo clone *)
---

# Deploy an app to Coolify

Deploys the user's projects to their Coolify server **through the API** (never through a browser). Everything runs
through the scripts in `${CLAUDE_SKILL_DIR}/scripts/`, which print JSON:

| Script | Purpose |
|---|---|
| `coolify.py` | Coolify API: check, init, status, projects, apps, databases, env vars, deploy, wait, logs, rollback, decommission |
| `analyze.py` | Read-only project analysis: is it deployable, which template, and why not |
| `prepare.py` | Writes Dockerfile / .dockerignore / nginx.conf from `templates/` (never overwrites) |
| `local_check.py` | Builds and runs the image locally, probes routes, always cleans up |
| `verify.py` | Checks the published app (HTTPS, redirect, routes, external reachability) and server health |

Shorthand used below: `C` = `python3 -I ${CLAUDE_SKILL_DIR}/scripts/coolify.py`, and likewise `A` (analyze.py),
`P` (prepare.py), `L` (local_check.py) and `V` (verify.py). **Always type the full command**, never the shorthand.

**Language:** talk to the user in the language they write in. Script output is in English; translate it.

User configuration (outside the repo, folder `~/.config/coolify-ops/`, mode 700):
`config.json` (url, base_domain, server and GitHub App uuids, ssh, reserved_subdomains, projects_dir,
default_limits), `apps.json` (registry of deployed apps), `secrets/<app>.env` (variable values).
API token: `COOLIFY_TOKEN`, or `~/.config/coolify-ops/token`, or the macOS Keychain (service `coolify-api-token`).
**Never print tokens or passwords.**

If there is no configuration or no token, Coolify itself is probably not set up yet: point the user to the
`provision-server` skill of this plugin (installs and connects Coolify step by step; checks progress, never
handles `sudo` or passwords) or, meanwhile, to the written tutorial at `docs/en/coolify-from-scratch.md` in the
repo root (`docs/es/coolify-desde-cero.md` in Spanish).

---

## Fixed rules (never skipped)

1. **One confirmation per new deployment**: the summary in step D. Everything before it is read-only or local;
   everything after it is automatic. `rollback`, `decommission` and deleting variables **always** ask separately.
2. **Pushing to GitHub is done by the user.** Never run `git push`, `gh repo create --push` or anything that
   uploads code. Prepare the commit and give the exact command for them to run with `!` (see «Pushes»). Wait.
3. **Secrets:** if `analyze.py` finds secrets in files that would be pushed, **stop** and explain what and where
   (never the values). Before every push, `A <path> --secrets` must come back clean. Variable values never go
   through the chat: they live in `~/.config/coolify-ops/secrets/<app>.env` and are uploaded with `env-push`.
4. **Never** make a database public or open router ports. Never use a reserved or already used subdomain
   (`C domain-check` verifies it).
5. **CPU/RAM limits always** (defaults from the config). Coolify's health check stays off unless the image has
   `curl`/`wget`.
6. **Only touch application code if the user asks.** The skill adds deployment files only.
7. If the server is above 80 °C or its disk above 90 %, warn and do not build.
8. **At most 2 automatic retries** per build/start failure, changing deployment files only. Then stop and
   explain using the last log lines.
9. Scope: **single-service** apps (Python FastAPI/Flask, Node, Next.js, SPA, static, plain PHP) with optional
   PostgreSQL. Monorepos, multi-service apps, Django, Laravel, Nuxt/Astro/SvelteKit SSR: **stop and explain**.

---

## Deploying a new app

### A · Pre-flight
1. `C check` → on failure, guide the user by the error (API disabled, IP not allowed, token, wrong network/VPN).
   Without configuration: `C init --url <URL> --domain <domain> [--ssh <user@host>] [--reserved <sub>]
   [--projects-dir <folder>]` (ask the user for the values the first time).
2. `V --server` → temperature, disk and Coolify healthy (rule 7). Skipped if there is no `ssh` in the config.

### B · Analysis
- Given `owner/repo` not present locally: `gh repo clone owner/repo <projects_dir>/<repo>` (`projects_dir` comes
  from `config.json`; new projects are also created there).
- `A <path>` and read: `deployable`, `blockers`, `warnings`, `stack`, `env_vars`, `databases`, `secrets`,
  `has_login_estimate`, `paid_services_estimate`, `git`.
- If there are **blockers**, stop here and explain them together with what would fix them.
- If the app uses paid services and has no login, access stays public by default **but** the summary must propose
  protecting it (proxy basic auth) and the user must choose explicitly.

### C · Preparation and local check
1. `P <path>` (use `--var KEY=value` if the analysis got something wrong, e.g. `--var PORT=8080`).
2. `L <path> --port <port> --routes / [other relevant routes]` (add `--env` with test values only).
3. On failure: read `build_error` / `container_logs`, fix **only** deployment files and repeat (rule 8).
4. If it works and files were created: `git add` those files and `git commit -m "build: deploy to Coolify (…)"`.

### D · Summary and confirmation (the only question)
Check the domain with `C domain-check <name>` and present exactly this block (translated to the user's language):
```
App:          <name>  (<framework>, <template or own Dockerfile>)
Repo:         <owner/repo> · branch <branch> · <what must be pushed: commits / new repo / nothing>
Domain:       https://<name>.<base_domain>   (<available ✔ | reason>)
Access:       public | protected with user and password
Database:     no | PostgreSQL 17 (new, private)
Variables:    <names> (values in ~/.config/coolify-ops/secrets/<name>.env) | none
Resources:    max <cpus> CPU / <memory>
Auto-deploy:  yes (every push publishes) | no
Warnings:     <list or «none»>
Local check:  OK (<seconds> s build, routes <…>)
```
If variables are needed, create `~/.config/coolify-ops/secrets/<name>.env` with **empty** keys, `chmod 600`, and
ask the user to fill in the values (never ask for them in the chat). Wait for their «yes».

### E · Execution (no more questions)
1. **Push to GitHub** if needed: see «Pushes». Wait for the user, then check with `git -C <path> status -sb`
   that nothing is left to push.
2. `C create-project <name>` → `project_uuid`.
3. `C create-app --project <uuid> --repo <owner/repo> --branch <branch> --port <port> --domain <name> --name <name>`
   (+ `--cpus`/`--memory` to override defaults, `--no-autodeploy` if chosen) → `app_uuid`.
4. With PostgreSQL: `C create-postgres --project <uuid> --name <name> --app <name> --app-uuid <app_uuid>`
   (creates a private database and sets `DATABASE_URL` on the app; the password is generated by the script and
   never shown).
5. With variables: `C env-push <name> ~/.config/coolify-ops/secrets/<name>.env`.
6. `C deploy <name>` → `deployment_uuid`; `C wait <deployment_uuid>`.
7. If `ok` is false: diagnose with `last_lines` (and `C logs <name>`), fix deployment files, commit, push by the
   user and retry (rule 8).

### F · Verification
`V https://<domain> --routes / [routes] --external --server`. If the certificate is not valid yet, wait (the
script already waits up to 2 minutes). If `external_unverified`, say so; it is not a failure.

### G · Wrap-up
Summarize in a few lines: URL, what was created (project, app, database), verification result and how to update
(«push to <branch> and it deploys by itself»). The local registry (`apps.json`) is updated by the scripts.

---

## Other modes

| Request | What to do |
|---|---|
| `status` | `C status` → table: app, status, domain, auto-deploy (`C last-deployment <app>` if useful) |
| `logs <app>` | `C logs <app>` and `C last-deployment <app>`; summarize errors |
| `update <app>` | Local commit if there are changes → push by the user → `C last-deployment <app>` until the new commit shows up → `C wait …` → `V …`. Without auto-deploy: `C deploy <app>` |
| `env <app>` | `C env-list <app>` (names only). To change values: the user edits `secrets/<app>.env` → `C env-push …` → `C deploy <app>`. To delete one: confirm with the user → `C env-delete <app> <KEY> --confirmed` |
| `rollback <app>` | `C rollback <app> --confirmed` lists images; **ask which one** and confirm → `C rollback <app> --image <tag> --confirmed` |
| `decommission <app>` | Explain what will be deleted (app, and the database if any: **offer a backup first**). After an explicit «yes»: `C decommission <app> --confirmed [--with-db] [--with-project]`. The script watches the server until Coolify's cleanup is done before removing the project; if `deleted.warning` appears, the project was kept: tell the user |

---

## Pushes (done by the user)

Give the exact command, ready to paste with `!`:
- New repository (private by default): `! gh repo create <owner>/<name> --private --source=<path> --remote=origin --push`
- Pending commits: `! git -C <path> push`

Before handing it over: `A <path> --secrets` clean and `git -C <path> log --oneline @{u}..HEAD` to tell the user
what will be pushed.

## Known issues
See `${CLAUDE_SKILL_DIR}/reference/troubleshooting.md` (ports, health check, old Node, SPA routes, public
Next/Vite variables, certificates, leftovers after deleting) and `${CLAUDE_SKILL_DIR}/reference/coolify-api.md`.
