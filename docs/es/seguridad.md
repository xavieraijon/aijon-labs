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
- **Las acciones irreversibles preguntan siempre** (borrar, rollback, force push), aunque el resto del flujo sea
  automático. Una excepción declarada: una app Django desplegada con `deploy-app` aplica sus migraciones de base
  de datos en cada arranque, así que con auto-deploy cada push ejecuta las migraciones nuevas sin preguntar (el
  resumen del despliegue lo dice antes de la única confirmación). Una migración que borra una columna pierde esos
  datos, un rollback no la deshace y la skill todavía no hace copias de seguridad de la base de datos.
- **Publicar código lo hace el usuario.** Las skills nunca ejecutan `git push` ni crean repositorios con push.
- **Sin `sudo` ni contraseñas en los servidores.** `provision-server` solo ejecuta órdenes de lectura por ssh con
  clave y nunca acepta una clave de host desconocida en tu nombre.
- **Mínimo privilegio.** Tokens de la API con los permisos justos; `allowed-tools` limitado a los scripts de cada
  skill y a unas pocas órdenes de `gh` que solo leen de GitHub (git solo se usa a través de un script que no tiene push);
  los scripts se ejecutan con `python3 -I` y solo usan la biblioteca estándar de Python.
- **Privado por defecto.** Las bases de datos nunca se hacen públicas y nunca se abren puertos del router ni del
  cortafuegos.

## Versiones con soporte

Solo la última versión publicada de cada plugin recibe correcciones.
