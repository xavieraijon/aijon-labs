# Coolify API used by the skills

Base: `<url>/api/v1` · Auth: `Authorization: Bearer <token>` · Checked against Coolify **v4.6.0**.
The token needs `read`, `read:sensitive`, `write`, `deploy` and `delete` (`root` is not needed). `read:sensitive`
is required by `GET /applications/{uuid}/logs` (`routes/api.php`); the scripts never print the values it exposes.
`delete` is a separate permission: without it every `DELETE` returns 403 «Missing required permissions: delete».

| `coolify.py` command | Method and path |
|---|---|
| `check` | `GET /version`, `GET /projects` |
| `init` | `GET /servers`, `GET /github-apps` |
| `status` | `GET /applications`, `GET /applications/{uuid}` (settings), `GET /databases`, and `GET /databases/{uuid}/backups` per PostgreSQL database (an error there is reported in that database's `backups.error`) |
| any `<app>` argument | a name missing from `apps.json` is looked up in `GET /applications` (exact `name`) |
| `domain-check` | `GET /applications` (`fqdn` field) |
| `create-project` | `GET /projects`, `POST /projects` (an existing project with the same name is reused: `created: false`) |
| `create-app` | `POST /applications/private-github-app` (`build_pack=dockerfile`, `ports_exposes`, `domains`, `limits_*`, `is_auto_deploy_enabled`, `health_check_enabled=false`, `instant_deploy=false`; `--base-dir /<folder>` → `base_directory`, the build context and the folder `--dockerfile` is relative to; `--watch-paths GLOB` (repeatable) → `watch_paths`, one glob per line, relative to the repository root, `!` excludes; paths are checked against Coolify's own pattern before any call); with `--env-domain KEY` it then sets `KEY=<domain>` as a runtime variable, with `--env-url KEY` `KEY=https://<domain>`, with `--env-generate KEY[:FORMAT]` a random secret (as `env-generate`), and reports failures in `env_errors` without losing `app_uuid` |
| `env-domain <app> KEY…` | `GET /applications/{uuid}` (`fqdn`) then `POST/PATCH /applications/{uuid}/envs` with the domain host |
| `env-url <app> KEY…` | Same as `env-domain`, with the value `https://<domain host>` (e.g. Laravel `APP_URL`) |
| `env-generate <app> KEY[:FORMAT]…` | `GET /applications/{uuid}/envs`; for each key not present, `POST /applications/{uuid}/envs` with a random value (`is_shown_once`, runtime only). Formats: none (`token_urlsafe(50)`) or `laravel` (`base64:` + 32 random bytes, as `php artisan key:generate`). Existing keys are kept, never rotated |
| `create-postgres [--env-key KEY]` | `POST /databases/postgresql` (`is_public=false`, `instant_deploy=true`; user and password generated locally); with `--app-uuid` the URL is set on the app as `DATABASE_URL`, or `KEY` (Laravel: `DB_URL`); then, unless `--backup none`, the scheduled backup as `backup-schedule` (a failure is `backup_warning`, not an error) |
| `env-set`, `env-push [--only KEY…] [--buildtime KEY…]`, `env-delete` (and `create-postgres --buildtime` for `DATABASE_URL`) | `GET/POST/PATCH/DELETE /applications/{uuid}/envs` (`is_literal`, `is_buildtime`, `is_runtime`, `is_shown_once`) |
| `env-template` | none: writes `secrets/<app>.env` locally (empty keys, mode 600) |
| `protect` | `PATCH /applications/{uuid}` with `is_http_basic_auth_enabled`, `http_basic_auth_username`, `http_basic_auth_password` (max 72 characters; applied on the next deployment) |
| `env-list` | `GET /applications/{uuid}/envs` (names only; preview copies hidden) |
| `deploy` | `POST /deploy?uuid=…&force=…` |
| `wait` | `GET /deployments/{uuid}` (final states: `finished`, `failed`, `cancelled-by-user`, `cancelled`) |
| `last-deployment` | `GET /deployments/applications/{uuid}?take=1` |
| `logs` | `GET /applications/{uuid}/logs?lines=…` |
| `rollback` | `GET /applications/{uuid}/rollback-images` (→ `current`, `images[]` with `tag`, `created_at`, `is_current`, `source`), `POST /applications/{uuid}/rollback` with body `{"commit": "<tag>"}` only — any other field is rejected with 422 (→ `deployment_uuid`) |
| every `backup-*` | `GET /version` (4.6.0 or later, else refused), `GET /databases/{uuid}` (`database_type` must be `standalone-postgresql`) |
| `backup-status` | `GET /databases/{uuid}/backups` (configurations with their `executions`: `uuid`, `filename`, `size`, `status`, `created_at`, `local_storage_deleted`) |
| `backup-schedule` | no skill-made scheduled configuration → `POST /databases/{uuid}/backups` `{frequency, enabled: true, save_s3: false, database_backup_retention_amount_locally, timeout: 3601}` (refused, naming them, while the database has configurations made in Coolify; `--backup <uuid>` changes one of those instead); else `PATCH /databases/{uuid}/backups/{backup}` with only the changed fields (`frequency` is optional on update). A lower `--keep` that would delete backups answers `needs_confirmation` until `--confirmed` |
| `backup-now` | manual configuration missing → `POST …/backups` `{frequency: "0 0 1 1 *", enabled: false, save_s3: false, backup_now: true, database_backup_retention_amount_locally: 5, timeout: 3599}`; else `PATCH …/backups/{backup}` `{backup_now: true}`; then `GET …/backups/{backup}/executions` every 5 s until a new execution is `success` or `failed` |
| `backup-restore` | `backup-now` (safety backup, always: there is no option to skip it; `--backup-timeout`, default 900 s), the chosen execution read again, `POST /databases/{uuid}/imports` `{source: "server", path: <execution filename>, replace_existing: true}` (→ `id`), `GET /databases/{uuid}/imports/{id}` until `finished`, `error`, `killed`, `cancelled` or `closed` (`--timeout`, default 1800 s) |
| `backup-restore-status` | `GET /databases/{uuid}/imports/{id}` (the id must be a number) |
| `backup-download` | no API: over ssh, `docker exec <db uuid> pg_dump --format=custom` with the container's own `POSTGRES_USER`/`POSTGRES_DB` |
| `decommission` | `DELETE /applications/{uuid}`, `DELETE /databases/{uuid}`, `GET` until 404, server watched over ssh until the cleanup job is done, then `DELETE /projects/{uuid}` — skipped (`project_kept`) while another app in `apps.json` uses the same project |

Notes:
- A database's internal URL is `postgres://user:password@<database-uuid>:5432/<db>`: the host is the uuid and only
  resolves inside the server's Docker network.
- `is_buildtime`/`is_runtime` are not documented for creating variables, but the API accepts them (verified).
- Every variable gets a twin with `is_preview=true` for preview deployments; `env-list` hides them and
  `env-delete` removes both.
- The applications list has no `settings`; auto-deploy (`settings.is_auto_deploy_enabled`) needs the detail call.
- Deletions run in the background (`DeleteResourceJob`). The API answers 404 *before* that job runs, so a 404 does
  not mean the server is clean. Deleting the parent project too early breaks the job (verified on v4.6.0).
- Watch paths (verified on v4.6.0): a push redeploys the app only if a changed file matches one of the globs
  (`*`, `**`, `?`, `[…]`, `!` exclusion, the last match wins). With no watch paths, or when the push carries no file
  list, every push deploys. Manual `deploy` calls ignore them.
- `DELETE /projects/{uuid}` answers 400 «Project has resources» while anything is left in the project.
- Backups (verified on v4.6.0): `pg_dump --format=custom` into
  `/data/coolify/backups/databases/<team>-<id>/<db-name>-<db-uuid>/` (root only). Retention is **per backup
  configuration** and its default is 0 = keep everything; after every run Coolify deletes the files of successful
  backups beyond the limit. A stopped database is skipped without any execution. `backup_now` needs the `deploy`
  permission and also runs a disabled configuration. The skill tells its two configurations apart by `timeout`
  (3601 scheduled, 3599 manual) and never changes others unless `--backup <uuid>` is given.
- Restore (verified on v4.6.0): the file must be inside this database's backup folder; Coolify first scans the dump
  for `COPY … PROGRAM` and psql shell commands, then runs `pg_restore --exit-on-error --single-transaction
  --no-owner --no-acl --clean --if-exists`. `--clean` drops only objects that are in the dump: tables created after
  the backup stay, and a later table with a foreign key to a restored one makes the whole restore fail (nothing
  changes). Imports need `write` and `deploy`.
