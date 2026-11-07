# Coolify desde cero

Guía paso a paso para tener tu propio servidor [Coolify](https://coolify.io) —una alternativa autoalojada a
Heroku/Vercel— y poder usar después el plugin `coolify-ops` para desplegar tus proyectos en él. No necesitas
saber Docker ni administración de servidores de antemano; cada comando va completo.

Una vez funcionando, la skill `provision-server` de este plugin puede comprobar buena parte de los pasos
siguientes por ti (diagnóstico de solo lectura, DNS, puertos abiertos, salud de Coolify) y acompañarte en los que
necesitan tu contraseña de `sudo` o el navegador, que nunca hace por ti. Esta guía también sirve igual de bien a
mano, sin esa skill.

## 1 · Qué necesitas

- Una máquina que esté siempre encendida: un **VPS** (unos pocos euros al mes) o un **ordenador en casa** (una
  Raspberry Pi 4/5, un portátil viejo, un mini-PC). 2 GB de RAM son un mínimo cómodo para el propio Coolify, más
  lo que pidan tus apps; con 4 GB vas más holgado si vas a compilar apps de Node o Angular en ella.
- Cualquier CPU de 64 bits: x86_64 o ARM64 valen (Coolify y las plantillas Docker de este toolkit admiten ambas).
- Debian o Ubuntu (otras distribuciones de Linux también suelen valer; esta guía asume una de estas dos).
- Un dominio que controles, aunque sea gratuito (ver el paso 3). **No** necesitas una IP fija en la propia
  máquina si usas un servicio de DNS dinámico, solo un dominio que siempre apunte a ella.
- Acceso por `ssh` a la máquina con un usuario que pueda usar `sudo`.

## 2 · Elige dónde va a vivir

| | VPS | Servidor en casa |
|---|---|---|
| IP pública | Fija, la da el proveedor | Suele cambiar; hace falta DNS dinámico |
| Puesta en marcha | Más rápida: los puertos están abiertos por defecto | Abres puertos en tu router |
| Coste | Cuota mensual | Solo la luz, hardware que ya puedes tener |
| Fiabilidad | La del proveedor | Depende de tu luz e internet |

**En un VPS**, cualquier proveedor que te dé acceso SSH como root a una máquina Debian/Ubuntu recién creada vale.
Apunta su IP pública; a ella harás apuntar tu dominio.

**En casa**, dos cosas importan antes de nada:
- **Comprueba que no estás detrás de CGNAT.** Algunos operadores no te dan una IP pública real, aunque el router
  muestre una. Desde el servidor, ejecuta `curl -4 ifconfig.me` y compáralo con lo que muestra la página WAN de
  tu router. Si son distintas, estás detrás de CGNAT y no puedes reenviar puertos sin pedir una IP pública a tu
  operador (a veces gratis si la pides) o usar un túnel (p. ej. Cloudflare Tunnel, fuera del alcance de esta
  guía).
- **Dale al servidor una dirección fija en tu red local** (una reserva DHCP en el router, o una IP estática en la
  máquina) para que el reenvío de puertos siga funcionando después de un reinicio.
- **Reenvía los puertos 80 y 443** en tu router hacia esa dirección local. Son los únicos puertos que deben ser
  públicos; el panel de Coolify (puerto 8000) debe quedar privado (ver el paso 5).
- Si quieres entrar al panel desde dentro de tu propia red usando el nombre de dominio público, tu router
  necesita **NAT loopback / hairpinning**. La mayoría de routers domésticos lo admiten; si una petición a
  `https://tu-dominio` desde dentro de la LAN no llega al servidor, suele ser por esto —navegar por la IP local
  lo evita mientras tanto—.

## 3 · DNS: un dominio con comodín

Necesitas un dominio que resuelva al servidor, con un registro **comodín** para que cada app tenga su propio
subdominio automáticamente (`tienda.ejemplo.org`, `blog.ejemplo.org`, …) sin volver a tocar el DNS.

- **Tu propio dominio** (recomendado si piensas mantener este servidor): en tu proveedor de dominios, añade un
  registro `A` `*.ejemplo.org` apuntando a la IP pública del servidor. Un solo registro cubre cualquier
  subdominio futuro.
- **Opción gratuita**: [DuckDNS](https://www.duckdns.org) te da `tunombre.duckdns.org` gratis, con comodín
  incluido (`*.tunombre.duckdns.org`) y un pequeño cliente que mantiene la IP actualizada si cambia (útil en
  casa). Cualquier servicio de DNS dinámico parecido con comodín funciona igual.

Espera a que el cambio de DNS se propague (de minutos a un par de horas) y compruébalo con:
```bash
dig +short cualquiercosa.ejemplo.org
```
Debería imprimir la IP pública del servidor.

## 4 · Endurece el servidor antes de nada

Hazlo antes de instalar cualquier otra cosa: lleva pocos minutos y evita la forma más habitual en que estas
máquinas se ven comprometidas.

```bash
# Crea un usuario que no sea root si solo tienes root, y como ese usuario:
sudo apt update && sudo apt upgrade -y

# SSH: solo entrada con clave
ssh-copy-id usuario@servidor                 # desde tu propia máquina, si no lo has hecho ya
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh

# Cortafuegos: solo SSH, HTTP y HTTPS desde fuera
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable

# Actualizaciones de seguridad automáticas
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```
Mantén el puerto del panel de Coolify (8000) **cerrado** hacia fuera: la regla 80/443 de arriba no lo abre.
Llegarás al panel por túnel SSH o VPN hasta que decidas lo contrario (ver el paso 5).

## 5 · Instala Coolify

Coolify se instala con un único script oficial, que instala Docker si falta:
```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```
Tarda unos minutos. Al final imprime una URL como `http://<ip-del-servidor>:8000`.

- **Primer arranque**: abre esa URL —desde dentro de tu red, o por un túnel SSH si ya endureciste el cortafuegos
  (`ssh -L 8000:localhost:8000 usuario@servidor`, y luego abre `http://localhost:8000` en tu propia máquina)—.
  Crea la cuenta de administrador en esta primera visita; quien llegue a esa URL antes que tú puede crearla en tu
  lugar, así que hazlo justo después de instalar.
- Mantén el panel accesible solo desde tu red local, una VPN o un túnel SSH —no desde internet público—, salvo
  que quieras gestionar Coolify explícitamente desde fuera y te sientas cómodo abriendo el puerto 8000 (o
  pasándolo por el 443 con su propia autenticación delante).
- En los ajustes de Coolify, pon su propio dominio o IP si piensas usar un nombre para el propio panel (opcional;
  las apps que despliega tienen sus propios dominios en cualquier caso).

## 6 · Proxy y HTTPS

Coolify tiene su propio proxy inverso (Traefik) que pide y renueva certificados de Let's Encrypt
automáticamente para el dominio de cada app, siempre que los puertos 80 y 443 lleguen al servidor (paso 2/4) y el
DNS ya resuelva (paso 3). No configuras certificados a mano.

Fallo conocido: si abres los puertos 80/443 **después** de que un despliegue ya haya fallado al pedir el
certificado, a veces Traefik no reintenta solo. Reiniciar su contenedor lo empuja:
```bash
docker restart coolify-proxy
```
Ver [troubleshooting.md](../../plugins/coolify-ops/skills/deploy-app/reference/troubleshooting.md) para este y
otros problemas de certificados.

## 7 · Conecta GitHub (como GitHub App)

La skill `deploy-app` despliega desde repositorios de GitHub usando una **GitHub App**, no un token personal: se
limita a los repos que elijas, y Coolify la usa para clonar, leer commits y recibir webhooks de cada push.

1. En Coolify: *Sources → Add → GitHub App*. Coolify te prepara el manifiesto.
2. Sigue su enlace a GitHub, dale nombre a la app y deja que GitHub la cree; Coolify recibe las credenciales
   automáticamente.
3. Instala la app en tu cuenta u organización, eligiendo **o bien** todos los repositorios **o bien** solo los
   que vayas a desplegar (puedes añadir más después).
4. Un ajuste necesita una dirección pública incluso en un servidor en casa: en GitHub → *Settings → Developer
   settings → GitHub Apps → tu app → Webhook URL* debe ser la URL pública de tu servidor terminada en
   `/webhooks/source/github/events` (p. ej. `https://coolify.ejemplo.org/webhooks/source/github/events`), nunca
   una IP privada. Es la única entrada desde GitHub; no expone nada más.

## 8 · Activa la API

Las skills de este plugin hablan con Coolify solo por su API, nunca por el navegador.

1. *Settings → Advanced → API access*: actívala.
2. En la misma pantalla, pon en **Allowed IPs** la red desde la que llamarás a la API (p. ej. tu red doméstica
   `192.168.1.0/24`, o tu propia IP si llamas desde fuera). No se recomienda dejarlo sin restringir.
3. *Security → API tokens → Create*: dale un nombre y los permisos `read`, `write`, `deploy` y **`delete`**
   (`delete` es un permiso aparte de `write`; sin él, cada borrado devuelve un 403). Los permisos no se pueden
   editar después de crear el token; si te olvidas uno, crea otro.
4. Copia el token ahora; Coolify lo muestra solo una vez. Guárdalo con una de estas opciones (nunca en un fichero
   dentro de este repo ni de ninguno que vayas a subir):
   - Llavero de macOS: `security add-generic-password -U -a "$USER" -s coolify-api-token -w "<pégalo aquí>"`
   - Cualquier sistema: guárdalo en `~/.config/coolify-ops/token` y hazle `chmod 600`.
   - O expórtalo como `COOLIFY_TOKEN` en tu perfil de shell.

## 9 · Conecta la skill y despliega la app de ejemplo

De vuelta en Claude Code, con el plugin `coolify-ops` instalado:
```
Configura coolify-ops: mi Coolify está en http://<ip-o-dominio-del-servidor>:8000, mi dominio base es
ejemplo.org, puedo entrar por ssh como usuario@servidor, y los proyectos nuevos van en ~/Projects.
```
Esto ejecuta `coolify.py init`, que descubre tu servidor y tu GitHub App por la API y guarda
`~/.config/coolify-ops/config.json` (fuera del repo; nunca se sube).

Luego prueba con el proyecto de ejemplo que viene en este repo:
```
Despliega examples/hello-fastapi
```
La skill lo analiza, lo construye y lo prueba en local con Docker, te muestra un solo resumen para confirmar y,
tras tu «sí», crea la app en Coolify con dominio HTTPS y despliegue automático en cada push.

## 10 · Copias de seguridad y mantenimiento

- **El propio Coolify** guarda su configuración en su base de datos interna, dentro de Docker; la interfaz de
  Coolify tiene copia de seguridad y restauración integradas (*Settings → Backup*). Activa ahí las copias
  programadas.
- **Las bases de datos de tus apps** (p. ej. las de PostgreSQL que crea este plugin): Coolify también puede
  programar copias por base de datos (*la base de datos → Backups*); apúntalas a un almacenamiento compatible
  con S3 si quieres tenerlas fuera del servidor.
- **Actualizaciones del sistema**: `sudo apt upgrade` con regularidad; Coolify se actualiza solo desde su propia
  interfaz (*Settings → Update*).
- **Espacio en disco**: las imágenes de Docker se acumulan con el tiempo; `docker system prune` recupera espacio
  de imágenes antiguas sin usar y de la caché de build (revisa antes qué borraría con `docker system df`).

## 11 · Problemas frecuentes

Ver [troubleshooting.md](../../plugins/coolify-ops/skills/deploy-app/reference/troubleshooting.md) para los
problemas encontrados desplegando apps reales: dirección de escucha equivocada, health checks en imágenes
mínimas, versiones antiguas de Node/Angular, rutas de SPA, variables de compilación frente a ejecución,
certificados, webhooks, permisos de la API y restos tras borrar una app.
