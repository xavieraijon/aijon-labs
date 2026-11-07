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

A [Claude Code](https://code.claude.com) plugin marketplace: skills, hooks and mods for self-hosting and
everyday automation. Each plugin installs on its own.

| Plugin | What it does |
|---|---|
| [`coolify-ops`](plugins/coolify-ops/) | Run your own [Coolify](https://coolify.io) server (a self-hosted Heroku/Vercel) from Claude Code: set it up on a VPS or a home server, then deploy your projects with a Dockerfile, HTTPS domain, optional PostgreSQL and auto-deploy on every push — all through the Coolify API |

## Quick start

In Claude Code:
```
/plugin marketplace add xavieraijon/aijon-labs
/plugin install coolify-ops@aijon-labs
```
Then just ask:
```
> set up Coolify on my VPS user@203.0.113.10 with the domain example.org
> deploy ~/Projects/my-shop
> /coolify-ops:deploy-app status
```

What a deployment looks like: Claude analyzes the project, writes a Dockerfile if it has none, builds and tests it
on your machine, and shows you **one summary**:
```
App:          my-shop  (fastapi, python-fastapi template)
Repo:         you/my-shop · branch main · 1 commit to push
Domain:       https://my-shop.example.org   (available ✔)
Database:     PostgreSQL 17 (new, private)
Resources:    max 1 CPU / 512m
Auto-deploy:  yes (every push publishes)
Local check:  OK (9 s build, routes / 200, /health 200)
```
After your «yes» it creates everything on Coolify, deploys, and verifies HTTPS from outside.

## New to Coolify?

Follow **[Coolify from scratch](docs/en/coolify-from-scratch.md)** — hardware, VPS vs. home server, DNS,
hardening, install, GitHub and the API — or let the `provision-server` skill walk you through it and check every
step. Then try the bundled [example app](examples/hello-fastapi/).

## Safety by design

- One confirmation per deployment; delete, rollback and force push always ask.
- `git push` is always yours: the skills prepare the commit and give you the command.
- Tokens and passwords never go through the chat and are masked in all output.
- No `sudo`, no passwords on servers, no unknown ssh host keys accepted.
- Databases stay private; ports are never opened for you.

More in [SECURITY.md](SECURITY.md).

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
