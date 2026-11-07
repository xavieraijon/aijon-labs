---
name: deploy-app
description: Prepare and deploy the user's own projects (local folder or GitHub repo) to a self-hosted Coolify server through its API — Dockerfile from templates, local build check, HTTPS domain, optional PostgreSQL and auto-deploy on every push — and manage deployed apps (status, logs, update, env vars, rollback, decommission). Use when the user asks to deploy, publish or ship an app or website to their server or to Coolify, or to manage apps already running there. Also triggers on Spanish requests such as «despliega», «publica» or «sube a mi servidor».
argument-hint: "[path | owner/repo | status | logs <app> | update <app> | env <app> | rollback <app> | decommission <app>]"
allowed-tools: Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*), Bash(gh api user -q .login), Bash(gh repo view *), Bash(gh repo clone *)
---

# Deploy an app to Coolify

Deploys the user's projects to their Coolify server **through the API** (never through a browser). Everything runs
through the scripts in `${CLAUDE_SKILL_DIR}/scripts/`, which print JSON:

| Script | Purpose |
|---|---|
| `coolify.py` | Coolify API: check, init, status, projects, apps, databases, env vars, access protection, deploy, wait, logs, rollback, decommission |
| `repo.py` | Local git: `state`, `init` (with a `.gitignore`), `commit` (refuses if it finds secrets). **It has no push** |
| `analyze.py` | Read-only project analysis: is it deployable, which template, and why not |
| `prepare.py` | Writes Dockerfile / .dockerignore / nginx.conf from `templates/` (never overwrites) |
| `local_check.py` | Builds and runs the image locally, probes routes, always cleans up |
| `verify.py` | Checks the published app (HTTPS, redirect, routes, external reachability) and server health |

Shorthand used below: `C` = `python3 -I ${CLAUDE_SKILL_DIR}/scripts/coolify.py`, and likewise `A` (analyze.py),
`P` (prepare.py), `L` (local_check.py), `V` (verify.py) and `G` (repo.py). **Always type the full command**, never the shorthand.

**Language:** talk to the user in the language they write in. Script output is in English; translate it.

User configuration (outside the repo, folder `~/.config/coolify-ops/`, mode 700):
`config.json` (url, base_domain, server and GitHub App uuids, ssh, reserved_subdomains, projects_dir,
default_limits), `apps.json` (registry of deployed apps), `secrets/<app>.env` (variable values),
`secrets/<app>.access` (user and password of a protected app).
API token: `COOLIFY_TOKEN`, or `~/.config/coolify-ops/token`, or the macOS Keychain (service `coolify-api-token`).
**Never print tokens or passwords.**

If there is no configuration or no token, Coolify itself is probably not set up yet: point the user to the
`provision-server` skill of this plugin (installs and connects Coolify step by step; checks progress, never
handles `sudo` or passwords) or, meanwhile, to the written tutorial «Coolify from scratch»:
https://github.com/xavieraijon/aijon-labs/blob/main/docs/en/coolify-from-scratch.md (Spanish:
https://github.com/xavieraijon/aijon-labs/blob/main/docs/es/coolify-desde-cero.md). It is not installed with the
plugin.

---

## Fixed rules (never skipped)

1. **One confirmation per new deployment**: the summary in step D. Everything before it is read-only or local;
   everything after it is automatic. `rollback`, `decommission` and deleting variables **always** ask separately.
2. **Pushing to GitHub is done by the user.** Never run `git push`, `gh repo create --push` or anything that
   uploads code. Prepare the commit and give the exact command for them to run with `!` (see «Pushes»). Wait.
3. **Secrets:** if `analyze.py` finds secrets in files that would be pushed, **stop** and explain what and where
   (never the values). Before every push, `A <path> --secrets` must come back clean. Variable values never go
   through the chat: they live in `~/.config/coolify-ops/secrets/<app>.env` (created by `env-template`) and are
   uploaded with `env-push`. Never pass a value on the command line.
4. **Never** make a database public or open router ports. Never use a reserved or already used subdomain
   (`C domain-check` verifies it).
5. **CPU/RAM limits always** (defaults from the config). Coolify's health check stays off unless the image has
   `curl`/`wget`.
6. **Only touch application code if the user asks.** The skill adds deployment files only.
7. If the server is above 80 °C or its disk above 90 %, warn and do not build.
8. **At most 2 automatic retries** per build/start failure, changing deployment files only. Then stop and
   explain using the last log lines.
9. Scope: **single-service** apps (Python FastAPI/Flask, Node, Next.js, SPA, static, plain PHP) with optional
   PostgreSQL, plus any single-service project with **its own `Dockerfile`** (used as is, whatever the framework).
   Without their own Dockerfile, Django, Laravel/Symfony and Nuxt/Astro/SvelteKit are not covered yet. Monorepos,
   multi-service apps and apps that need MySQL/MariaDB, MongoDB or Redis are not covered either. In all these
   cases: **stop and explain** (the analysis reports them as `blockers`).

---

## Deploying a new app

### A · Pre-flight
0. If the user already says the project is out of scope (rule 9) and has no Dockerfile of its own, skip the
   checks below: run only `A <path> --secrets` (to warn about secrets that would be pushed) and explain.
1. `C check` → on failure, guide the user by the error (API disabled, IP not allowed, token, wrong network/VPN).
   **No configuration:** ask once whether Coolify is already installed with API access, a token and a GitHub
   App. Yes → ask for the panel URL and base domain (and `user@host`, the reserved webhook subdomain) and run
   `C init --url <URL> --domain <domain> [--ssh <user@host>] [--reserved <sub>] [--projects-dir <folder>]`.
   No or unsure → hand over to the `provision-server` skill and stop here.
2. `V --server` → read `server`: `skipped` (no `ssh` in the config) is fine; `error` (ssh failed) → warn and go
   on without server checks; `temperature_c` > 80 or `disk_used_pct` > 90 → rule 7; `coolify` not `healthy` →
   stop and show it (a deployment would fail).

### B · Analysis
- Given `owner/repo` not present locally: `gh repo clone owner/repo <projects_dir>/<repo>` (`projects_dir` comes
  from `config.json`; new projects are also created there).
- `G state <path>`. Not a repository (`is_repo` false): `G init <path>` first — it creates `.gitignore` if missing
  (dependencies, build caches, `.env*`) so the analysis below sees the project as it would be pushed. Git is only
  ever used through `repo.py`, never directly.
- `A <path>` and read: `deployable`, `blockers`, `warnings`, `stack`, `env_vars`, `databases`, `secrets`,
  `has_login_estimate`, `paid_services_estimate`, `git`, `suggested_name`.
- From here on, `<name>` = the name the user gave, else `suggested_name`; `<port>` = `stack.port`;
  `<path>` = the project folder.
- No GitHub remote yet: the owner is `gh api user -q .login` unless the user names an organisation; the repository
  is created by the user at push time (see «Pushes»).
- If there are **blockers**, stop here and explain them together with what would fix them.
- If the app uses paid services and has no login, access stays public by default **but** the summary must propose
  protecting it (basic auth on its domain, step E6) and the user must choose explicitly. Mention that an API
  called by other programs would then need the same user and password.

### C · Preparation and local check
1. `P <path>` (use `--var KEY=value` if the analysis got something wrong, e.g. `--var PORT=8080`).
2. `L <path> --port <port> --routes / [other relevant routes]` (add `--env` with test values only).
   If the app needs a database (`databases` not empty), there is none locally: probe only routes that do not use
   it. A failure caused only by the missing database (connection refused / unknown host in `container_logs`) is
   **not** a build failure: report «build OK, start needs the database» and do not apply rule 8.
3. On failure: read `build_error` / `container_logs`, fix **only** deployment files and repeat (rule 8).
4. If it works, commit. A repository just created by `G init` has no commits yet: commit the whole project,
   deployment files included (`G commit <path> -m "chore: initial commit" --all`; allowed under rule 6, it changes
   no code). An existing repository: only the deployment files,
   `G commit <path> -m "build: deploy to Coolify (…)" --files Dockerfile .dockerignore [nginx.conf]`.
   If `G commit` returns `secrets`, stop (rule 3).

### D · Summary and confirmation (the only question)
Check the domain with `C domain-check <name>` and present exactly this block (translated to the user's language):
```
App:          <name>  (<framework>, <template or own Dockerfile>)
Repo:         <owner/repo> · branch <branch> · <what must be pushed: commits / new repo (+ give the GitHub App access) / nothing>
Domain:       https://<name>.<base_domain>   (<available ✔ | reason>)
Access:       public | protected with user and password
Database:     no | PostgreSQL 17 (new, private)
Variables:    <names> (values in ~/.config/coolify-ops/secrets/<name>.env) | none
Resources:    max <cpus> CPU / <memory>
Auto-deploy:  yes (every push publishes) | no
Warnings:     <list or «none»>
Local check:  OK (<seconds> s build, routes <…>)
```
If variables are needed, `C env-template <name> KEY1 KEY2 …` with the names from `env_vars` (it creates
`~/.config/coolify-ops/secrets/<name>.env` with empty keys, mode 600, and never touches existing values). **Leave
out `DATABASE_URL` when the skill creates the database** (step E4 sets it). Ask the user to fill in the values in
that file (never in the chat). Wait for their «yes».

### E · Execution (no more questions)
1. **Push to GitHub** if needed: see «Pushes». Wait for the user, then check with `G state <path>` that
   `to_push` is empty. **New repository:** the GitHub App only sees the repositories it was installed on, so ask
   the user to add it: GitHub → *Settings → Applications → Installed GitHub Apps → <the Coolify app> → Configure
   → Repository access → add <owner>/<name> → Save*. Wait for their «done».
2. `C create-project <name>` → `project_uuid`.
3. `C create-app --project <uuid> --repo <owner/repo> --branch <branch> --port <port> --domain <name> --name <name>`
   (+ `--cpus`/`--memory` to override defaults, `--no-autodeploy` if chosen) → `app_uuid`.
4. With PostgreSQL: `C create-postgres --project <uuid> --name <name> --app <name> --app-uuid <app_uuid>`
   (creates a private database and sets `DATABASE_URL` on the app; the password is generated by the script and
   never shown).
5. With variables: `C env-push <name> ~/.config/coolify-ops/secrets/<name>.env`. Empty values are never uploaded:
   if `skipped_empty` lists keys, name them and ask the user whether to fill them in (then push again) or go on.
6. Protected access chosen: `C protect <name> [--user <user>]` (the password is generated and saved in
   `secrets/<name>.access`, mode 600; never print it — tell the user where it is).
7. `C deploy <name>` → `deployment_uuid`; `C wait <deployment_uuid>`.
8. If `ok` is false: diagnose with `last_lines` (and `C logs <name>`). A clone/checkout error («repository not
   found», «could not read from remote») means the GitHub App has no access to the repository: back to step E1,
   it is not a build failure. Otherwise fix deployment files, commit, push by the user and retry (rule 8).

### F · Verification
`V https://<domain> --routes / [routes] --external --server`, adding `--protected` when the app has a user and
password (its routes must then answer 401). If the certificate is not valid yet, wait (the
script already waits up to 2 minutes). If `external_unverified`, say so; it is not a failure.

### G · Wrap-up
Summarize in a few lines: URL, what was created (project, app, database), verification result and how to update
(«push to <branch> and it deploys by itself»). The local registry (`apps.json`) is updated by the scripts.

---

## Other modes

| Request | What to do |
|---|---|
| `protect <app>` / `unprotect <app>` | Confirm with the user → `C protect <app> [--user <user>]` (or `--off`) → `C deploy <app>` → `C wait …`. The credentials stay in `secrets/<app>.access` |
| `status` | `C status` → table: app, status, domain, auto-deploy (`C last-deployment <app>` if useful). Every command accepts the app's name (from `apps.json` or from the server) or its uuid; if a name is ambiguous, use the uuid |
| `logs <app>` | `C logs <app>` and `C last-deployment <app>`; summarize errors |
| `update <app>` | `G state <path>`; local changes → `G commit <path> -m "<message>" --all` → push by the user → `C last-deployment <app>` until the new commit shows up → `C wait …` → `V …`. Without auto-deploy: `C deploy <app>` |
| `env <app>` | `C env-list <app>` (names only). To add or change values: `C env-template <app> <KEY…>` if new keys → the user edits `secrets/<app>.env` → `C env-push <app> <file> --only <KEY…>` with **only** the keys added or changed (pushing the whole file would overwrite values changed in the panel since) → `C deploy <app>` → `C wait <deployment_uuid>` → `V https://<domain>`. To delete one: confirm with the user → `C env-delete <app> <KEY> --confirmed`. Do not use `env-set` with a value on the command line |
| `rollback <app>` | `C rollback <app>` lists images (read-only, no question): `current` is the running tag, `images[]` have `tag`, `created_at`, `is_current`; «the previous version» = the newest image that is not current. No image besides the current one → say a rollback is not possible and offer an `update` with a `git revert` made by the user. Otherwise show them, **ask which one** and confirm → `C rollback <app> --image <tag> --confirmed` → `C wait <deployment_uuid>` → `V https://<domain>` (`--protected` if it has a user and password). Domain and auto-deploy come from `C status` (`domains`, `autodeploy`) when the app is not in `apps.json`. If auto-deploy is on, warn that the next push replaces the rollback |
| `decommission <app>` | Explain what will be deleted (app, and the database if any: **offer a backup first**). After an explicit «yes»: `C decommission <app> --confirmed [--with-db] [--with-project]`. If the database or project is not in `apps.json`, the script refuses before deleting anything: tell the user and offer to delete only the app. The script watches the server until Coolify's cleanup is done before removing the project; if `deleted.warning` appears, the project was kept: tell the user. It also deletes the app's local `secrets/<app>.env` and `.access` (listed in `deleted.local_files`) |

---

## Pushes (done by the user)

Give the exact command, ready to paste with `!`:
- New repository (private by default): `! gh repo create <owner>/<name> --private --source=<path> --remote=origin --push`
- Pending commits: `! git -C <path> push`

Before handing it over: `A <path> --secrets` clean and `G state <path>` → tell the user what `to_push` lists (for
a new repository, every commit).

## Known issues
See `${CLAUDE_SKILL_DIR}/reference/troubleshooting.md` (ports, health check, old Node, SPA routes, public
Next/Vite variables, certificates, leftovers after deleting) and `${CLAUDE_SKILL_DIR}/reference/coolify-api.md`.
