# Problemas conocidos y cómo resolverlos

Aprendidos desplegando apps reales en Coolify v4.6 sobre una Raspberry Pi 5 (ARM64).

| Síntoma | Causa | Solución |
|---|---|---|
| 502 / 503 / «no available server» | La app escucha en `127.0.0.1`/`localhost`, o el puerto de Coolify (`ports_exposes`) no coincide con el de la app | Escuchar en `0.0.0.0`; el `EXPOSE` del Dockerfile y `--puerto` deben coincidir |
| El despliegue falla aunque la app funciona | Health check de Coolify activado en una imagen `slim`/`alpine` sin `curl` ni `wget` | Dejar `health_check_enabled=false` (es lo que hace `crear-app`) o instalar `curl` en la imagen |
| Build de Angular antiguo falla con errores de OpenSSL o de dependencias | Angular ≤ 14 necesita Node 16; Angular 15-16, Node 18 | `analizar.py` elige Node según la versión de Angular; forzar con `--var NODE_VERSION=16` |
| Al recargar una ruta de una SPA (p. ej. `/cart`) sale 404 | El servidor no devuelve `index.html` en rutas que no son ficheros | `nginx.conf` de la plantilla SPA con `try_files $uri $uri/ /index.html` |
| Angular ≥ 17 publica en `dist/<app>/browser` | El builder `application` añade `/browser` | `analizar.py` lo tiene en cuenta; revisar `BUILD_DIR` si la build no encuentra la carpeta |
| Variables `NEXT_PUBLIC_*` / `VITE_*` vacías en el navegador | Se incrustan al compilar; si solo están en ejecución no llegan | `variables-fichero` las marca también para la build |
| El certificado HTTPS no aparece | Let's Encrypt necesita los puertos 80 y 443 abiertos hacia el servidor y que el DNS apunte a la IP pública | `verificar.py` espera hasta 2 min; si sigue, comprobar puertos del router y DNS |
| Traefik no vuelve a pedir un certificado tras abrir los puertos | Traefik no reintenta si la configuración no cambia | Reiniciar el proxy de Coolify (`docker restart coolify-proxy` en el servidor) |
| `git push` bloqueado desde Claude Code | Decisión del usuario / clasificador de permisos | El usuario ejecuta el comando con `!` |
| El aviso (webhook) de GitHub no llega | La Webhook URL de la GitHub App apunta a una IP privada | En GitHub → Developer settings → GitHub Apps → la app → Webhook URL pública (ruta `/webhooks/source/github/events`) |
| La API devuelve 403 | La IP del Mac no está en «Allowed IPs» o el token no tiene permiso | Settings → Access and API; token con `read`, `write`, `deploy`, `delete` |
| 403 «Missing required permissions: delete» al borrar | El permiso `delete` es aparte de `write` | Crear un token nuevo que lo incluya (los permisos no se editan) |
| Tras retirar quedan volúmenes, imágenes o carpetas en el servidor | Se borró el proyecto antes de que Coolify terminara de borrar la app o la BD (lo hace en segundo plano) y su limpieza falló («Attempt to read property "project" on null» en el log) | `retirar` ya espera a que cada recurso dé 404 antes de borrar el proyecto. Restos antiguos: `docker volume rm`, `docker image rm` y `/data/coolify/{applications,databases}/<uuid>` |
| La API no responde | No estás en la red de casa ni en la VPN, o la API está desactivada | Conectar la VPN o activar la API |
| Un despliegue corta un proceso largo de la app | Cada despliegue reinicia el contenedor | Para apps con tareas largas, crear con `--sin-autodeploy` y desplegar a mano |
| La Pi se calienta mucho al compilar | Builds pesadas de Node/Angular | Normal 1-2 min; si pasa de 80 °C a menudo, mejorar ventilación |
