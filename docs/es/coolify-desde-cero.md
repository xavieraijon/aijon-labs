# Coolify desde cero

Guía paso a paso para tener tu propio servidor [Coolify](https://coolify.io) —una alternativa autoalojada a
Heroku/Vercel— y usar después el plugin `coolify-ops` para desplegar tus proyectos en él. No necesitas saber
Docker ni administración de servidores; cada comando va completo.

La skill `provision-server` de este plugin sigue esta misma guía contigo: comprueba cada paso (diagnóstico de
solo lectura, DNS, puertos vistos desde Internet, salud de Coolify) y te acompaña en los que necesitan tu
contraseña de `sudo` o el navegador, que nunca hace por ti. La guía también sirve sola, a mano.

## 1 · Qué necesitas

**El servidor**
- Una máquina siempre encendida: un **VPS** (unos pocos euros al mes) o un **ordenador en casa** (una Raspberry
  Pi 4/5, un portátil viejo, un mini-PC). 2 GB de RAM es el mínimo para Coolify y apps pequeñas; con 4 GB vas más
  holgado si vas a compilar apps de Node o Angular en él. 20 GB de disco libre o más.
- CPU de 64 bits: x86_64 o ARM64 (Coolify y las plantillas Docker de este plugin admiten ambas).
- Debian o Ubuntu (otras distribuciones suelen valer; esta guía asume una de estas dos).
- Acceso por `ssh` con un usuario que pueda usar `sudo`.
- Un dominio que controles, aunque sea gratuito (paso 3).

**Tu ordenador** (donde se ejecuta Claude Code)
- [Claude Code](https://code.claude.com), Python 3.10+, `git`, la CLI de GitHub [`gh`](https://cli.github.com)
  con sesión iniciada (`gh auth login`) y Docker (Docker Desktop en macOS/Windows) para la prueba local.
- El plugin, desde Claude Code:
  ```
  /plugin marketplace add xavieraijon/aijon-labs
  /plugin install coolify-ops@aijon-labs
  ```

## 2 · Elige dónde va a vivir

| | VPS | Servidor en casa |
|---|---|---|
| IP pública | Fija, la da el proveedor | Suele cambiar; hace falta DNS dinámico |
| Puesta en marcha | Más rápida: nada que configurar en un router | Reenvías dos puertos en tu router |
| Cortafuegos | El **cortafuegos del proveedor** (paso 4) | Tu router: solo es accesible lo que reenvías |
| Coste | Cuota mensual | Solo la luz, con hardware que quizá ya tienes |
| Fiabilidad | La del proveedor | Depende de tu luz e internet |

**En un VPS**, vale cualquier proveedor que te dé acceso SSH como root a una máquina Debian/Ubuntu recién creada.
Apunta su IP pública; a ella apuntará tu dominio. Elige uno que tenga **cortafuegos de red** en su panel (casi
todos: Hetzner, DigitalOcean, Vultr, OVH, AWS…): lo necesitarás en el paso 4.

**En casa**, comprueba esto antes de nada:
- **Que no estás detrás de CGNAT.** Algunos operadores no te dan una IP pública real. Desde el servidor, ejecuta
  `curl -4 ifconfig.me` y compáralo con la IP WAN de la página de estado de tu router. Si son distintas, estás
  detrás de CGNAT y el reenvío de puertos no puede funcionar: pide una IP pública a tu operador (a menudo es
  gratis si la pides) o usa un túnel (p. ej. Cloudflare Tunnel, fuera del alcance de esta guía).
- **Dale al servidor una dirección fija en tu red** (una reserva DHCP en el router) para que el reenvío de
  puertos siga funcionando después de un reinicio.
- **Reenvía solo los puertos 80 y 443** del router a esa dirección. Nunca reenvíes el puerto del panel de Coolify.
- Para abrir tus apps desde dentro de tu propia red por su nombre público, el router necesita **NAT loopback**
  (hairpinning). La mayoría lo admiten; si `https://<tu-dominio>` no carga desde dentro de casa pero sí desde los
  datos móviles del teléfono, es por esto.

## 3 · DNS: un dominio con comodín

Necesitas un dominio que resuelva al servidor, con un registro **comodín** para que cada app tenga su propio
subdominio automáticamente (`tienda.ejemplo.org`, `blog.ejemplo.org`…) sin volver a tocar el DNS.

- **Tu propio dominio** (recomendado si vas a mantener este servidor): en tu proveedor de DNS, añade un registro
  `A` `*.ejemplo.org` apuntando a la IP pública del servidor. Un solo registro cubre cualquier subdominio futuro.
- **Opción gratuita**: [DuckDNS](https://www.duckdns.org) te da `tunombre.duckdns.org`, donde también resuelve
  cualquier subdominio (`*.tunombre.duckdns.org`), y un pequeño cliente que mantiene la IP al día si cambia
  (útil en casa). Cualquier DNS dinámico con comodín funciona igual.

Espera a que se propague (de minutos a un par de horas) y compruébalo:
```bash
dig +short cualquiercosa.ejemplo.org
```
Debe imprimir la IP **pública** del servidor.

## 4 · Endurece el servidor antes de nada

Hazlo antes de instalar Coolify, en una sesión ssh en el servidor.

**SSH solo con clave.** Primero, desde tu ordenador, copia tu clave y comprueba que entras sin contraseña:
```bash
ssh-copy-id usuario@servidor
ssh usuario@servidor          # no debe pedir la contraseña de la cuenta
```
Después, en el servidor, desactiva la entrada con contraseña con un fichero propio (en muchas imágenes de VPS un
fichero de `/etc/ssh/sshd_config.d/` pone `PasswordAuthentication yes`, y sshd se queda con el primer valor que
lee, así que editar solo `sshd_config` no basta; el prefijo `00-` hace que gane este fichero):
```bash
echo "PasswordAuthentication no" | sudo tee /etc/ssh/sshd_config.d/00-key-only.conf
sudo systemctl restart ssh
```
No cierres esa sesión hasta comprobar desde **otra** terminal que sigues pudiendo entrar.

**Cortafuegos.** Importante: **Docker se salta `ufw`.** Los puertos que publican los contenedores —el panel de
Coolify (8000) y sus puertos de tiempo real (6001, 6002)— siguen accesibles desde Internet aunque `ufw` diga que
están cerrados. Por eso:
- **VPS:** usa el **cortafuegos del proveedor** (filtra antes de que el tráfico llegue a la máquina) y permite
  solo la entrada a **22, 80 y 443**. Puedes activar además `ufw` como capa extra para servicios que no sean de
  Docker.
- **Servidor en casa:** el router ya bloquea todo menos los puertos que reenvías (80 y 443). `ufw` es opcional.

**Actualizaciones de seguridad automáticas:**
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

## 5 · Instala Coolify

Coolify se instala con un único script oficial, que también instala Docker si falta:
```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```
Tarda unos minutos y al final imprime una URL como `http://<ip-del-servidor>:8000`.

**Crea la cuenta de administrador enseguida**: quien abra primero el panel puede registrarla. Ábrelo:
- **Servidor en casa:** desde tu red, `http://<ip-local-del-servidor>:8000`.
- **VPS:** el panel está (y debe seguir) cerrado por el cortafuegos del proveedor, así que ábrelo por un túnel ssh:
  ```bash
  ssh -L 8000:localhost:8000 -L 6001:localhost:6001 -L 6002:localhost:6002 usuario@servidor
  ```
  y entra en `http://localhost:8000` mientras esa sesión siga abierta (6001/6002 llevan los logs en directo y la
  terminal).

En la configuración inicial, elige desplegar en **esta máquina** (`localhost`). **No** le pongas un dominio
público al propio panel en los ajustes de Coolify, salvo que quieras el panel entero accesible desde Internet.

## 6 · Proxy y HTTPS

Coolify tiene un proxy inverso (Traefik) que pide y renueva certificados de Let's Encrypt automáticamente para el
dominio de cada app, siempre que los puertos 80 y 443 lleguen al servidor y el DNS resuelva (pasos 2–3). Nunca
configuras certificados a mano.

Fallo conocido: si una petición de certificado falló porque los puertos aún no estaban abiertos, puede que
Traefik no reintente solo. Reinícialo (en el servidor):
```bash
docker restart coolify-proxy
```

## 7 · Conecta GitHub

Coolify despliega desde GitHub mediante una **GitHub App** —limitada a los repositorios que elijas— y vuelve a
desplegar en cada push gracias a sus **webhooks**. GitHub tiene que poder llegar a una URL de tu servidor, pero el
panel debe seguir privado, así que publicamos **solo la ruta de los webhooks** en un subdominio propio, `hooks`.

1. **Expón solo el webhook.** En Coolify: *Servers → localhost → Proxy → Dynamic Configurations → Add*, llámalo
   `github-webhooks.yaml` y pega (cambia `ejemplo.org` por tu dominio):
   ```yaml
   http:
     routers:
       github-webhooks:
         entryPoints: [https]
         rule: "Host(`hooks.ejemplo.org`) && Path(`/webhooks/source/github/events`) && Method(`POST`)"
         service: github-webhooks
         tls:
           certResolver: letsencrypt
     services:
       github-webhooks:
         loadBalancer:
           servers:
             - url: "http://coolify:8080"
   ```
   Cualquier otra ruta de `hooks.ejemplo.org` devuelve una página de error: el panel no queda expuesto.
   Compruébalo desde fuera con `curl -I https://hooks.ejemplo.org/` (**no** debe salir la página de login de
   Coolify).
2. **Crea la GitHub App.** *Sources → Add → GitHub App*, sigue el enlace a GitHub y deja que cree la app; Coolify
   recibe las credenciales solo. Instálala en tu cuenta eligiendo **solo los repositorios** que vayas a desplegar
   (puedes añadir más después).
3. **Apunta los webhooks a la URL pública.** En GitHub: *Settings → Developer settings → GitHub Apps → tu app →
   Webhook URL* = `https://hooks.ejemplo.org/webhooks/source/github/events`. Guarda.

Desde ahora, `hooks` es un subdominio reservado: nunca despliegues una app en él (el paso 9 se lo dice al plugin).

## 8 · Activa la API

El plugin habla con Coolify solo por su API, que se sirve en el **mismo puerto que el panel**.

1. *Settings → Advanced* (`/settings/advanced`), apartado *API*: activa **API access** y pon en **Allowed IPs**
   la red desde la que llama Claude Code, p. ej. tu red de casa `192.168.1.0/24`, o el rango de tu VPN (VPS, ver
   abajo). Pulsa **Save**.
2. *Keys & Tokens → API Tokens* (`/security/api-tokens`): crea un token con **`read`, `write`, `deploy` y
   `delete`**. `delete` es aparte de `write` (sin él, cada borrado da 403), y los permisos no se pueden cambiar
   después: si te olvidas uno, crea otro token.
3. Copia el token (solo se muestra una vez) y guárdalo **sin pegarlo en el chat ni en el historial del shell**:
   - **macOS** (Llavero), justo después de copiarlo:
     ```bash
     security add-generic-password -U -a "$USER" -s coolify-api-token -w "$(pbpaste)" && pbcopy < /dev/null
     ```
   - **Linux y otros**: crea el fichero con tu editor, pega el token y guarda:
     ```bash
     mkdir -p ~/.config/coolify-ops && chmod 700 ~/.config/coolify-ops
     nano ~/.config/coolify-ops/token && chmod 600 ~/.config/coolify-ops/token
     ```

**VPS: cómo llega Claude Code a la API.** Con el panel cerrado por el cortafuegos, tu ordenador tampoco llega al
puerto 8000. La opción más sencilla y segura es una red privada entre tu ordenador y el servidor, como
[Tailscale](https://tailscale.com) o WireGuard: instálala en los dos y usa la dirección del servidor en la VPN
(`http://100.x.y.z:8000`) como URL de Coolify y el rango de la VPN en *Allowed IPs*. No se recomienda abrir el
puerto 8000 a todo Internet. (En un servidor en casa en la misma red que tu ordenador, no hay que hacer nada.)

## 9 · Conecta el plugin y despliega la app de ejemplo

En Claude Code:
```
Configura coolify-ops: mi Coolify está en http://<dirección-del-servidor>:8000, mi dominio base es ejemplo.org,
entro al servidor por ssh como usuario@servidor, reserva el subdominio hooks, y los proyectos nuevos van en ~/Projects.
```
Esto ejecuta `coolify.py init`, que comprueba el token, descubre tu servidor y tu GitHub App y guarda
`~/.config/coolify-ops/config.json` (fuera de cualquier repositorio). El acceso ssh es opcional, pero permite al
plugin vigilar la salud del servidor y limpiar a fondo cuando borras una app.

Después prueba la app de ejemplo que viene en este repositorio. Coolify despliega desde un repositorio de GitHub,
así que primero cópiala a su propia carpeta (el plugin le creará un repo privado y te dará el comando para
subirla):
```bash
cp -r examples/hello-fastapi ~/Projects/hello-fastapi
```
```
Despliega ~/Projects/hello-fastapi
```
El plugin la analiza, le escribe un Dockerfile, la construye y la prueba en local con Docker, te enseña un solo
resumen para confirmar y, tras tu «sí», crea la app con dominio HTTPS y despliegue automático en cada push. Cuando
ya no la necesites: `/coolify-ops:deploy-app decommission hello-fastapi`.

## 10 · Copias de seguridad y mantenimiento

- **Los datos del propio Coolify** (ajustes, apps, secretos cifrados): *Settings → Backup* (`/settings/backup`);
  activa las copias programadas, a ser posible en un almacenamiento compatible con S3 fuera del servidor.
- **Las bases de datos de tus apps** (p. ej. las de PostgreSQL que crea este plugin): cada base de datos tiene su
  pestaña *Backups* con programación y destinos S3.
- **Actualizaciones:** `unattended-upgrades` cubre los parches de seguridad; haz `sudo apt upgrade` de vez en
  cuando. Coolify se actualiza desde su panel (*Settings → Updates*, `/settings/updates`, donde también puedes
  activar la actualización automática).
- **Espacio en disco:** las imágenes de Docker se acumulan con cada despliegue. Coolify las limpia solo: revisa la
  frecuencia y el umbral de disco en *Servers → localhost → Docker Cleanup*; conserva unas pocas imágenes
  recientes por app para poder hacer rollback.

## 11 · Problemas frecuentes

Ver [problemas frecuentes](../../plugins/coolify-ops/skills/deploy-app/reference/troubleshooting.md) (en inglés)
con lo encontrado desplegando apps reales: dirección de escucha equivocada, health checks en imágenes mínimas,
versiones antiguas de Node/Angular, rutas de SPA, variables de compilación frente a ejecución, certificados,
webhooks, permisos de la API y restos tras borrar una app.
