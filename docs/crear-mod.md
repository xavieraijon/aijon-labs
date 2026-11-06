# Crear un mod

Un *mod* cambia la propia interfaz o el comportamiento de Claude Code: línea de estado, paneles, avisos, órdenes con
barra… Algunas cosas no se pueden hacer desde un plugin (por ejemplo, fijar la `statusLine` principal): esas se
documentan aquí con su script y las instrucciones para activarlas en `~/.claude/settings.json`.

1. Crea `plugins/<plugin>/` con su `plugin.json` si el mod se puede empaquetar (hooks, órdenes, agentes).
2. Si necesita ajustes en `settings.json`, ponlos en el README del plugin como fragmento JSON para copiar, nunca los
   apliques desde un script de instalación.
3. Mismas reglas que el resto: castellano, nada personal, tests y CHANGELOG.

En Claude Code, la skill `plugin-authoring` ayuda a diseñarlos.
