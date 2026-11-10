# Seguridad

*[In English](../../SECURITY.md)*

## Avisar de una vulnerabilidad

Por favor, **no abras un issue público** para un problema de seguridad. Usa el aviso privado de GitHub:
*Security → Report a vulnerability* en este repositorio. Te responderemos lo antes posible; deja un tiempo razonable
para corregirlo antes de hacerlo público.

Indica qué está afectado (plugin, skill, script), cómo reproducirlo y el impacto que ves. No incluyas nunca tokens,
contraseñas ni datos personales reales en el aviso: tápalos.

## Qué prometen estos plugins

Las skills actúan sobre tus servidores, así que siguen unas reglas por diseño. Un fallo que rompa alguna de ellas es
un problema de seguridad y merece un aviso:

- **Ningún secreto en el chat ni en la salida.** Los tokens de la API se leen del Llavero de macOS, de un fichero
  con `chmod 600` o de una variable de entorno; las contraseñas y las cadenas de conexión se enmascaran; los valores
  de las variables nunca se muestran.
- **Nada personal en el repositorio.** Las IPs, dominios, uuids y secretos de cada usuario viven en
  `~/.config/<plugin>/`, nunca en el repo.
- **Las acciones irreversibles preguntan siempre** (borrar, rollback, restaurar una copia de la base de datos,
  guardar menos copias, force push), aunque el resto del flujo sea automático. Una excepción declarada: una app Django o Laravel desplegada con `deploy-app` aplica sus
  migraciones de base de datos en cada arranque, así que con auto-deploy cada push ejecuta las migraciones nuevas sin preguntar (el
  resumen del despliegue lo dice antes de la única confirmación). Una migración que borra una columna pierde esos
  datos y un rollback no la deshace; la copia diaria de la base de datos (activada por defecto en las PostgreSQL
  que crea la skill) se puede restaurar, con su propia pregunta.
- **Publicar código lo hace el usuario.** Las skills nunca ejecutan `git push` ni crean repositorios con push.
- **Sin `sudo` ni contraseñas en los servidores.** `provision-server` solo ejecuta órdenes de lectura por ssh con
  clave y nunca acepta una clave de host desconocida en tu nombre. `deploy-app` usa el mismo acceso ssh para
  vigilar el servidor y, solo durante un decommission o una restauración de copia confirmados, para borrar las
  imágenes de la app o para vaciar y restaurar su base de datos dentro del contenedor de la base de datos (como el
  usuario de la base de datos, sin sudo).
- **Mínimo privilegio.** Tokens de la API con los permisos justos; `allowed-tools` limitado a los scripts de cada
  skill y a unas pocas órdenes de `gh` que solo leen de GitHub (git solo se usa a través de un script que no tiene push);
  los scripts se ejecutan con `python3 -I` y solo usan la biblioteca estándar de Python.
- **Privado por defecto.** Las bases de datos nunca se hacen públicas y nunca se abren puertos del router ni del
  cortafuegos. Las copias de la base de datos que descarga `deploy-app` van por defecto a
  `~/.config/coolify-ops/backups/` (carpeta 700); los ficheros siempre tienen modo 600 y nunca se escriben dentro de
  un repositorio git.

## Versiones con soporte

Solo la última versión publicada de cada plugin recibe correcciones.
