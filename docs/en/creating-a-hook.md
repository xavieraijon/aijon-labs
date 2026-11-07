# Creating a hook

Hooks run a command when a Claude Code event happens (before or after a tool call, when a turn ends, when a
message is sent…). Claude Code runs them, not the model: they are for rules that must always hold.

1. Create `plugins/<plugin>/hooks/hooks.json`:
   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Bash",
           "hooks": [{ "type": "command", "command": "python3 -I ${CLAUDE_PLUGIN_ROOT}/hooks/my_hook.py" }]
         }
       ]
     }
   }
   ```
2. The script receives the event as JSON on stdin. To block an action in `PreToolUse`, exit with code 2 and
   explain why on stderr (Claude will see it).
3. Use `${CLAUDE_PLUGIN_ROOT}` for the plugin's paths and `${CLAUDE_PLUGIN_DATA}` to keep state.
4. Keep the hook fast (it runs on every event) and make it tolerate unexpected input.
5. Tests with sample events in `tests/`.

Reference: <https://code.claude.com/docs/en/hooks>
