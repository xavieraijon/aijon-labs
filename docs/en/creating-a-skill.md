# Creating a skill

1. Pick or create the plugin: `plugins/<plugin>/.claude-plugin/plugin.json` (`name`, `version`, `description`,
   `author`). If it is new, add it to `.claude-plugin/marketplace.json`.
2. Create `plugins/<plugin>/skills/<skill>/SKILL.md`:
   ```markdown
   ---
   name: my-skill
   description: What it does and WHEN to use it (Claude decides from this sentence whether to load it).
   argument-hint: "[arguments]"
   allowed-tools: Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)
   ---
   # Step-by-step instructions for Claude
   ```
   `${CLAUDE_SKILL_DIR}` is replaced with the skill's folder (in the text and in `allowed-tools`); it is **not** a
   shell environment variable.
3. Put deterministic logic in `scripts/` and keep judgement in `SKILL.md`: when to stop, what to ask, which rules
   are never skipped.
4. Long reference material goes in `reference/` (Claude reads it only when needed).
5. Tests in `plugins/<plugin>/tests/`, the plugin README and an entry in `CHANGELOG.md`.
6. Try it locally: `/plugin marketplace add ./aijon-labs` (path to your clone) and
   `/plugin install <plugin>@aijon-labs`; after edits, `/reload-plugins`.
