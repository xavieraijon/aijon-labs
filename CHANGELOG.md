# Changelog

All notable changes to the plugins of this marketplace. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and each plugin follows
[Semantic Versioning](https://semver.org) on its own.

## coolify-ops

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
