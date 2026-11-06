---
name: desplegar-coolify
description: Prepara y despliega en Coolify proyectos propios (carpeta local o repo de GitHub) con dominio HTTPS, base de datos opcional y despliegue automático en cada push; también consulta el estado, ve logs, actualiza, hace rollback o retira apps. Úsala cuando el usuario pida desplegar, publicar o subir una app o web a su servidor o a Coolify, o gestionar las apps que ya tiene allí.
argument-hint: "[ruta | owner/repo | estado | logs <app> | actualizar <app> | variables <app> | rollback <app> | retirar <app>]"
allowed-tools: Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*), Bash(git status*), Bash(git -C *), Bash(git add *), Bash(git commit *), Bash(git log *), Bash(gh repo view *), Bash(gh repo clone *)
---

# Desplegar en Coolify

Despliega proyectos del usuario en su servidor Coolify **por la API** (nunca por el navegador). Todo lo que hace
falta está en los scripts de `${CLAUDE_SKILL_DIR}/scripts/`, que devuelven JSON:

| Script | Para qué |
|---|---|
| `coolify.py` | API de Coolify: comprobar, estado, proyectos, apps, BD, variables, desplegar, esperar, logs, rollback, retirar |
| `analizar.py` | Analiza un proyecto (solo lectura) y dice si es desplegable, con qué plantilla y por qué no |
| `preparar.py` | Crea Dockerfile / .dockerignore / nginx.conf desde `plantillas/` (nunca sobrescribe) |
| `probar_local.py` | Construye y prueba la imagen en el Mac y limpia siempre |
| `verificar.py` | Comprueba la app publicada (HTTPS, rutas, acceso externo) y la salud del servidor |

Abreviaturas en este documento: `C=python3 -I ${CLAUDE_SKILL_DIR}/scripts/coolify.py`, y lo mismo `A` (analizar),
`P` (preparar), `L` (probar_local) y `V` (verificar). **Escribe siempre la orden completa**, no las abreviaturas.

Configuración del usuario (fuera del repo): `~/.config/coolify-deploy/config.json` (url, dominio base, uuids, ssh,
subdominios reservados, carpeta de proyectos), `apps.json` (registro de apps desplegadas), `secretos/<app>.env` (valores de variables).
El token de la API está en el Llavero de macOS (servicio `coolify-api-token`). **Nunca muestres tokens ni contraseñas.**

---

## Reglas fijas (no se saltan nunca)

1. **Una sola confirmación por despliegue nuevo**: el resumen del paso D. Antes, todo es de solo lectura o en local;
   después, todo es automático. `rollback` y `retirar` piden confirmación aparte, **siempre**.
2. **Subir a GitHub lo hace el usuario.** No ejecutes `git push`, `gh repo create --push` ni nada que suba código.
   Prepara el commit y dale el comando exacto para que lo lance con `!` (ver «Pushes»). Espera a que lo haga.
3. **Secretos:** si `analizar.py` encuentra secretos en ficheros que se subirían, **para** y explica qué y dónde (sin
   mostrar valores). Antes de cada push, `A <ruta> --secretos` debe salir limpio. Los valores de las variables nunca
   pasan por el chat: van en `~/.config/coolify-deploy/secretos/<app>.env` y se suben con `variables-fichero`.
4. **Nunca** hagas pública una base de datos ni abras puertos del router. Nunca uses un subdominio reservado o en uso
   (`C dominio-libre` lo comprueba).
5. **Límites de CPU/RAM siempre** (por defecto los de la config). Health check de Coolify desactivado salvo que la imagen
   tenga `curl`/`wget`.
6. **Solo se toca la lógica de la app si el usuario lo pide.** Lo que añade la skill son ficheros de despliegue.
7. Si el servidor está por encima de 80 °C o con el disco por encima del 90 %, avisa y no construyas.
8. **Máximo 2 reintentos automáticos** por fallo de build/arranque, y solo cambiando ficheros de despliegue. Después,
   para y explica con las últimas líneas del log.
9. Alcance v1: apps de **un solo servicio** (Python FastAPI/Flask, Node, Next.js, SPA, estática, PHP sencillo) con
   PostgreSQL opcional. Monorepos, varios servicios, Django, Laravel, SSR de Nuxt/Astro/SvelteKit: **para y explica**.

---

## Despliegue de una app nueva

### A · Comprobaciones previas
1. `C comprobar` → si falla, guía al usuario según el error (API desactivada, IP no permitida, token, no está en casa/VPN).
   Si no hay configuración: `C config-init --url <URL> --dominio <dominio> --ssh <usuario@host> --reservado hooks --proyectos <carpeta>`
   (pide los datos al usuario la primera vez).
2. `V --servidor` → temperatura, disco y Coolify sanos (regla 7).

### B · Análisis
- Si te dan `owner/repo` y no está en local: `gh repo clone owner/repo <carpeta_proyectos>/<repo>` (la carpeta está
  en `config.json`; los proyectos nuevos también se crean ahí).
- `A <ruta>` y lee: `desplegable`, `bloqueos`, `avisos`, `stack`, `variables`, `bases_de_datos`, `secretos`,
  `tiene_login_estimado`, `servicios_de_pago_estimados`, `git`.
- Si hay **bloqueos**, para aquí y explícalos con lo que haría falta para resolverlos.
- Si la app usa servicios de pago y no tiene login, el acceso por defecto sigue siendo público **pero** el resumen
  debe proponer protegerla (usuario/contraseña del proxy) y pedir que el usuario lo elija explícitamente.

### C · Preparación y prueba en local
1. `P <ruta>` (usa `--var CLAVE=valor` si el análisis se equivocó en algo, p. ej. el puerto o el módulo).
2. `L <ruta> --puerto <puerto> --rutas / [otras rutas relevantes]` (añade `--env` solo con valores de prueba).
3. Si falla: lee `error_build` / `logs_contenedor`, corrige **solo** ficheros de despliegue y repite (regla 8).
4. Si funciona y hay ficheros nuevos: `git add` de esos ficheros y `git commit -m "build: despliegue en Coolify (…)"`.

### D · Resumen y confirmación (la única pregunta)
Comprueba el dominio con `C dominio-libre <nombre>` y presenta exactamente este bloque:
```
App:         <nombre>  (<framework>, <plantilla o Dockerfile propio>)
Repo:        <owner/repo> · rama <rama> · <qué hay que subir: commits / repo nuevo / nada>
Dominio:     https://<nombre>.<dominio_base>   (<libre ✔ | motivo>)
Acceso:      público | protegido con usuario y contraseña
Base datos:  no | PostgreSQL 17 (nueva, privada)
Variables:   <nombres> (valores en ~/.config/coolify-deploy/secretos/<nombre>.env) | ninguna
Recursos:    máx. <cpus> CPU / <memoria>
Autodeploy:  sí (cada push publica) | no
Avisos:      <lista o «ninguno»>
Prueba local: OK (<segundos> s de build, rutas <…>)
```
Si hay variables necesarias, crea `~/.config/coolify-deploy/secretos/<nombre>.env` con las claves **vacías** y
`chmod 600`, y pide al usuario que rellene los valores (nunca se los pidas por el chat). Espera su «sí».

### E · Ejecución (sin más preguntas)
1. **Subir a GitHub** (si hace falta): ver «Pushes». Espera a que el usuario lo haga y comprueba con
   `git -C <ruta> status -sb` que no queda nada por subir.
2. `C crear-proyecto <nombre>` → `proyecto_uuid`.
3. `C crear-app --proyecto <uuid> --repo <owner/repo> --rama <rama> --puerto <puerto> --dominio <nombre> --nombre <nombre>`
   (+ `--cpus`/`--memoria` si no valen los de por defecto, `--sin-autodeploy` si se eligió) → `app_uuid`.
4. Si lleva PostgreSQL: `C crear-postgres --proyecto <uuid> --nombre <nombre> --app <nombre> --app-uuid <app_uuid>`
   (crea la BD privada y añade `DATABASE_URL` a la app; la contraseña la genera el script y nunca sale en claro).
5. Si hay variables: `C variables-fichero <nombre> ~/.config/coolify-deploy/secretos/<nombre>.env`.
6. `C desplegar <nombre>` → `deployment_uuid`; `C esperar <deployment_uuid>`.
7. Si `ok` es false: diagnostica con `ultimas_lineas` (y `C logs <nombre>`), corrige ficheros de despliegue,
   commit, push por el usuario y reintenta (regla 8).

### F · Verificación
`V https://<dominio> --rutas / [rutas] --externo --servidor`. Si el certificado aún no es válido, espera (el
script ya espera hasta 2 min). Si `externo_no_verificado`, dilo, pero no es un fallo.

### G · Cierre
Resume en pocas líneas: URL, qué se creó (proyecto, app, BD), resultado de la verificación, y cómo se actualiza
(«haz push a <rama> y se publica solo»). El registro local (`apps.json`) ya lo actualizan los scripts.

---

## Otros modos

| Petición | Qué hacer |
|---|---|
| `estado` | `C estado` → tabla: app, estado, dominio, último despliegue (`C ultimo-despliegue <app>` si hace falta) |
| `logs <app>` | `C logs <app>` y `C ultimo-despliegue <app>`; resume errores |
| `actualizar <app>` | Commit local si hay cambios → push por el usuario → `C ultimo-despliegue <app>` hasta ver el nuevo commit → `C esperar …` → `V …`. Si el autodeploy está desactivado: `C desplegar <app>` |
| `variables <app>` | `C variables <app>` (solo nombres). Para cambiar: editar `secretos/<app>.env` (el usuario) → `C variables-fichero …` → `C desplegar <app>`. Para borrar una: confirmar con el usuario → `C borrar-variable <app> <CLAVE> --confirmado` |
| `rollback <app>` | `C rollback <app> --confirmado` lista imágenes; **pregunta cuál** y confirma → `C rollback <app> --imagen <tag> --confirmado` |
| `retirar <app>` | Explica qué se borra (app, y BD si la hay: **antes ofrece copia**). Tras un «sí» explícito: `C retirar <app> --confirmado [--con-bd] [--con-proyecto]` |

---

## Pushes (los hace el usuario)

Da el comando exacto, listo para pegar con `!`:
- Repo nuevo (privado por defecto): `! gh repo create <owner>/<nombre> --private --source=<ruta> --remote=origin --push`
- Commits pendientes: `! git -C <ruta> push`

Antes de dárselo: `A <ruta> --secretos` limpio y `git -C <ruta> log --oneline @{u}..HEAD` para decirle qué sube.

## Problemas conocidos
Ver `${CLAUDE_SKILL_DIR}/referencia/problemas-conocidos.md` (puertos, health check, Node antiguo, SPA y rutas,
variables públicas de Next/Vite, certificados).
