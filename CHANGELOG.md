# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Cada plugin tiene su propia versión.

## coolify-deploy

### 0.1.0 — 2026-11-06
- Primera versión de la skill `desplegar-coolify`: análisis del proyecto, Dockerfile desde plantillas
  (FastAPI, Flask, Node, Next.js, SPA con nginx, estática, PHP), prueba local con Docker, despliegue por la API
  de Coolify con HTTPS, PostgreSQL privado opcional, variables desde fichero, verificación (certificado, rutas,
  acceso desde fuera, salud del servidor) y modos `estado`, `logs`, `actualizar`, `variables`, `rollback`, `retirar`.
