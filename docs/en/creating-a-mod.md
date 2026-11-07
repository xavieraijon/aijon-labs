# Creating a mod

A *mod* changes Claude Code's own interface or behaviour: status line, panels, notices, slash commands… Some
things cannot be done from a plugin (for example, setting the main `statusLine`): those are documented with their
script and the instructions to enable them in `~/.claude/settings.json`.

1. Create `plugins/<plugin>/` with its `plugin.json` if the mod can be packaged (hooks, commands, agents).
2. If it needs `settings.json` changes, put them in the plugin README as a JSON snippet to copy; never apply them
   from an install script.
3. Same rules as everything else (see [conventions](conventions.md)): nothing personal, tests and CHANGELOG.

In Claude Code, the `plugin-authoring` skill helps design them.
