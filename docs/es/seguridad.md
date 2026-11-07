# Seguridad

*[In English](../../SECURITY.md)*

Este repositorio es **público**. Reglas para todo lo que se añada:

- **Ningún dato personal ni secreto**: nada de IPs, dominios, uuids, correos, tokens ni contraseñas. Todo eso vive
  en la configuración local del usuario (`~/.config/<plugin>/`, Llavero de macOS).
- **Los secretos no pasan por el chat:** se leen del Llavero o de ficheros con `chmod 600`, y los scripts los
  enmascaran en su salida.
- **Las acciones irreversibles se confirman siempre** (borrar, rollback, force push), aunque el resto del flujo
  sea automático.
- **Lo que publica código lo ejecuta el usuario** (`git push`, crear repos): las skills preparan el comando.
- **Mínimo privilegio:** tokens con los permisos justos; `allowed-tools` limitado a los scripts de la skill.
- **Scripts con `python3 -I`** y sin dependencias externas.
- **Sin `sudo` ni contraseñas en los servidores:** `provision-server` solo ejecuta órdenes de lectura por ssh con
  clave y nunca acepta una clave de host desconocida por el usuario.
- **Privado por defecto:** las bases de datos nunca se hacen públicas y nunca se abren puertos del router ni del
  cortafuegos.

¿Has encontrado un problema de seguridad? **No abras un issue público**: sigue [SECURITY.md](../../SECURITY.md)
(aviso privado por GitHub).
