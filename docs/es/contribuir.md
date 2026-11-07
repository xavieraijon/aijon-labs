# Contribuir

*[In English](../../CONTRIBUTING.md)*

¡Gracias por el interés! Se agradecen issues y pull requests; los fallos encontrados en servidores reales son
especialmente útiles, porque cada instalación de Coolify es un poco distinta.

## Antes de empezar

- Para un fallo, abre un issue con la plantilla: versión de Coolify, sistema y arquitectura, la orden o petición,
  y la salida JSON (**tapa IPs, dominios, tokens y uuids**).
- Para una función nueva o un plugin nuevo, abre antes un issue para acordar el enfoque.
- Los problemas de seguridad van por [SECURITY.md](../../SECURITY.md), no por issues públicos.

## Desarrollo

```bash
git clone https://github.com/xavieraijon/aijon-labs && cd aijon-labs
python3 -m venv .venv && .venv/bin/pip install pytest ruff
.venv/bin/ruff check .
.venv/bin/python -m pytest -q plugins
claude plugin validate . --strict
```
Prueba los cambios en Claude Code con `/plugin marketplace add ./` desde la copia, `/plugin install
coolify-ops@aijon-labs` y `/reload-plugins` tras cada cambio.

## Reglas

Lee antes las [convenciones](convenciones.md). En resumen:

- Solo la biblioteca estándar de Python, salida JSON, tests sin red (simula APIs, ssh y Docker).
- Nada personal en el repo: usa `example.org`, `203.0.113.x` (IPs de documentación) y `user@server` en ejemplos
  y tests.
- Respeta las reglas de seguridad de [SECURITY.md](../../SECURITY.md); relajarlas necesita un buen motivo.
- Código y mensajes en inglés; documentación para usuarios en inglés y castellano (si solo escribes uno, dilo en
  el PR y se traducirá).
- [Commits convencionales](https://www.conventionalcommits.org) (`feat:`, `fix:`, `docs:`…) y entrada en
  `CHANGELOG.md` (en inglés) para los cambios visibles.

Guías: [crear una skill](crear-skill.md) · [un hook](crear-hook.md) · [un mod](crear-mod.md).
