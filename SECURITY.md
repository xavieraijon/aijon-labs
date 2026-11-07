# Security

*[En castellano](docs/es/seguridad.md)*

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private reporting instead:
*Security → Report a vulnerability* on this repository. You will get an answer as soon as possible; please allow
a reasonable time for a fix before disclosing it.

Include what is affected (plugin, skill, script), how to reproduce it and the impact you see. Never include real
tokens, passwords or personal data in the report — redact them.

## What these plugins promise

The skills act on your servers, so they follow a few rules by design. A bug that breaks one of them is a security
issue worth reporting:

- **No secrets in the chat or in output.** API tokens are read from the macOS Keychain, a `chmod 600` file or an
  environment variable; passwords and connection strings are masked; variable values are never printed.
- **Nothing personal in the repository.** Each user's IPs, domains, uuids and secrets live in
  `~/.config/<plugin>/`, never in the repo.
- **Irreversible actions always ask** (delete, rollback, force push), even inside an otherwise automatic flow.
- **Publishing code is done by the user.** The skills never run `git push` or create repositories with a push.
- **No sudo, no passwords on servers.** `provision-server` only runs read-only commands over ssh with key
  authentication and never accepts an unknown host key on your behalf.
- **Least privilege.** API tokens with only the permissions needed; `allowed-tools` limited to each skill's own
  scripts; scripts run with `python3 -I` and use only the Python standard library.
- **Private by default.** Databases are never made public and router or firewall ports are never opened.

## Supported versions

Only the latest released version of each plugin receives fixes.
