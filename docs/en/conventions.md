# Conventions

- **Language:** code, commands, JSON keys, script messages, commits and `CHANGELOG.md` in English. User documentation in English and
  Spanish (`docs/en/` and `docs/es/`, `README.md` and `README.es.md`). Skills answer in the user's language.
- **One plugin per topic** (`plugins/<name>/`). A plugin may hold several related skills and hooks.
- **Names** in `kebab-case`. The reserved prefixes `claude-`, `anthropic-` and `cc-plugin-` are not allowed for
  plugins. Avoid names that look official for a third-party product (e.g. plain `coolify`).
- **Semantic versions** in `plugin.json`; every published change bumps the version and is noted in `CHANGELOG.md`.
- **Scripts** in Python using only the standard library (nothing to install), JSON output, a non-zero exit code on
  error, and a useful `--help`. They are run with `python3 -I` (no code is loaded from the current folder).
- **Nothing personal in the repo:** no IPs, domains, uuids, emails or secrets. Each user's data lives in
  `~/.config/<plugin>/` (or `${CLAUDE_PLUGIN_DATA}` when it never needs editing by hand).
- **Tests** with pytest in `plugins/<name>/tests/`, offline: APIs, ssh and Docker are mocked with `monkeypatch`.
- **Before publishing:** `ruff check .`, `pytest -q plugins` and `claude plugin validate . --strict`.
