# Crear un hook

Los hooks ejecutan una orden cuando ocurre un evento de Claude Code (antes o después de usar una herramienta, al
terminar, al enviar un mensaje…). Los ejecuta Claude Code, no el modelo: sirven para reglas que se deben cumplir
siempre.

1. Crea `plugins/<plugin>/hooks/hooks.json`:
   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Bash",
           "hooks": [{ "type": "command", "command": "python3 -I ${CLAUDE_PLUGIN_ROOT}/hooks/mi_hook.py" }]
         }
       ]
     }
   }
   ```
2. El script recibe el evento en JSON por la entrada estándar. Para bloquear una acción en `PreToolUse`, sale con
   código 2 y explica el motivo por la salida de error (Claude lo verá).
3. Usa `${CLAUDE_PLUGIN_ROOT}` para las rutas del plugin y `${CLAUDE_PLUGIN_DATA}` para guardar estado.
4. Haz el hook rápido (se ejecuta en cada evento) y que no falle si le llega algo inesperado.
5. Tests con eventos de ejemplo en `tests/`.

Referencia: <https://code.claude.com/docs/en/hooks>
