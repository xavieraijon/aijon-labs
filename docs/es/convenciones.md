# Convenciones

- **Idioma:** código, órdenes, claves JSON, mensajes de los scripts, commits y `CHANGELOG.md` en inglés. La documentación para usuarios, en
  inglés y castellano (`docs/en/` y `docs/es/`, `README.md` y `README.es.md`). Las skills responden en el idioma
  del usuario.
- **Un plugin por tema** (`plugins/<nombre>/`). Un plugin puede tener varias skills y hooks relacionados.
- **Nombres** en `kebab-case`. Prohibidos los prefijos reservados `claude-`, `anthropic-` y `cc-plugin-` en plugins.
  Evita nombres que parezcan oficiales de un producto ajeno (p. ej. `coolify` a secas).
- **Versiones** semánticas en `plugin.json`; cada cambio publicado sube la versión y se anota en `CHANGELOG.md`.
- **Scripts** en Python con solo la biblioteca estándar (sin dependencias que instalar), salida JSON, código de salida
  distinto de 0 en caso de error, y `--help` útil. Se invocan con `python3 -I` (no cargan código de la carpeta actual).
- **Nada personal en el repo:** ni IPs, dominios, uuids, correos ni secretos. Los datos de cada usuario van en
  `~/.config/<plugin>/` (o `${CLAUDE_PLUGIN_DATA}` si no hace falta editarlos a mano).
- **Userscripts** en `userscripts/<nombre>/<nombre>.user.js`: un solo archivo de JavaScript, sin dependencias, sin
  peticiones de red propias y sin código remoto. Su `@version` sigue semver y sube con cada cambio publicado (con su
  entrada en `CHANGELOG.md`); `@updateURL` y `@downloadURL` apuntan al archivo en bruto de `main`, así que a los
  usuarios solo les llega un cambio cuando se fusiona. Textos de la interfaz en inglés y castellano, según el
  idioma del navegador.
- **Tests** con pytest en `plugins/<nombre>/tests/`, sin red: las APIs, ssh y Docker se simulan con `monkeypatch`.
- **Antes de publicar:** `ruff check .`, `pytest -q plugins` y `claude plugin validate . --strict`.
