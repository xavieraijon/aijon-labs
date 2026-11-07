# Coolify API used by the skills

Base: `<url>/api/v1` · Auth: `Authorization: Bearer <token>` · Checked against Coolify **v4.6.0**.
The token needs `read`, `write`, `deploy` and `delete` (`root` and `read:sensitive` are not needed).
`delete` is a separate permission: without it every `DELETE` returns 403 «Missing required permissions: delete».

| `coolify.py` command | Method and path |
|---|---|
| `check` | `GET /version`, `GET /projects` |
| `init` | `GET /servers`, `GET /github-apps` |
| `status` | `GET /applications`, `GET /applications/{uuid}` (settings), `GET /databases` |
| any `<app>` argument | a name missing from `apps.json` is looked up in `GET /applications` (exact `name`) |
| `domain-check` | `GET /applications` (`fqdn` field) |
| `create-project` | `GET /projects`, `POST /projects` |
| `create-app` | `POST /applications/private-github-app` (`build_pack=dockerfile`, `ports_exposes`, `domains`, `limits_*`, `is_auto_deploy_enabled`, `health_check_enabled=false`, `instant_deploy=false`) |
| `create-postgres` | `POST /databases/postgresql` (`is_public=false`, `instant_deploy=true`; user and password generated locally) |
| `env-set`, `env-push [--only KEY…]`, `env-delete` | `GET/POST/PATCH/DELETE /applications/{uuid}/envs` (`is_literal`, `is_buildtime`, `is_runtime`, `is_shown_once`) |
| `env-template` | none: writes `secrets/<app>.env` locally (empty keys, mode 600) |
| `protect` | `PATCH /applications/{uuid}` with `is_http_basic_auth_enabled`, `http_basic_auth_username`, `http_basic_auth_password` (max 72 characters; applied on the next deployment) |
| `env-list` | `GET /applications/{uuid}/envs` (names only; preview copies hidden) |
| `deploy` | `POST /deploy?uuid=…&force=…` |
| `wait` | `GET /deployments/{uuid}` (final states: `finished`, `failed`, `cancelled-by-user`, `cancelled`) |
| `last-deployment` | `GET /deployments/applications/{uuid}?take=1` |
| `logs` | `GET /applications/{uuid}/logs?lines=…` |
| `rollback` | `GET /applications/{uuid}/rollback-images` (→ `current`, `images[]` with `tag`, `created_at`, `is_current`, `source`), `POST /applications/{uuid}/rollback` with body `{"commit": "<tag>"}` only — any other field is rejected with 422 (→ `deployment_uuid`) |
| `decommission` | `DELETE /applications/{uuid}`, `DELETE /databases/{uuid}`, `GET` until 404, server watched over ssh until the cleanup job is done, then `DELETE /projects/{uuid}` |

Notes:
- A database's internal URL is `postgres://user:password@<database-uuid>:5432/<db>`: the host is the uuid and only
  resolves inside the server's Docker network.
- `is_buildtime`/`is_runtime` are not documented for creating variables, but the API accepts them (verified).
- Every variable gets a twin with `is_preview=true` for preview deployments; `env-list` hides them and
  `env-delete` removes both.
- The applications list has no `settings`; auto-deploy (`settings.is_auto_deploy_enabled`) needs the detail call.
- Deletions run in the background (`DeleteResourceJob`). The API answers 404 *before* that job runs, so a 404 does
  not mean the server is clean. Deleting the parent project too early breaks the job (verified on v4.6.0).
