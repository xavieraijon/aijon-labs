"""Minimal FastAPI app to try coolify-ops end to end: a page, a JSON endpoint and a health check."""

import os
import platform
import socket
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="hello-fastapi")
STARTED = datetime.now(timezone.utc)
GREETING = os.getenv("GREETING", "Hello from Coolify")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>hello-fastapi</title>
<style>body{{font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem;line-height:1.5}}
code{{background:#f2f2f2;padding:.1rem .3rem;border-radius:.2rem}}</style></head><body>
<h1>{GREETING} 👋</h1>
<p>This app was deployed with <a href="https://github.com/xavieraijon/aijon-labs">coolify-ops</a>.</p>
<p>Container <code>{socket.gethostname()}</code> · {platform.machine()} · Python {platform.python_version()}
· up since {STARTED:%Y-%m-%d %H:%M} UTC</p>
<p>Try <a href="/api/info"><code>/api/info</code></a> or <a href="/health"><code>/health</code></a>.</p>
</body></html>"""


@app.get("/api/info")
def info() -> dict:
    return {"greeting": GREETING, "host": socket.gethostname(), "arch": platform.machine(),
            "python": platform.python_version(), "started": STARTED.isoformat()}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
