# Contributing

*[En castellano](docs/es/contribuir.md)*

Thanks for your interest! Issues and pull requests are welcome — bug reports from real servers are especially
useful, since every Coolify setup is a little different.

## Before you start

- For a bug, open an issue with the template: the Coolify version, your OS/architecture, the command or request,
  and the JSON output (**redact IPs, domains, tokens and uuids**).
- For a new feature or a new plugin, open an issue first so we can agree on the approach.
- Security problems go through [SECURITY.md](SECURITY.md), not public issues.

## Development

```bash
git clone https://github.com/xavieraijon/aijon-labs && cd aijon-labs
python3 -m venv .venv && .venv/bin/pip install pytest ruff
.venv/bin/ruff check .
.venv/bin/python -m pytest -q plugins
claude plugin validate . --strict
```
Try your changes in Claude Code with `/plugin marketplace add ./` from the clone, `/plugin install
coolify-ops@aijon-labs` and `/reload-plugins` after each edit.

## Rules

Read the [conventions](docs/en/conventions.md) first. In short:

- Python standard library only, JSON output, tests without network (mock APIs, ssh and Docker).
- Nothing personal in the repo: use `example.org`, `203.0.113.x` (documentation IPs) and `user@server` in
  examples and tests.
- Keep the safety rules in [SECURITY.md](SECURITY.md) intact; changes that relax them need a strong reason.
- Code and messages in English; user docs in English and Spanish (if you only write one, say so in the PR and it
  will be translated).
- [Conventional commits](https://www.conventionalcommits.org) (`feat:`, `fix:`, `docs:`…) and a `CHANGELOG.md` (in English)
  entry for user-visible changes.

Guides: [creating a skill](docs/en/creating-a-skill.md) · [a hook](docs/en/creating-a-hook.md) ·
[a mod](docs/en/creating-a-mod.md).
