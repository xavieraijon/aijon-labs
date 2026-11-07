# coolify-ops

*[Read in English](README.md)*

Skills de Claude Code para gestionar tu propio servidor [Coolify](https://coolify.io): le dices a Claude
«despliega este proyecto» y él lo analiza, le escribe un Dockerfile si no tiene, lo construye y lo prueba en tu
máquina, te enseña **un solo resumen** para confirmar y, tras tu «sí», lo publica con dominio HTTPS, base de datos
si hace falta y despliegue automático en cada push. Todo va por la API de Coolify, sin automatizar el navegador.

| Skill | Cómo se invoca | Qué hace |
|---|---|---|
| `deploy-app` | `/coolify-ops:deploy-app` | Despliega y gestiona apps (estado, logs, actualizar, variables, rollback, retirar) |
| `provision-server` | `/coolify-ops:provision-server` | Monta Coolify en un VPS o en casa paso a paso, comprobando cada paso (nunca usa contraseñas ni `sudo`) |

```
> monta Coolify en mi VPS usuario@203.0.113.10 con el dominio ejemplo.org
> /coolify-ops:provision-server diagnose usuario@mi-servidor
> /coolify-ops:provision-server check
> despliega ~/Projects/mi-tienda
> /coolify-ops:deploy-app status
> /coolify-ops:deploy-app logs mi-tienda
> /coolify-ops:deploy-app decommission app-de-prueba
```
Las órdenes de los scripts y de la skill están en inglés (`status`, `logs`, `decommission`…), pero puedes pedirlo
todo en castellano: Claude te responde en tu idioma.

## Qué puede desplegar

| Proyecto | Plantilla |
|---|---|
| Python con FastAPI | `python-fastapi` (uvicorn) |
| Python con Flask | `python-flask` (gunicorn) |
| Servidor Node (Express, Hono, Fastify, NestJS) | `node-server` |
| Next.js | `nextjs` |
| SPA: Angular, Vite (React/Vue/Svelte), Create React App | `spa-nginx` |
| Web estática | `static-nginx` |
| PHP sencillo | `php-apache` |
| Cualquier proyecto de un solo servicio con su propio `Dockerfile` (de cualquier framework) | se usa tal cual |

Con PostgreSQL privado opcional. **Todavía no** admite (la skill para y lo explica): monorepos, apps de varios
servicios, apps que necesitan MySQL/MariaDB, MongoDB o Redis y, salvo que traigan su propio `Dockerfile`, Django,
Laravel/Symfony, Nuxt, Astro y SvelteKit (estáticos o con SSR).

¿Nuevo en Coolify? Empieza por [Coolify desde cero](../../docs/es/coolify-desde-cero.md) antes de la
configuración de abajo, o deja que te guíe la skill `provision-server`.

## Requisitos

- Python 3.10+, `git`, [`gh`](https://cli.github.com) con sesión iniciada, y Docker (para la prueba local).
- Un servidor con Coolify v4 y una GitHub App como fuente, un dominio con comodín (`*.ejemplo.org`) apuntando a él
  y los puertos 80/443 abiertos para el HTTPS.
- Acceso de red desde tu máquina a la API de Coolify (misma red local o VPN, o un panel con URL pública).

## Configuración (una vez)

1. **Activa la API** en Coolify: *Settings → Advanced → API access → Enabled*, y pon en *Allowed IPs* tu red
   (p. ej. `192.168.1.0/24`) y pulsa *Save*.
2. **Crea un token** en *Keys & Tokens → API Tokens* (`/security/api-tokens`) con `read`, `write`, `deploy` y `delete`.
3. **Guarda el token** (nunca va en un repo ni en el chat). Elige una opción:
   - Llavero de macOS (copia antes el token):
     `security add-generic-password -U -a "$USER" -s coolify-api-token -w "$(pbpaste)" && pbcopy < /dev/null`
   - Cualquier sistema: guárdalo en `~/.config/coolify-ops/token` y hazle `chmod 600`.
   - O exporta `COOLIFY_TOKEN`.
4. Pide a Claude «configura coolify-ops». Ejecuta:
   ```bash
   coolify.py init --url http://<ip-de-coolify>:<puerto> --domain ejemplo.org --ssh usuario@servidor --reserved hooks --projects-dir ~/Projects
   ```
   que descubre el servidor y la GitHub App y guarda `~/.config/coolify-ops/config.json`.

### Permisos recomendados de Claude Code

Para que el flujo no te pida permiso a cada paso, añade a `permissions.allow` en `~/.claude/settings.json`:

```json
"Bash(docker build *)", "Bash(docker run *)", "Bash(docker rm *)", "Bash(docker image rm *)",
"Bash(docker info)", "Bash(ssh usuario@servidor *)"
```

La skill ya permite sus propios scripts. **El `git push` nunca se automatiza**: la skill prepara el commit y te da
el comando para que lo lances tú (`! git push`).

## Ficheros locales

| Ruta | Contenido |
|---|---|
| `~/.config/coolify-ops/config.json` | URL de Coolify, dominio base, uuids del servidor y de la GitHub App, ssh, carpeta de proyectos, límites por defecto |
| `~/.config/coolify-ops/apps.json` | Registro de las apps desplegadas (nombre → uuids, dominio) |
| `~/.config/coolify-ops/secrets/<app>.env` | Valores de las variables de cada app (`chmod 600`; lo crea `coolify.py env-template` con las claves vacías, y los valores vacíos nunca se suben) |

Cambia la carpeta con `COOLIFY_OPS_HOME`. Una configuración de la v0.1 en `~/.config/coolify-deploy/` se migra
sola.

## Seguridad

- Una sola confirmación por despliegue; rollback, retirar y borrar variables preguntan siempre.
- Bases de datos siempre privadas; nunca abre puertos ni usa subdominios reservados o en uso.
- Busca secretos en los ficheros que se subirían y para si encuentra alguno.
- Contraseñas y tokens enmascarados en toda la salida; los valores de las variables nunca se muestran.
- Límites de CPU y memoria en todas las apps.
- Usuario y contraseña opcionales en el dominio de una app (`coolify.py protect`); la contraseña se genera y se
  guarda en `~/.config/coolify-ops/secrets/<app>.access`.

## Scripts

Todos devuelven JSON y se pueden usar a mano. Están en `skills/deploy-app/scripts/`:

| Script | Uso |
|---|---|
| `coolify.py` | Cliente de la API (`coolify.py --help` lista las órdenes) |
| `repo.py state\|init\|commit <ruta>` | Git local para la skill: estado, `git init` con `.gitignore` y commit tras buscar secretos. No tiene push |
| `analyze.py <ruta>` | Análisis del proyecto; `--secrets` solo busca secretos |
| `prepare.py <ruta>` | Escribe Dockerfile, `.dockerignore` y `nginx.conf` desde las plantillas |
| `local_check.py <ruta> --port N` | Build y prueba con Docker en local; limpia siempre |
| `verify.py https://host` | Certificado, redirección, rutas, `--external` (check-host.net) y `--server` (ssh) |

Y en `skills/provision-server/scripts/`:

| Script | Uso |
|---|---|
| `server.py diagnose usuario@host` | Diagnóstico del servidor (solo lectura): sistema, arquitectura, RAM, disco, Docker, Coolify, puertos en uso, seguridad |
| `server.py dns ejemplo.org` | Comprueba el DNS comodín en un resolvedor público |
| `server.py ports 203.0.113.10 --private 8000` | 80/443 accesibles desde Internet y el puerto del panel cerrado (`--require-filtered` en un VPS: bloqueado por un cortafuegos) |
| `server.py health` | `/api/health` de Coolify y sus contenedores |

Ver también los [problemas frecuentes](skills/deploy-app/reference/troubleshooting.md) (en inglés) y la
[referencia de la API](skills/deploy-app/reference/coolify-api.md).
