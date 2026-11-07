# aijon-labs

Colección personal de **skills, hooks y mods para [Claude Code](https://code.claude.com)**, empaquetados como
plugins de un marketplace. Todo está en castellano.

| Plugin | Tipo | Qué hace |
|---|---|---|
| [`coolify-ops`](plugins/coolify-ops/) | skills | Instala Coolify y despliega tus proyectos en tu servidor [Coolify](https://coolify.io) por su API: Dockerfile, prueba local, dominio HTTPS, PostgreSQL y despliegue en cada push |

## Instalación

Desde Claude Code:

```
/plugin marketplace add xavieraijon/aijon-labs
/plugin install coolify-ops@aijon-labs
```

Para probar cambios sin publicarlos, añade el marketplace desde la carpeta local:

```
/plugin marketplace add ~/aijon-labs
```

Cada plugin tiene su propio README con los requisitos y la configuración.

## Estructura

```
.claude-plugin/marketplace.json   catálogo de plugins del repo
plugins/<plugin>/
  .claude-plugin/plugin.json      manifiesto del plugin (nombre, versión, autor)
  skills/<skill>/SKILL.md         instrucciones de la skill (+ scripts/, templates/, reference/)
  hooks/hooks.json                hooks (si los tiene)
  tests/                          tests de pytest
  README.md
docs/                             convenciones y guías para crear nuevas piezas
```

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install pytest ruff
.venv/bin/ruff check .
.venv/bin/python -m pytest -q plugins
claude plugin validate . --strict
```

La CI de GitHub ejecuta lo mismo en cada push.

- [Convenciones](docs/convenciones.md)
- [Crear una skill](docs/crear-skill.md) · [Crear un hook](docs/crear-hook.md) · [Crear un mod](docs/crear-mod.md)
- [Seguridad](docs/seguridad.md)

## Licencia

[MIT](LICENSE)
