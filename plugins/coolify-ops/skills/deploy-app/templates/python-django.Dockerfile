# Template: Python + Django (gunicorn, whitenoise, migrations on start). Variables: {{PYTHON_VERSION}} {{UV_IMAGE}}
#   {{POETRY_SETUP}} {{DEPS_FILES}} {{INSTALL}} {{EXTRA_PACKAGES}} {{COLLECTSTATIC}} {{MODULE}} {{PORT}}
# Settings come from coolify_settings.py (generated next to manage.py), which loads the project's own.
FROM python:{{PYTHON_VERSION}}-slim AS build
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 POETRY_NO_INTERACTION=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv VIRTUAL_ENV=/opt/venv UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3
COPY --from={{UV_IMAGE}} /uv /bin/uv
WORKDIR /app
RUN python -m venv /opt/venv{{POETRY_SETUP}}
COPY {{DEPS_FILES}} ./
RUN {{INSTALL}}
RUN uv pip install --python /opt/venv/bin/python {{EXTRA_PACKAGES}}

FROM python:{{PYTHON_VERSION}}-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH DJANGO_SETTINGS_MODULE=coolify_settings
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY . .
{{COLLECTSTATIC}}
RUN useradd --create-home --uid 10001 app
USER app
EXPOSE {{PORT}}
# Coolify waits for this check before switching traffic and keeps the previous container if it fails.
# A TCP connect (no request, no log lines): the port only opens once migrations ran and the app imported.
HEALTHCHECK --interval=5s --timeout=5s --start-period=10s --retries=60 CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', {{PORT}}), 4)"]
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn --bind 0.0.0.0:{{PORT}} --workers 2 --preload --access-logfile - {{MODULE}}"]
