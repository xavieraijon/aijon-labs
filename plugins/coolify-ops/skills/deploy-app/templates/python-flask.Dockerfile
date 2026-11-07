# Template: Python + Flask (gunicorn). Variables: {{PYTHON_VERSION}} {{MODULE}} {{PORT}}
FROM python:{{PYTHON_VERSION}}-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && pip install gunicorn
COPY . .
RUN useradd --create-home --uid 10001 app
USER app
EXPOSE {{PORT}}
CMD ["gunicorn", "--bind", "0.0.0.0:{{PORT}}", "--workers", "2", "--forwarded-allow-ips", "*", "{{MODULE}}"]
