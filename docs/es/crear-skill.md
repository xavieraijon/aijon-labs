# Crear una skill

1. Elige o crea el plugin: `plugins/<plugin>/.claude-plugin/plugin.json` (`name`, `version`, `description`, `author`).
   Si es nuevo, añádelo a `.claude-plugin/marketplace.json`.
2. Crea `plugins/<plugin>/skills/<skill>/SKILL.md`:
   ```markdown
   ---
   name: mi-skill
   description: Qué hace y CUÁNDO usarla (Claude decide por esta frase si la carga).
   argument-hint: "[argumentos]"
   allowed-tools: Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)
   ---
   # Instrucciones paso a paso para Claude
   ```
   `${CLAUDE_SKILL_DIR}` se sustituye por la carpeta de la skill (en el texto y en `allowed-tools`); **no** es una
   variable de entorno del shell.
3. Pon la lógica determinista en `scripts/` y deja en `SKILL.md` el criterio: cuándo parar, qué preguntar, qué reglas
   no se saltan nunca.
4. Material de consulta largo en `reference/` (Claude lo lee solo cuando lo necesita).
5. Tests en `plugins/<plugin>/tests/`, README del plugin y entrada en `CHANGELOG.md`.
6. Prueba en local: `/plugin marketplace add ./aijon-labs` (ruta a tu copia) y
   `/plugin install <plugin>@aijon-labs`; tras cada cambio, `/reload-plugins`.
