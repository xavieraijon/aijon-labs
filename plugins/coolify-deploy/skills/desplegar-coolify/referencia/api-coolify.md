# API de Coolify usada por la skill

Base: `<url>/api/v1` · Autenticación: `Authorization: Bearer <token>` · Comprobado con la especificación OpenAPI de
Coolify **v4.6.0**. El token necesita los permisos `read`, `write`, `deploy` y `delete` (no hace falta `root` ni `read:sensitive`).
`delete` es un permiso aparte: sin él, todos los `DELETE` devuelven 403 «Missing required permissions: delete».

| Orden de `coolify.py` | Método y ruta |
|---|---|
| `comprobar` | `GET /version`, `GET /projects` |
| `config-init` | `GET /servers`, `GET /github-apps` |
| `estado` | `GET /applications`, `GET /databases` |
| `dominio-libre` | `GET /applications` (campo `fqdn`) |
| `crear-proyecto` | `GET /projects`, `POST /projects` |
| `crear-app` | `POST /applications/private-github-app` (`build_pack=dockerfile`, `ports_exposes`, `domains`, `limits_*`, `is_auto_deploy_enabled`, `health_check_enabled=false`, `instant_deploy=false`) |
| `crear-postgres` | `POST /databases/postgresql` (`is_public=false`, `instant_deploy=true`; usuario y contraseña generados en local) |
| `variable`, `variables-fichero`, `borrar-variable` | `GET/POST/PATCH/DELETE /applications/{uuid}/envs` (`is_literal`, `is_buildtime`, `is_runtime`, `is_shown_once`) |
| `variables` | `GET /applications/{uuid}/envs` (solo se muestran nombres) |
| `desplegar` | `POST /deploy?uuid=…&force=…` |
| `esperar` | `GET /deployments/{uuid}` (estados finales: `finished`, `failed`, `cancelled-by-user`) |
| `ultimo-despliegue` | `GET /deployments/applications/{uuid}?take=1` |
| `logs` | `GET /applications/{uuid}/logs?lines=…` |
| `rollback` | `GET /applications/{uuid}/rollback-images`, `POST /applications/{uuid}/rollback` |
| `retirar` | `DELETE /applications/{uuid}`, `DELETE /databases/{uuid}`, `DELETE /projects/{uuid}` |

Notas:
- La URL interna de una base de datos es `postgres://usuario:contraseña@<uuid-de-la-bd>:5432/<bd>`: el host es el uuid,
  y solo se resuelve dentro de la red Docker del servidor.
- La especificación no documenta `is_buildtime`/`is_runtime` en el alta de variables, pero el objeto los tiene;
  `coolify.py` los envía y la prueba real confirma el resultado leyendo las variables.
