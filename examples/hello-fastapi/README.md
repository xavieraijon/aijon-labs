# hello-fastapi

A minimal [FastAPI](https://fastapi.tiangolo.com) app to try `coolify-ops` end to end: a home page, a JSON
endpoint (`/api/info`) and a health check (`/health`). It has **no Dockerfile on purpose** — the `deploy-app`
skill writes one from its `python-fastapi` template.

Coolify deploys from a GitHub repository, so copy it into its own folder first and let the skill create the repo:

```bash
d=$(mktemp -d) && git clone --depth 1 https://github.com/xavieraijon/aijon-labs "$d/aijon-labs" \
  && cp -r "$d/aijon-labs/examples/hello-fastapi" ~/Projects/hello-fastapi && rm -rf "$d"
```
Then, in Claude Code:
```
deploy ~/Projects/hello-fastapi
```
The optional `GREETING` variable changes the text on the home page (see `.env.example`).

---

*Una app mínima de FastAPI para probar `coolify-ops` de principio a fin. No trae Dockerfile a propósito: lo
escribe la skill `deploy-app`. Cópiala a su propia carpeta con las órdenes de arriba (`git clone` y `cp -r`)
y pide a Claude «despliega ~/Projects/hello-fastapi».*
