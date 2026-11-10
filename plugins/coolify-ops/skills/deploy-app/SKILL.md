---
name: deploy-app
description: Prepare and deploy the user's own projects (local folder or GitHub repo) to a self-hosted Coolify server through its API — Dockerfile from templates, local build check, HTTPS domain, optional PostgreSQL and auto-deploy on every push — and manage deployed apps (status, logs, update, env vars, rollback, PostgreSQL backups and restore, decommission). Use when the user asks to deploy, publish or ship an app or website to their server or to Coolify, or to manage apps already running there. Also triggers on Spanish requests such as «despliega», «publica» or «sube a mi servidor».
argument-hint: "[path | owner/repo | status | logs <app> | update <app> | env <app> | rollback <app> | backups <app> | decommission <app>]"
allowed-tools: Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*), Bash(gh api user -q .login), Bash(gh repo view *), Bash(gh repo clone *)
---

# Deploy an app to Coolify

Deploys the user's projects to their Coolify server **through the API** (never through a browser). Everything runs
through the scripts in `${CLAUDE_SKILL_DIR}/scripts/`, which print JSON:

| Script | Purpose |
|---|---|
| `coolify.py` | Coolify API: check, init, status, projects, apps, databases, env vars, access protection, deploy, wait, logs, rollback, database backups (`backup-*`), decommission |
| `repo.py` | Local git: `state`, `init` (with a `.gitignore`), `commit` (refuses if it finds secrets). **It has no push** |
| `analyze.py` | Read-only project analysis: is it deployable, which template, and why not |
| `prepare.py` | Writes Dockerfile / .dockerignore / nginx.conf / coolify_settings.py (Django) from `templates/` (never overwrites unless `--overwrite`) |
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
   everything after it is automatic. `rollback`, `decommission`, restoring a database backup, keeping fewer
   backups when that deletes some (`needs_confirmation`) and deleting variables **always** ask separately.
2. **Pushing to GitHub is done by the user.** Never run `git push`, `gh repo create --push` or anything that
   uploads code. Prepare the commit and give the exact command for them to run with `!` (see «Pushes»). Wait.
3. **Secrets:** if `analyze.py` finds secrets in files that would be pushed, **stop** and explain what and where
   (never the values). Before every push, `A <repo> --secrets` must come back clean (`<repo>` = `git.root`: a push
   publishes the whole repository; the same as `<path>` for a single app). Variable values never go
   through the chat: they live in `~/.config/coolify-ops/secrets/<app>.env` (created by `env-template`) and are
   uploaded with `env-push`. Never pass a value on the command line.
4. **Never** make a database public or open router ports. Never use a reserved or already used subdomain
   (`C domain-check` verifies it).
5. **CPU/RAM limits always** (defaults from the config). Coolify's health check stays off unless the image has
   `curl`/`wget`. The Python and Laravel templates bring their own `HEALTHCHECK` (Coolify waits for it and keeps the previous
   version if the new one never becomes healthy).
6. **Only touch application code if the user asks.** The skill adds deployment files only.
7. If the server is above 80 °C or its disk above 90 %, warn and do not build.
8. **At most 2 automatic retries** per build/start failure, changing deployment files only. Then stop and
   explain using the last log lines.
9. Scope: **single-service** apps (Python FastAPI/Flask/Django with requirements.txt, uv, Poetry or a plain
   `pyproject.toml`; Node, Next.js, SPA, static, plain PHP; Laravel 11+ with or without a Vite front end; Nuxt,
   Astro, SvelteKit, Angular SSR and React Router as a static site or a Node server) with optional PostgreSQL
   (always for Django and Laravel), plus any single-service project
   with **its own `Dockerfile`** (used as is, whatever the framework). Without their own Dockerfile, Django with a
   frontend build (`package.json`), Pipenv projects, Symfony, Laravel 10 or older (or with the pre-11 structure),
   Laravel Mix, private Composer repositories, Nuxt 2, Angular Universal, adapters for other platforms (Vercel, Netlify,
   Cloudflare, SvelteKit `adapter-auto`…), SolidStart, Qwik City, Vike, TanStack Start and Analog are not covered
   yet. A repository with **several apps in subfolders** is covered, one app per folder (see «Repositories with
   several apps»); workspaces (npm/yarn/pnpm workspaces, Turborepo, Nx, Lerna, Rush, uv), a root app plus several
   app folders, multi-service compose files, apps that import code from outside their folder and apps that need
   MySQL/MariaDB, MongoDB or Redis are not covered.
   In all these cases: **stop and explain** (the analysis reports them as `blockers`, with the change that would
   make the project deployable; the skill never makes that change itself, rule 6).

---

## Deploying a new app

### A · Pre-flight
0. If the user already says the project is out of scope (rule 9) and has no Dockerfile of its own, skip the
   checks below: run only `A <path> --secrets` (on the repository root; to warn about secrets that would be pushed) and explain.
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
- `G state <path>`. Not a repository (`is_repo` false) with `parent_warning`: ask the user whether the repository
  is the parent folder (then follow «Repositories with several apps» from it) or this folder alone.
  Not a repository: `G init <path>` first — it creates `.gitignore` if missing
  (dependencies, build caches, `.env*`, `db.sqlite3`, `staticfiles/`, `media/`, and the build output folder listed
  in `ignored_build_output` when the image builds it) so the analysis below sees the project as it would be pushed. Git is only
  ever used through `repo.py`, never directly.
- `A <path>` and read: `deployable`, `blockers`, `warnings`, `stack`, `env_vars`, `databases`, `secrets`,
  `has_login_estimate`, `paid_services_estimate`, `git`, `suggested_name`, and when present `build_time_env`.
  For the frameworks that can be static or a server, `stack.render` says which (`static` → nginx, `server` →
  Node); `stack.runtime_env` lists variables set from the domain at creation (e.g. `NG_ALLOWED_HOSTS`) and
  `stack.ssr_marker` a text that proves server rendering. `stack.origin_fix` (React Router, Astro server): form
  submissions will be rejected behind HTTPS; in the summary (step D) show the fix — in `origin_fix.file`, add
  `origin_fix.add` with `{domain}` replaced by `<name>.<base_domain>` — and add it only if the user asks (rule 6;
  then commit it with the deployment files). Pages without forms work either way.
- **Django** (`stack.framework` = `django`): `prepare.py` also writes `coolify_settings.py`, a deployment file
  that loads the project's settings and overrides the production values (secret key, `DEBUG` off, allowed hosts,
  HTTPS proxy, `DATABASE_URL`, static files with WhiteNoise, console logging); the project's own files are not
  changed. `stack.generated_env` (`DJANGO_SECRET_KEY`) is created on the server by step E3, never by the user;
  `env_vars.managed` lists the variables the deployment sets itself (never ask for them). `stack.check_routes`
  are the routes to probe (admin login and one admin CSS file when they exist); `stack.local_env` the test
  variables for step C. Migrations run on every container start (`stack.migrations`).
- **Laravel** (`stack.framework` = `laravel`): PHP with Apache serving `public/`, Composer, the Vite front end
  built in the image (`stack.frontend`; template `php-laravel`, or `php-laravel-api` without a build script),
  PostgreSQL always (`DB_URL`). With `stack.trust_proxies` = `generated`, `prepare.py` also writes
  `config/trustedproxy.php`, a deployment file that makes Laravel trust Coolify's proxy only inside the image
  (otherwise URLs and assets would use `http://` behind HTTPS); `project` means the project configures it: treat
  it like `origin_fix` — in step D show the warning and the fix (`->trustProxies(at: '*')` inside `withMiddleware`
  in `bootstrap/app.php`, replacing the project's own `trustProxies` call) and change it only if the user asks.
  A MySQL/MariaDB `.env.example` or a Sail `compose.yaml` (mysql, redis…) is **not** a rule-9 stop for Laravel:
  only what the analysis lists in `blockers` counts; the app runs on PostgreSQL and the summary says «your local
  database is MySQL; production uses PostgreSQL» (MySQL-only SQL in migrations would fail there). `stack.generated_env` (`APP_KEY:laravel`) and `stack.url_env` (`APP_URL`) are set on the
  server by step E3, `stack.db_env_key` (`DB_URL`) by step E4; never ask for them. `env_vars` keeps only the
  variables the project added: the skeleton's ones have defaults. `env_vars.changed_defaults` names the skeleton
  keys whose `.env.example` value differs (e.g. `MAIL_MAILER`): in step D name them and ask whether production
  needs its own values for them (the `config/*.php` defaults apply otherwise, e.g. mail goes to the log); values
  from a local setup (Sail's `mailpit`, `redis`, `mysql` hosts) are not production values. If the user wants
  them, add them to `env-template` — for mail, all the `MAIL_*` keys together. Queue workers, the scheduler, Reverb and Inertia SSR are not
  deployed (warnings). Migrations and `php artisan optimize` run on every container start.
- Python: check `stack.module` (the app object gunicorn/uvicorn loads, e.g. `main:app`). The analysis only looks
  at the project root, `app/` and `src/`; if the app object lives elsewhere, correct it in step C1.
- From here on, `<name>` = the name the user gave, else `suggested_name`; `<port>` = `stack.port`;
  `<path>` = the project folder.
- No GitHub remote yet: the owner is `gh api user -q .login` unless the user names an organisation; the repository
  is created by the user at push time (see «Pushes»).
- `monorepo.kind` = `apps`, or `git.subdir` not empty: see «Repositories with several apps» before going on. At
  the repository root the «several apps in this repository» blocker is expected: do not stop for it; the blocker
  rule below applies to each app folder's own analysis.
- If there are **blockers**, stop here and explain them together with what would fix them.
- If the app uses paid services and has no login, access stays public by default **but** the summary must propose
  protecting it (basic auth on its domain, step E6) and the user must choose explicitly. Mention that an API
  called by other programs would then need the same user and password.

### C · Preparation and local check
1. `P <path>` (use `--var KEY=value` if the analysis got something wrong, e.g. `--var PORT=8080` or
   `--var MODULE=api.main:app`; when the files already exist, add `--overwrite` or nothing is rewritten).
2. `L <path> --port <port> --routes / [other relevant routes]` (add `--env` with test values only).
   - `build_time_env` present: also `--build-env KEY=<test value>` for each of those keys (the build inlines them
     and fails without them). Test values only, never the real ones.
   - `stack.runtime_env` has `NG_ALLOWED_HOSTS`: add `--env NG_ALLOWED_HOSTS=localhost,127.0.0.1` (Angular answers
     400 to any other host).
   - `stack.ssr_marker` present: add `--expect <ssr_marker>`; `marker_found: false` means the page was not
     rendered on the server (a failure, rule 8).
   - `stack.local_env` present (Django, Laravel): `--routes / <check_routes>` and `--env` for each of its entries.
     With a SQLite project (Django) or always (Laravel: `DB_CONNECTION=sqlite`) migrations run against a temporary
     SQLite file, so migrations, static files or caches and the server are all exercised. Without it (the project targets PostgreSQL), a start failure from `migrate` or the database
     connection counts as «start needs the database» below.
   - Laravel failures that are the project's, not the deployment files' (no rule-8 retries; explain with the log
     lines): a migration error caused by SQL that SQLite cannot run → report «local check limited» and go on; an
     exception after the `Caching` lines (`php artisan optimize`: duplicate route names, a broken view) or during
     `composer dump-autoload` / `package:discover` / `wayfinder:generate` in the build (a service provider that
     needs the database or a variable while booting) → stop and explain.
   Unless `stack.local_env` provides a database, an app that needs a database (`databases` not empty) has
   none locally: probe only routes that do not use it. A failure caused only by the missing database (connection refused / unknown host in `container_logs`) is
   **not** a build failure: report «build OK, start needs the database» and do not apply rule 8.
3. On failure: read `build_error` / `container_logs`, fix **only** deployment files and repeat (rule 8). A build
   error about a file outside the app folder (`../shared`, a missing sibling package) is the project's: stop and
   explain (the build only sees the folder; no rule-8 retries). To
   change a value from the analysis, `P <path> --var KEY=value --overwrite`.
4. If it works, commit. A repository just created by `G init` has no commits yet: commit the whole project,
   deployment files included (`G commit <repo> -m "chore: initial commit" --all`, `<repo>` = `git.root`, the same
   as `<path>` for a single app; allowed under rule 6, it changes no code). An existing repository: only the deployment files,
   `G commit <path> -m "build: deploy to Coolify (…)" --files Dockerfile .dockerignore [nginx.conf] [coolify_settings.py] [config/trustedproxy.php]`.
   If `G commit` returns `secrets`, stop (rule 3).

### D · Summary and confirmation (the only question)
Check the domain with `C domain-check <name>` and present exactly this block (translated to the user's language):
```
App:          <name>  (<framework>, <template or own Dockerfile>)
Repo:         <owner/repo> · branch <branch> · <what must be pushed: commits / new repo (+ give the GitHub App access) / nothing>
              (app folder: «<owner/repo> · <folder>/ · redeploys only when <folder>/ changes»)
Project:      <project name> (new | shared with <apps of `C status` with the same `repo`>)
Domain:       https://<name>.<base_domain>   (<available ✔ | reason>)
Access:       public | protected with user and password
Database:     no | PostgreSQL 17 (new, private) | external (DATABASE_URL supplied by you, with the variables)
Backups:      (new PostgreSQL) daily on the server, last 7 kept | none (you said so)
Variables:    <names> (values in ~/.config/coolify-ops/secrets/<name>.env; mark build-time ones) | none
              + <keys of stack.runtime_env> = the domain (set automatically)
              + <keys of stack.url_env> = https://<the domain> (set automatically)
              + <keys of stack.generated_env> = random secret (generated on the server, never shown)
Migrations:   (Django and Laravel) applied automatically on every start — with auto-deploy also on every push, without
              asking; (when Backups is not «none») a database backup is taken every day (restoring one replaces the data)
Resources:    max <cpus> CPU / <memory>
Auto-deploy:  yes (every push publishes) | no
Warnings:     <list or «none»>
Local check:  OK (<seconds> s build, routes <…>)
```
If `stack.warning_sqlite` is present, add to «Warnings»: «the PostgreSQL database starts empty: the admin user
must be created again (step G)». If `build_time_env` lists secret keys, add to «Warnings»: «<keys> are needed at build time: Coolify passes them
as build arguments, so their values stay in the image history on the server (not in logs)».
If variables are needed, `C env-template <name> KEY1 KEY2 …` with the names in `env_vars.in_code` plus the keys of
`env_vars.example` (and the `changed_defaults` the user chose) — never those in
`env_vars.managed` (it creates
`~/.config/coolify-ops/secrets/<name>.env` with empty keys, mode 600, and never touches existing values). **Leave
out `DATABASE_URL` (Laravel: `DB_URL`, `stack.db_env_key`) when the skill creates the database** (step E4 sets it); include it when the database is
external. Ask the user to fill in the values in
that file (never in the chat). Wait for their «yes».

### E · Execution (no more questions)
1. **Push to GitHub** if needed: see «Pushes». Wait for the user, then check with `G state <path>` that
   `to_push` is empty. **New repository:** the GitHub App only sees the repositories it was installed on, so ask
   the user to add it: GitHub → *Settings → Applications → Installed GitHub Apps → <the Coolify app> → Configure
   → Repository access → add <owner>/<name> → Save*. Wait for their «done».
2. `C create-project <project>` → `project_uuid` (`<project>` = `<name>`; for an app folder, the repository folder
   name, shared by every app of the repository).
3. `C create-app --project <uuid> --repo <owner/repo> --branch <branch> --port <port> --domain <name> --name <name>`
   (+ `--cpus`/`--memory` to override defaults, `--no-autodeploy` if chosen, `--env-domain <KEY>` for each key of
   `stack.runtime_env`, `--env-url <KEY>` for each key of `stack.url_env`, `--env-generate <KEY>` for each entry of
   `stack.generated_env`, as written, e.g. `APP_KEY:laravel`; app folder: `--base-dir /<folder> --watch-paths
   '<folder>/**'`, with `<folder>` = `git.subdir` without its final `/`) → `app_uuid`. If `env_errors` is not empty the app
   **was** created: retry once the failed keys with `C env-domain`, `C env-url` or `C env-generate <name> <KEY…>`
   (for `env-generate`, use the `key` of `env_errors` as it is, with its format, e.g. `APP_KEY:laravel`); if it fails again, stop and explain (nothing to undo; the variable can be
   set later the same way).
4. With PostgreSQL, unless the user said they bring their own database (then `DATABASE_URL` is a variable like
   any other, uploaded in step E5, with `--buildtime` if it is in `build_time_env`):
   `C create-postgres --project <uuid> --name <name> --app <name> --app-uuid <app_uuid>` (+ `--env-key
   <stack.db_env_key>` when the analysis has one: Laravel reads `DB_URL`)
   (creates a private database and sets `DATABASE_URL`, or that key, on the app; the password is generated by the script and
   never shown). Add `--buildtime` when `DATABASE_URL` is in `build_time_env` (the build inlines it), and
   `--backup none` only if the user said no backups in step D. It also schedules daily backups (last 7 kept); if
   the result has `backup_warning`, say so in the final summary (the database works; backups can be set up later
   with `C backup-schedule <name>`).
5. With variables: `C env-push <name> ~/.config/coolify-ops/secrets/<name>.env` (+ `--buildtime <KEY…>` with
   the keys of `build_time_env`, except `DATABASE_URL` when step E4 created it). If the result has
   `buildtime_not_in_file`, those keys were not uploaded: add them with `env-template` and push again. Empty values are never uploaded:
   if `skipped_empty` lists keys, name them and ask the user whether to fill them in (then push again) or go on.
6. Protected access chosen: `C protect <name> [--user <user>]` (the password is generated and saved in
   `secrets/<name>.access`, mode 600; never print it — tell the user where it is).
7. `C deploy <name>` → `deployment_uuid`; `C wait <deployment_uuid>`.
8. If `ok` is false: diagnose with `last_lines` (and `C logs <name>`). A clone/checkout error («repository not
   found», «could not read from remote») means the GitHub App has no access to the repository: back to step E1,
   it is not a build failure. If the new container never became healthy and the deployment log
   (`C wait <deployment_uuid> --lines 120`; Coolify copies the new container's output there) shows `Applying …`
   followed by a traceback, a **migration failed**: Coolify kept the previous version running (`C logs <name>`
   shows that old container, not the failed one). Report it with the error lines; it is a problem in the project's
   migrations, not in the deployment files (no rule-8 retries). Laravel, in the same deployment log:
   `Running migrations` then `FAIL` or a `QueryException` → migration failed (same handling); an exception after
   the `Caching` lines → `optimize` failed (a project problem, same handling); connection refused to
   `127.0.0.1:5432` → the database URL variable is missing (check `C env-list <name>`, redo step E4 with
   `--env-key`); connection refused or `could not translate host name` to the database uuid on a first
   deployment → the database was not ready yet: deploy once more; `could not find driver` → a variable overrides
   `DB_CONNECTION`, or a PHP extension is missing.
   Otherwise fix deployment files, commit, push by the user and retry (rule 8).

### F · Verification
`V https://<domain> --routes / [routes] --external --server`, adding `--protected` when the app has a user and
password (its routes must then answer 401) and `--expect <ssr_marker>` when the analysis has one (not checked
on protected apps: `marker_found` is then null). Django: `--routes <check_routes>` (without `/`). Laravel:
`--routes / <check_routes>` and, when `stack.verify_expect` is present and `/` answered 2xx in the local check,
`--expect <verify_expect with {domain} replaced>` (asset URLs in https prove the proxy is trusted; never in step C).
Without `verify_expect` (no front end, or `/` not 2xx) say «proxy trust not verified» in the wrap-up. Any app whose
`/` answered 404 in the local check (a Django project with no home page, an API): use a route that answered 2xx
there (FastAPI serves `/docs`) or `--routes / --accept-4xx` (401/403/404/405 then prove it is up; 400 does not). If the certificate is not valid yet, wait (the
script already waits up to 2 minutes). If `external_unverified`, say so; it is not a failure.

### G · Wrap-up
Summarize in a few lines: URL, what was created (project, app, database), verification result and how to update
(«push to <branch> and it deploys by itself»). Django: the new database is empty (data in `db.sqlite3` was not
copied); to use the admin, create a user with `python manage.py createsuperuser` in the app's *Terminal* tab in
Coolify (it asks for the password there, never in the chat). Laravel: the database is empty too; users sign up
through the app, or are created with `php artisan tinker` in the same *Terminal* tab. The local registry (`apps.json`) is updated by the scripts.

### Repositories with several apps
A repository whose root holds no app and whose subfolders do (`backend/` + `frontend/`, `api/` + `web/`…). Each app
is its own Coolify app built from its folder, with its own domain, in one Coolify project per repository.
- At the repository root, `monorepo.apps` lists each app folder (`path`, `framework`, `template`,
  `existing_dockerfile`, `databases`, `deployable`, `blockers`, `suggested_name` = `<repository>-<folder>`). Show
  it as a table and ask which to deploy (one, several or all the deployable ones). This choice is not rule 1's
  confirmation: each app still gets its own step D. When a frontend and the API it calls are both chosen, say now
  that the API must allow the frontend's domain (CORS), so it can be fixed before the API is deployed.
- Then, **one app after another** (APIs and backends first), run steps B–G with `<path>` = the app folder:
  `A`, `P`, `L` and `G commit --files` work on the folder; `G init`, `A --secrets`, the initial commit and pushes
  on the repository (`<repo>` = `git.root`). Step E1 (push, new repository, GitHub App access) usually only applies
  to the first app. If an app fails, **stop**: say which apps were deployed, which failed and which were not started.
- In step D, when the app reads a public variable that holds the URL of a sibling API (`VITE_API_URL`,
  `NEXT_PUBLIC_API_URL`…), tell the user its value for the secrets file: `https://<sibling's domain>` — read from
  `C status` (the app with the same `repo` and the sibling's `base_dir`; ask if there is none) — plus the path its
  `.env.example` value has (e.g. `/api`). Add to «Warnings»: «the API must allow
  https://<this app's domain> (CORS)»; change the API's code only if the user asks (rule 6).
- `git.root` is shown in step B when it is not the folder the user named (the folder may be inside a repository
  they did not expect).

---

## Other modes

| Request | What to do |
|---|---|
| `protect <app>` / `unprotect <app>` | Confirm with the user → `C protect <app> [--user <user>]` (or `--off`) → `C deploy <app>` → `C wait …`. The credentials stay in `secrets/<app>.access` |
| `status` | `C status` → table: app, status, domain, auto-deploy (`C last-deployment <app>` if useful). Every command accepts the app's name (from `apps.json` or from the server) or its uuid; if a name is ambiguous, use the uuid |
| `logs <app>` | `C logs <app>` and `C last-deployment <app>`; summarize errors. `C logs` shows the **running** container: if the last deployment `failed`, read its log as in the next row |
| «my change does not show», «it did not update» | `G state <path>`: `to_push` not empty → the change was never pushed (see «Pushes»). Otherwise `C last-deployment <app>`: `failed` → `C wait <deployment_uuid> --lines 120` and diagnose as in step E8 (migration, `optimize`, database URL, build error; the previous version is still running); `in_progress`/`queued` → `C wait <deployment_uuid>`; no deployment after the push → if the push only changed files outside the app's folder (an app of a repository with several apps only redeploys when its folder changes; files at the repository root do not count), say that this is expected and offer `C deploy <app>`; otherwise auto-deploy is off or the webhook did not arrive: `C deploy <app>` (the GitHub App webhook can be checked in Coolify). Only then suggest a hard refresh of the browser |
| `update <app>` | `G state <path>`; local changes → `G commit <path> -m "<message>" --all` (from an app folder `--all` commits, and scans, the whole repository: say so) → push by the user → `C last-deployment <app>` until the new commit shows up → `C wait …` → `V …`. Without auto-deploy: `C deploy <app>` |
| `env <app>` | `C env-list <app>` (names only). To add or change values: `C env-template <app> <KEY…>` if new keys → the user edits `secrets/<app>.env` → `C env-push <app> <file> --only <KEY…>` with **only** the keys added or changed (pushing the whole file would overwrite values changed in the panel since) → `C deploy <app>` → `C wait <deployment_uuid>` → `V https://<domain>`. To delete one: confirm with the user → `C env-delete <app> <KEY> --confirmed`. Do not use `env-set` with a value on the command line |
| `rollback <app>` | `C rollback <app>` lists images (read-only, no question): `current` is the running tag, `images[]` have `tag`, `created_at`, `is_current`; «the previous version» = the newest image that is not current. No image besides the current one → say a rollback is not possible and offer an `update` with a `git revert` made by the user. Otherwise show them, **ask which one** and confirm → `C rollback <app> --image <tag> --confirmed` → `C wait <deployment_uuid>` → `V https://<domain>` (`--protected` if it has a user and password). Domain and auto-deploy come from `C status` (`domains`, `autodeploy`) when the app is not in `apps.json`. If auto-deploy is on, warn that the next push replaces the rollback. Django and Laravel: a rollback restores the code, not the database: migrations already applied stay; a backup from before the deployment can be restored with `backup-restore` (see below), **asked separately** |
| `backups <app>`, «do I have backups?» | `C backup-status <app>` (read-only, no question; `--db <uuid>` when the app's database is not in `apps.json`: in `C status` the app's database is named `<app>-db` (step E4); if none or several match, show them and ask). Show `schedules` (frequency, how many kept) and `backups` (date and time converted from UTC to the user's local time, size, `origin` scheduled/manual/other). `daily` runs at 00:00 in the server's timezone; for another hour use a cron (`0 3 * * *` = every night at 3). `has_any_schedule` true → backups are scheduled; when the enabled one is `origin: other` it was made in Coolify: change it only if the user asks, with `--backup <uuid>`. `has_any_schedule` false (database created before backups existed, or with `--backup none`) → **offer** `C backup-schedule <app>` (daily, last 7 kept); never create it unasked. `last_failed_at` newer than the last success → say the latest backup failed. Only PostgreSQL databases made in Coolify; Coolify 4.6.0 or later |
| «back up now», «haz una copia» | `C backup-now <app>` (no question: it adds a backup; manual backups are kept apart from the scheduled ones, last 5) → date and size. «not running» → the database is stopped: Coolify does not back up a stopped database |
| «change how often / how many are kept» | `C backup-schedule <app> [--frequency hourly\|daily\|weekly\|monthly\|<cron>] [--keep N] [--off]`. `needs_confirmation` → tell the user that `would_delete` backups will be deleted at the next run and ask, even if they already gave the number (the count is new to them); after a «yes» repeat with `--confirmed`. Without `needs_confirmation` nothing is deleted: no question. The script refuses (naming them) while the database has configurations made in Coolify and none of the skill's. A configuration made in Coolify (`origin: other`) is changed only with `--backup <uuid>` and if the user asks |
| «restore», «go back to yesterday's data», «the deploy broke, put the data back» | **First** check that the configuration has `ssh` (`V --server` → `server: skipped` means it has none): restoring needs it. None → say so, ask for the server's `user@host` and run `C init --ssh <user@host>` (keeps the rest of the configuration), or stop; do not suggest the panel's restore (it does not empty the database first and fails on tables created since). Then `C backup-status <app>` → show the backups (local date and time, size) and **ask which one**. Compare its `created_at` with `C last-deployment <app>` (any app with a database). Before the «yes», say: the `public` schema of the database is replaced by the backup — tables created since are removed too; a safety backup of the current data is taken first (unless the database holds nothing), and if the import fails the previous data is put back automatically; while the import runs (seconds for small databases, longer for large ones) the app sees an empty database and may answer errors; if a deployment came after the backup (it may have added migrations), the running code will work on the older tables and may fail until the code is rolled back or redeployed (asked after the restore). Explicit «yes» → `C backup-restore <app> --execution <uuid> --confirmed` (the safety backup cannot be skipped) → verify as after a rollback: `V https://<domain>` with `--routes` of the analysis when known, else `--accept-4xx` for Django and Laravel (`/` may not exist), and `--protected` if the app has a user and password; after a restore across a deployment a failing `V` is expected: say the data is restored and ask the next question, then verify again. After a restore across a deployment, ask **separately**: roll the code back to the version of the backup (`rollback`) — **recommend it when the user said the deployment broke something** (redeploying would run its migrations on the restored data again) — or redeploy the current code (`C deploy <app>`, when the newer code is wanted: its migrations run again on the restored data). `ok: false`: «no longer exists» → nothing was restored (pick another); `recovered: true` → the restore failed (`output`), the previous data is back; `recovered: false` → the database may be empty: say so plainly and give the copies named in `error` (restore the safety backup with `backup-restore`); `import_id` (still running, or contact lost) → the data may be half restored: later `C backup-restore-status <app> <import_id>`; if it ended in an error, restore the safety backup (`copy_in_container` names a second copy inside the database container, lost if the container is recreated); any other `ok: false` (no `recovered`, no `import_id`: ssh, size, «not a dump of this app's database», PostgreSQL older than 15, «busy», «could not copy», «could not empty») → nothing was restored, say why (a safety backup may already exist). Never chain a restore and a rollback without asking for each |
| «download a copy» | `C backup-download <app>` (needs `ssh` in the configuration) → give `file` and say it holds all the app's data (keep it private). It goes to `~/.config/coolify-ops/backups/<app>/`; `--out <folder>` only outside any git repository (the script refuses otherwise). Restore it elsewhere with `pg_restore` |
| `decommission <app>` | Explain what will be deleted (app, and the database if any: **offer `C backup-download <app>` first** — `--with-db` deletes the backups on the server too (`deleted.backups`), before anything else (if one cannot be deleted, the app and database are kept — the backups named in the error as deleted are already gone: fix it and run it again); if the user wants the copy and the download fails or needs the panel, do not ask about the decommission until they confirm they have the file). After an explicit «yes»: `C decommission <app> --confirmed [--with-db] [--with-project]`. If the database or project is not in `apps.json`, the script refuses before deleting anything: tell the user and offer to delete only the app. The script watches the server until Coolify's cleanup is done before removing the project; if `deleted.warning` appears, the project was kept: tell the user. Before asking, check `C status` for other apps with the same `repo`: say the project stays while they are in it, and name any that call this app (a frontend would lose its API). After it: `deleted.project_kept` = other apps of the repository are still in the project (it goes with the last one); `deleted.project_not_deleted` = Coolify refused (something else is still in the project): tell the user. It also deletes the app's local `secrets/<app>.env` and `.access` (listed in `deleted.local_files`) |

---

## Pushes (done by the user)

Give the exact command, ready to paste with `!`:
- New repository (private by default): `! gh repo create <owner>/<name> --private --source=<repo> --remote=origin --push`
  (`<repo>` = `git.root`; for an app folder the repository is named after `<repo>`'s folder, not after the app)
- Pending commits: `! git -C <repo> push`

A push publishes the whole repository. Before handing it over: `A <repo> --secrets` clean and `G state <path>` → tell the user what `to_push` lists (for
a new repository, every commit).

## Known issues
See `${CLAUDE_SKILL_DIR}/reference/troubleshooting.md` (ports, health check, old Node, SPA routes, public
Next/Vite variables, SSR frameworks, certificates, leftovers after deleting) and `${CLAUDE_SKILL_DIR}/reference/coolify-api.md`.
