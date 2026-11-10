<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/aijonlabs-logo-dark.svg">
    <img alt="aijon-labs" src="assets/brand/aijonlabs-logo-light.svg" width="420">
  </picture>
</p>

<p align="center"><em>Claude Code plugins, built and maintained by Xavi Aijon.</em></p>

*[Leer en castellano](README.es.md)*

[![CI](https://github.com/xavieraijon/aijon-labs/actions/workflows/ci.yml/badge.svg)](https://github.com/xavieraijon/aijon-labs/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Claude Code](https://code.claude.com) plugin marketplace. Today it has one plugin, `coolify-ops`, for
self-hosted deployments; more plugins (skills, hooks and interface mods) are planned, and each installs on its
own.

## Install

In Claude Code, add the marketplace once, then install the plugins you want, for example:
```
/plugin marketplace add xavieraijon/aijon-labs
/plugin install coolify-ops@aijon-labs
```
Then run `/reload-plugins` (or restart Claude Code): typing `/coolify-ops:` now lists its skills, and they also
trigger when you ask in your own words. To update later: `/plugin marketplace update aijon-labs` refreshes the
catalogue, `/plugin update coolify-ops@aijon-labs` installs the new version (restart to apply).

## Plugins

| Plugin | What it does | You need | Get started |
|---|---|---|---|
| [`coolify-ops`](plugins/coolify-ops/) | Run your own [Coolify](https://coolify.io) server (a self-hosted Heroku/Vercel) from Claude Code: set it up on a VPS or a home server, then deploy your projects to it — it writes the Dockerfile if missing (FastAPI, Django, Laravel, Next.js, Nuxt, SPAs and more) — with an HTTPS domain, optional PostgreSQL with backups and auto-deploy on every push, all through the Coolify API | A VPS or home server, a domain, GitHub (`gh` signed in), and Docker and Python 3.10+ on your computer ([details](plugins/coolify-ops/README.md#requirements)) | [README](plugins/coolify-ops/) · tutorial [Coolify from scratch](docs/en/coolify-from-scratch.md) · [example app](examples/hello-fastapi/) (once the server is set up) |

Versions and changes: [CHANGELOG](CHANGELOG.md) and [releases](https://github.com/xavieraijon/aijon-labs/releases)
(tagged `<plugin>-v<version>`).

## How the plugins behave

Every plugin here follows the same rules:
- Anything irreversible or outward-facing (deleting, restoring, publishing) asks first.
- `git push` and anything that publishes are yours: the plugins prepare the commit and give you the command.
- Tokens and passwords never go through the chat and are masked in all output.
- Nothing personal lives in this repository; your settings stay in your own config folder.
- Scripts use only the Python standard library and are tested offline.

Each plugin's README lists its own guarantees. Details, and how to report a vulnerability, in
[SECURITY.md](SECURITY.md).

## Repository layout

```
.claude-plugin/marketplace.json   the marketplace catalogue
plugins/<plugin>/
  .claude-plugin/plugin.json      plugin manifest (name, version, author)
  skills/<skill>/SKILL.md         skill instructions (+ scripts/, templates/, reference/)
  tests/                          pytest tests (offline)
  README.md
examples/                         sample apps to try the plugins
docs/en/, docs/es/                tutorials and contributor guides
```

## Contributing

Bug reports from real servers are very welcome. See [CONTRIBUTING.md](CONTRIBUTING.md), the
[conventions](docs/en/conventions.md) and the guides for [skills](docs/en/creating-a-skill.md),
[hooks](docs/en/creating-a-hook.md) and [mods](docs/en/creating-a-mod.md).

```bash
python3 -m venv .venv && .venv/bin/pip install pytest ruff
.venv/bin/ruff check . && .venv/bin/python -m pytest -q plugins && claude plugin validate . --strict
```

## License

[MIT](LICENSE). Not affiliated with Coolify or Anthropic.
