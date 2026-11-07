# Changelog

All notable changes to the plugins of this marketplace. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and each plugin follows
[Semantic Versioning](https://semver.org) on its own.

## coolify-ops

### Unreleased (0.3.0)

#### Added
- `deploy-app` deploys Nuxt, Astro, SvelteKit, Angular with SSR and React Router (framework mode) without a
  Dockerfile of their own. The analysis reads their configuration (never runs it) and picks a Node server (new
  `node-ssr` template) or a static site served by nginx. Next.js with `output: 'export'` is served as a static
  site.
- Projects that cannot run on a plain server (SvelteKit `adapter-auto`, Astro or Nitro adapters for other
  platforms, Nuxt 2, Angular Universal) are blocked with the exact change that would make them deployable.
- React Router and Astro (server): the analysis warns when the project does not trust its own domain
  (`allowedActionOrigins`, `security.allowedDomains`). Behind HTTPS their origin checks see `http://` and reject
  every form submission (400/403); the skill shows the line to add (`stack.origin_fix`) and adds it only if the
  user asks.
- `create-app --env-domain KEY` and `env-domain <app> KEY…` set a variable to the app's own domain (used for
  Angular's `NG_ALLOWED_HOSTS`). If the variable fails, `create-app` still returns the app's uuid.
- `env-push --buildtime KEY…` and `create-postgres --buildtime` make secret variables available at build time
  (SvelteKit `$env/static/*`, which the analysis now detects and lists in `build_time_env`). `env-push` reports
  `--buildtime` keys missing from the file.
- `local_check.py --build-env KEY=value` (build-time test values, through `ARG` lines in a temporary copy of the
  Dockerfile, as Coolify does) and `--expect TEXT`; `verify.py --expect TEXT` checks the page body (e.g. that
  Angular rendered it on the server).

#### Changed
- `nginx-spa.conf` falls back to the file the framework writes for client-side routes (`index.html`, `200.html`,
  `index.csr.html`, `__spa-fallback.html`) and no HTML page is cached. Static sites that are not single-page apps
  get `nginx-static.conf`, which now serves the site's own `404.html`.
- `prepare.py` refuses build folders, fallback files and environment values read from the project's config that
  are not plain paths or names, before writing anything.
- Angular 21 builds with Node 22 and Angular 22 with Node 24.
- `deploy-app` no longer assumes it must create the database: if the user brings their own PostgreSQL,
  `DATABASE_URL` is handled like any other variable and the summary says «external».
- `local_check.py` exits with a non-zero code when the check fails, and reports a missing Dockerfile as JSON.
- `repo.py init` also ignores the build output folder (`dist/`, `build/`…) when the image builds it, so a local
  build (which may hold inlined build-time values) is not committed. Plain static sites are not affected.
- Build folders of the new frameworks (`.output`, `.nuxt`, `.svelte-kit`, `.astro`, `.react-router`) are left out
  of the image, the analysis and the `.gitignore` written for new repositories.

#### Fixed
- `prepare.py --overwrite` regenerates a Dockerfile it wrote before (it used to skip any project that already had
  one, so the documented way to change e.g. the Node version did nothing).
- nginx redirects (e.g. `/about` → `/about/`) are relative, so they keep HTTPS and the host behind the proxy.
- React Router, Remix with Vite, SolidStart, Qwik City, Vike and TanStack Start projects were treated as a Vite
  single-page app served from `dist/`, which deployed a broken site without any warning; Analog was treated as a
  plain Angular app. Classic Remix keeps working with the `node-server` template.
- Angular with SSR was deployed with the static template and only a warning.
- Next.js with `output: 'export'` got the `nextjs` template, whose `next start` refuses to run with that option.

### 0.2.1 — 2026-11-07

#### Fixed
- `rollback` works again: Coolify 4.6 only accepts `{"commit": "<tag>"}` and rejected the `docker_tag` field
  with a 422. The rollback now returns its `deployment_uuid`, so the skill waits for it and verifies the app.
- `env-push` no longer uploads empty values. An empty `DATABASE_URL=` line used to overwrite the URL that
  `create-postgres` had just set. Skipped keys are reported by name (`skipped_empty`).
- Commands that take an app name now find apps missing from the local `apps.json` by looking them up on the
  server. Ambiguous names ask for the uuid.
- `provision-server` no longer depends on files that are not installed with the plugin. The hardening commands,
  the GitHub webhook proxy configuration and the example app are in `reference/server-setup.md`, and the guide
  is linked by URL.
- `provision-server` on a VPS: the health check no longer targets the panel port closed by the firewall, and
  the port check targets the public IP instead of the bare domain.
- `provision-server` on a VPS no longer lets the install start without a provider firewall: before installing,
  the panel ports must be `filtered`, not just `closed` (`server.py ports --require-filtered`).
- `decommission --with-db/--with-project` refuses before deleting anything when the database or project is not
  in the local registry, instead of silently skipping them; the registry entry is also found by uuid.
- A project that was not a git repository is now committed whole (with a `.gitignore`) before its first push,
  and a new repository is added to the GitHub App's access before deploying.

#### Added
- `repo.py`: the skill's only way to use git (`state`, `init` with a `.gitignore`, `commit` after a secrets scan).
  It has no push. `git` is no longer in `allowed-tools`, so a push can never be approved by the skill's
  permissions (the old `git -C *` pattern also matched `git -C <path> push`).
- `protect` command: user and password on an app's domain (Coolify's basic auth). The password is generated
  locally, saved in `secrets/<app>.access` (mode 600) and never printed.
- `env-push --only KEY…`: upload only some keys, so values changed in the panel are not overwritten.
- `provision-server` reference blocks for users without an ssh key, working as root on a fresh VPS, and a private
  network (Tailscale) to reach the API of a VPS.
- `env-template` command: creates `secrets/<app>.env` with empty keys (mode 600) without touching existing values.
- `analyze.py` blocks apps that need MySQL/MariaDB, MongoDB or Redis (only PostgreSQL can be created).

#### Changed
- Git remotes are printed without any credentials they contain, and GitHub repository names may contain dots.
- `decommission` also deletes the app's local `secrets/<app>.env` and `.access` files.
- `verify.py --protected`: for an app with a user and password, its routes must answer 401.
- A project with its own `Dockerfile` is deployed as is whatever its framework; the docs and the skill now agree.
- Listing rollback images is read-only and no longer needs `--confirmed`; rolling back still does.
- `deploy-app`: clear steps for folders without git or a GitHub remote, for local checks of apps that need a
  database, and for each result of the server check.
- `provision-server`: what to do if a password is pasted in the chat; also triggers on «check my server»;
  `check` works without a configuration.
- Spanish security policy completed (reporting steps, supported versions); both versions now describe what
  `allowed-tools` really allows.
- The guide's webhook check is done from outside the network and says which answers are expected.

### 0.2.0 — 2026-11-07

First public release.

#### Added
- Skill `provision-server`: guides the setup of a Coolify server on a VPS or a home server (diagnosis over ssh,
  wildcard DNS, ports seen from the Internet, hardening, install, API, GitHub App), checking every step. It never
  runs `sudo`, never handles passwords and never accepts unknown ssh host keys.
- Script `server.py` with `diagnose`, `dns`, `ports` and `health`.
- `env-delete` command (removes a variable and its preview copy).
- The API token can also be read from `~/.config/coolify-ops/token` (Linux and other systems without a Keychain).
- Tutorial «Coolify from scratch» in English and Spanish (`docs/en`, `docs/es`).
- Example app `examples/hello-fastapi` to try the whole flow.
- Bilingual repository: `README.md` / `README.es.md`, contributor guides, `SECURITY.md`, `CONTRIBUTING.md`, issue
  and pull request templates.
- CI on Python 3.10 and 3.13, plugin validation, and a check that no private IPs or e-mail addresses are committed.

#### Changed
- **Breaking:** plugin renamed `coolify-deploy` → `coolify-ops` and skill `desplegar-coolify` → `deploy-app`.
- **Breaking:** code, commands, JSON keys and messages in English (Claude still answers in the user's language).
  Commands: `check`, `init`, `status`, `domain-check`, `create-project`, `create-app`, `create-postgres`,
  `env-set`, `env-push`, `env-list`, `env-delete`, `deploy`, `wait`, `last-deployment`, `logs`, `rollback`,
  `decommission`.
- The configuration moves to `~/.config/coolify-ops/` (mode 700); a v0.1 configuration in
  `~/.config/coolify-deploy/` is migrated automatically.
- The API token needs the `delete` permission as well.
- `server.py ports` checks Coolify's realtime ports (6001/6002) too, submits all ports at once, waits longer for
  slow check-host nodes and backs off when check-host rate-limits.

#### Fixed
- `decommission` left volumes, images and folders on the server: Coolify answers 404 before its background
  cleanup runs, and deleting the project in between made that cleanup fail. It now watches the server over ssh
  until the cleanup has finished, only then deletes the project, and removes the deleted app's own images.
- `status` showed auto-deploy as unknown: it is now read from the app settings.
- `env-list` listed the preview copies of every variable.
- Remote ssh commands gave wrong results when the server user's login shell was zsh or fish: they now run
  through `sh -s`.
- `verify.py --external` failed when a check-host node gave no answer: that is now reported as partial.

## coolify-deploy (old name)

### 0.1.0 — 2026-11-06

#### Added
- First version of the `desplegar-coolify` skill: project analysis, Dockerfile from templates (FastAPI, Flask,
  Node, Next.js, SPA with nginx, static, PHP), local check with Docker, deployment through the Coolify API with
  HTTPS, optional private PostgreSQL, variables from a file, verification (certificate, routes, external access,
  server health) and the `estado`, `logs`, `actualizar`, `variables`, `rollback` and `retirar` modes.
