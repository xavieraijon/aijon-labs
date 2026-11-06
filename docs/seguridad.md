# Seguridad

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

¿Has encontrado un problema de seguridad? Abre un issue sin detalles sensibles o escribe al autor por GitHub.
