# coolify-deploy

Skill `desplegar-coolify`: le dices a Claude Code «despliega este proyecto» y él lo analiza, le crea el Dockerfile si
no lo tiene, lo prueba en tu ordenador, te enseña **un único resumen** para confirmar y, tras tu «sí», lo publica en
tu Coolify con dominio HTTPS, base de datos si hace falta y despliegue automático en cada push. Todo por la API de
Coolify: sin navegador.

```
> despliega ~/proyectos/mi-tienda
> /desplegar-coolify estado
> /desplegar-coolify logs mi-tienda
> /desplegar-coolify retirar app-de-prueba
```

## Qué sabe desplegar (v0.1)

| Proyecto | Plantilla |
|---|---|
| Python con FastAPI | `python-fastapi` (uvicorn) |
| Python con Flask | `python-flask` (gunicorn) |
| Servidor Node (Express, Hono, Fastify, NestJS) | `node-server` |
| Next.js | `nextjs` |
| SPA: Angular, Vite (React/Vue/Svelte), Create React App | `spa-nginx` |
| Web estática | `static-nginx` |
| PHP sin framework | `php-apache` |
| Cualquier proyecto con su propio `Dockerfile` | se respeta tal cual |

Con PostgreSQL privado opcional. **No** cubre (se detiene y lo explica): monorepos, apps de varios servicios,
Django, Laravel/Symfony ni SSR de Nuxt/Astro/SvelteKit.

## Requisitos

- macOS con Python 3.10+, `git`, [`gh`](https://cli.github.com) autenticado y Docker Desktop (para la prueba local).
- Un servidor con Coolify v4 y:
  - una **GitHub App** conectada (Sources) con acceso a tus repos;
  - un dominio comodín apuntando al servidor (p. ej. `*.midominio.org`) y los puertos 80/443 abiertos para HTTPS.
- Acceso a la API de Coolify desde tu ordenador (misma red o VPN).

## Configuración (una vez)

1. **Activa la API** en Coolify: *Settings → Access and API → API Access*, y en *Allowed IPs* pon tu red
   (p. ej. `192.168.1.0/24`).
2. **Crea un token** en *Keys & Tokens → API tokens* con los permisos `read`, `write` y `deploy`
   (no hace falta `root` ni `read:sensitive`).
3. **Guárdalo en el Llavero** (el token no se escribe en ningún fichero ni pasa por el chat):
   ```bash
   security add-generic-password -a "$USER" -s coolify-api-token -w
   ```
4. Pide a Claude «configura coolify-deploy». Ejecutará:
   ```bash
   coolify.py config-init --url http://<ip-coolify>:<puerto> --dominio midominio.org --ssh usuario@servidor --reservado hooks
   ```
   que descubre el servidor y la GitHub App y lo guarda en `~/.config/coolify-deploy/config.json`.

### Permisos recomendados de Claude Code

Para que el flujo sea automático, añade a `~/.claude/settings.json` (en `permissions.allow`):

```json
"Bash(docker build *)", "Bash(docker run *)", "Bash(docker rm *)", "Bash(docker image rm *)",
"Bash(docker info)", "Bash(ssh usuario@servidor *)"
```

La skill ya concede permiso a sus propios scripts. **`git push` nunca se automatiza**: la skill prepara el commit y
te da el comando para que lo ejecutes tú (`! git push`).

## Ficheros locales

| Ruta | Contenido |
|---|---|
| `~/.config/coolify-deploy/config.json` | URL de Coolify, dominio base, uuids del servidor y la GitHub App, ssh, límites por defecto |
| `~/.config/coolify-deploy/apps.json` | Registro de las apps desplegadas (nombre → uuids, dominio) |
| `~/.config/coolify-deploy/secretos/<app>.env` | Valores de las variables de cada app (`chmod 600`) |

Se puede cambiar la carpeta con la variable `COOLIFY_DEPLOY_HOME`, y usar `COOLIFY_TOKEN` en lugar del Llavero.

## Seguridad

- Una sola confirmación por despliegue; `rollback` y `retirar` piden permiso siempre.
- Bases de datos siempre privadas; nunca abre puertos ni usa subdominios reservados o en uso.
- Escanea secretos en los ficheros que se subirían y se detiene si encuentra alguno.
- Contraseñas y tokens enmascarados en toda la salida; los valores de las variables nunca se muestran.
- Límites de CPU y memoria en todas las apps.

## Scripts

Todos devuelven JSON y se pueden usar a mano. Están en `skills/desplegar-coolify/scripts/`:

| Script | Uso |
|---|---|
| `coolify.py` | Cliente de la API (`coolify.py --help` para ver las órdenes) |
| `analizar.py <ruta>` | Análisis del proyecto; `--secretos` solo escanea secretos |
| `preparar.py <ruta>` | Genera Dockerfile, `.dockerignore` y `nginx.conf` desde las plantillas |
| `probar_local.py <ruta> --puerto N` | Build y prueba con Docker en local; limpia siempre |
| `verificar.py https://host` | Certificado, redirección, rutas, `--externo` (check-host.net) y `--servidor` (ssh) |

Ver también [problemas conocidos](skills/desplegar-coolify/referencia/problemas-conocidos.md) y la
[API usada](skills/desplegar-coolify/referencia/api-coolify.md).
