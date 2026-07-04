# Changelog

Todos los cambios notables de Show Designer Pro. Formato basado en
[Keep a Changelog](https://keepachangelog.com/); el proyecto usa versionado semántico.

El detalle profundo (por fases del roadmap) está en [`CLAUDE.md`](CLAUDE.md) y
[`docs/roadmap/`](docs/roadmap/).

## [Unreleased]

### Added
- **Tooling de ingeniería:** `pyproject.toml` (metadata, extras `dev`/`audio`, entry point
  `show-designer`), **Ruff** (lint), **mypy** (gradual), **CI de Python** (`python-ci.yml`) y
  **pre-commit**. Log en [`docs/dev/professionalization.md`](docs/dev/professionalization.md).
- **ADR-005:** despiece de `dispatcher.py` en `server/handlers/` por dominio (waveform, projects,
  patch) — 4517 → 2963 líneas, sin cambios de API JSON-RPC.
- **Code-splitting** del frontend (`React.lazy`): bundle inicial 624 → 524 kB; inicio del despiece
  de `Timeline.tsx` (`views/timeline/`).
- CI de frontend (`frontend-ci.yml`): tsc + Vitest en cada push de `web/`.
- Documentación de configuración ([`docs/dev/configuration.md`](docs/dev/configuration.md)).

### Changed
- **Migración legacy cerrada:** retirado el andamiaje pre-`projects/` (`fixtures.json` /
  `show_timeline.json` raíz, `ensure_migrated` de copia legacy). `save_rig` (MCP) ahora guarda en
  el rig del proyecto activo.
- Documentación reescrita y puesta al día (README, STRUCTURE, docs MkDocs); roadmaps completados
  movidos a `docs/roadmap/`.

### Fixed
- **Usabilidad/scroll:** las columnas de paneles de **Live** (`.live-side`, ~16 paneles, 1229 px
  ocultos) y **Patch** (`.patch-side`, 631 px ocultos) no tenían scroll y dejaban paneles
  inaccesibles; ahora `overflow-y: auto`. El `body` permite scroll horizontal cuando la ventana
  es más estrecha que el mínimo de la app (1100 px). Verificado en navegador real.
- La forma de onda del timeline ya no bloquea el event loop (cálculo en executor + evento
  `waveform_ready`; precalentado en el arranque).
- 17 tests pre-existentes en rojo → verde (`pytest-asyncio`, `Pillow`, bug del bench). **1063
  tests, 0 fallos.**
- Visor 3D: protocolo WS derivado (`ws`/`wss`). `control.ts`: token fuera de la URL + heartbeat.
- `offline_render`/`tick`: errores logueados (throttled) en vez de silenciados.

## [2.0.0] — 2026-06-14

Roadmaps v2 + v3 + v4 completos: editor de timeline profesional, efectos LED + DMX, análisis de
audio, visor 3D, control por Claude (MCP), directo (macros/cues/MIDI/OSC/auto-VJ), REST API,
webhooks, multiusuario, marketplace de plugins, backup/restore y hardening de seguridad.
Ver [`CLAUDE.md`](CLAUDE.md) para el desglose por fases.
