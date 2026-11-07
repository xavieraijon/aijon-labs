# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Cada plugin tiene su propia versión.

## coolify-ops

### 0.2.0 — 2026-11-07
- Renamed: plugin `coolify-deploy` → `coolify-ops`, skill `desplegar-coolify` → `deploy-app`.
- Code, commands, JSON keys and messages in English (Claude still answers in the user's language).
  New command names: `check`, `init`, `status`, `domain-check`, `create-project`, `create-app`, `create-postgres`,
  `env-set`, `env-push`, `env-list`, `env-delete`, `deploy`, `wait`, `last-deployment`, `logs`, `rollback`,
  `decommission`.
- Token can also come from `~/.config/coolify-ops/token` (Linux and other systems without a Keychain).
- The v0.1 configuration (`~/.config/coolify-deploy`, Spanish keys) is migrated automatically.
- `decommission` waits for Coolify to finish deleting the app and database before deleting the project
  (it used to leave volumes, images and folders behind).
- `status` reads auto-deploy from the app settings; `env-list` hides preview copies; new `env-delete`.
- The token needs the `delete` permission as well.
- New skill `provision-server`: guides the setup of a Coolify server (diagnosis over ssh, wildcard DNS, ports from
  the Internet, hardening, install, API, GitHub App), checking every step; never runs `sudo` or handles passwords.
  New script `server.py` (`diagnose`, `dns`, `ports`, `health`).
- Tutorial «Coolify from scratch» in English and Spanish (`docs/en`, `docs/es`).
- Example app `examples/hello-fastapi` to try the whole flow.
- Bilingual repository: `README.md`/`README.es.md`, contributor guides in `docs/en` and `docs/es`, `SECURITY.md`,
  `CONTRIBUTING.md`, issue and pull request templates.
- CI on Python 3.10 and 3.13 plus a check that no private IPs or e-mail addresses are committed.
- Remote ssh commands run through `sh -s`, so they work whatever the login shell of the server user (zsh, fish…).

## coolify-deploy (old name)

### 0.1.0 — 2026-11-06
- Primera versión de la skill `desplegar-coolify`: análisis del proyecto, Dockerfile desde plantillas
  (FastAPI, Flask, Node, Next.js, SPA con nginx, estática, PHP), prueba local con Docker, despliegue por la API
  de Coolify con HTTPS, PostgreSQL privado opcional, variables desde fichero, verificación (certificado, rutas,
  acceso desde fuera, salud del servidor) y modos `estado`, `logs`, `actualizar`, `variables`, `rollback`, `retirar`.
