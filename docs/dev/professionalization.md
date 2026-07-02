# Profesionalización — log de pasos

Registro de las mejoras de madurez de ingeniería aplicadas (evaluación `/architecture`).
Cada paso: qué, por qué, resultado. Un commit por bloque.

Leyenda: ✅ hecho · 🟡 parcial (patrón establecido + resto documentado) · ⏳ pendiente

## P0 — Guardarraíles (tooling + CI)
- [x] **#1 `pyproject.toml`** — metadata + deps (core/dev/audio) + entry point + config ruff/mypy.
- [x] **#2 Ruff** — lint con línea 120; **1054 autofixes**; `ruff check` **verde**.
- [x] **#3 CI de Python** — `.github/workflows/python-ci.yml` (ruff bloqueante + mypy informativo).
- [x] **#4 pre-commit** — `.pre-commit-config.yaml` (ruff --fix + hygiene hooks).

## P1 — Salud del código
- [x] **#8 mypy gradual** — config lenient en `pyproject.toml` + CI informativo (baseline 95 errores).
- [🟡] **#7 Dispatch async** — DOCUMENTADO. El global `run_in_executor` se **descarta** (rompería la
  invariante mono-hilo). Patrón correcto = offload por handler (ya en waveform/render/key).
- [🟡] **#6 print → logger** — hot-path/errores ya migrados (tick, offline_render, red); ~143
  informativos restantes (mecánico, por módulo).
- [🟡] **#5 Despiece de `dispatcher.py`** — DOCUMENTADO (plan `server/handlers/` + registro por decorador).

## P2 — Pulido y operabilidad
- [🟡] **#9 Despiece de `Timeline.tsx`** — DOCUMENTADO (subcomponentes; extraer UI antes que el gesto).
- [🟡] **#10 Code-splitting frontend** — DOCUMENTADO (`React.lazy` de vistas pesadas).
- [x] **#11 Higiene de config/secretos** — `docs/dev/configuration.md` (`LUCES_*` + secretos de output_targets).
- [x] **#12 Releases** — `CHANGELOG.md` + `docs.yml` (deploy MkDocs a GitHub Pages).
- [🟡] **#13** — gitignore de `rig_layout.json` con CAVEAT (regeneración en arranque; ver abajo).

---

## Bitácora

### 2026-07-01 · P0 — guardarraíles de tooling
- **#1** `pyproject.toml`: metadata, deps runtime (espejo de `requirements.txt`), extras `dev`
  (pytest, pytest-cov, pytest-asyncio, ruff, mypy) y `audio` (demucs); entry point
  `show-designer = server.main:main`; packaging `server`/`src`/`plugins`. `pip install -e .` OK.
- **#2** Ruff 0.15: config en pyproject (select E,F,I,W,UP,B; línea 120; ignores graduales +
  per-file para el bootstrap de `sys.path` y los probes de deps opcionales). `ruff check --fix`
  aplicó **1054 fixes** (orden/limpieza de imports) en ~100 ficheros; `ruff check` = **verde**.
- **#3** `python-ci.yml`: job lint (ruff bloqueante + `mypy || true`). Los tests aún NO corren en CI
  (dependen de audio/proyectos locales no versionados) → pendiente: fixtures sintéticos.
- **#4** `.pre-commit-config.yaml`: ruff `--fix` + trailing-whitespace/EOF/yaml/json/large-files.
- **Deuda saldada:** los **17 tests pre-existentes en rojo** → **verde**. `pytest-asyncio`
  (+ `asyncio_mode=auto`) arregla 10 async; `Pillow` arregla 6 de PIL; el bench
  `test_bench_compute_frame_…` (faltaba `session._recording` al construir la sesión con
  `object.__new__`) arregla 1. **Suite completa: 1063 tests, 0 fallos.**
- **mypy baseline:** 95 errores en 17 ficheros (gradual, no bloqueante) — deuda a reducir.

### 2026-07-01 · P2 — operabilidad (parcial)
- **#11** `docs/dev/configuration.md`: tabla de `LUCES_*` + campos sensibles de `output_targets.json`
  (api_key/tokens/webhooks/secret) con nota de seguridad (no versionar secretos; host `127.0.0.1`).
- **#12** `CHANGELOG.md` (Keep a Changelog) + `.github/workflows/docs.yml` (deploy MkDocs a Pages
  al hacer push a `main`).

---

## Siguientes pasos documentados (decisiones + planes)

Ítems que **no se ejecutan ahora** para no desestabilizar los 1063 tests verdes; quedan
especificados para una sesión dedicada.

### #7 — Dispatch async  ⚠️ decisión
`dispatcher.handle()` corre **síncrono en el hilo del event loop**. Mover TODO a
`run_in_executor` **se descarta**: rompería la invariante documentada en `tick.py` (tick +
handlers serializados en el único hilo del loop → **sin locks**). Hacerlo introduciría carreras
sobre el estado de la sesión (timeline, etc.).
**Patrón correcto (ya aplicado):** que cada handler con trabajo bloqueante lo delegue a un executor
y devuelva rápido (waveform, render offline, key_detector lo hacen). **Acción:** auditar handlers
que aún hagan I/O bloqueante en el loop y aplicarles el mismo patrón; el `.result(timeout=30)` del
path async (marketplace) solo afecta a operaciones raras fuera de directo.

### #5 — Despiece de `dispatcher.py` (4517 líneas)
Plan: `server/handlers/<dominio>.py` (`clips`, `rig`, `live`, `mixer`, `analyzer`, `patterns`…) con
un decorador `@handler("nombre")` que rellene el registro; `_LOCAL` se ensambla importando los
submódulos. **Riesgo:** muchos handlers dependen de helpers privados del mismo fichero → mover por
grupos, **corriendo los tests tras cada módulo**. No cambia la API JSON-RPC. Requiere pase dedicado.

### #6 — `print` → logger (resto)
Ya migrados los de error/hot-path (tick, offline_render, sends de red). Quedan ~143 informativos
(`server/session.py` 21, `src/` 111) — mecánico y de bajo riesgo, por módulo.

### #9 — Despiece de `Timeline.tsx` (1791 líneas)
Extraer `TimelineRuler`, `LanesList`, `ClipRenderer`, `MoveableLayer`, `WaveformCanvas`. **Cuidado:**
la lógica de drag/drop + update optimista (Fase 9) es delicada → extraer primero las piezas de UI y
mantener el gesto junto. Tipar las respuestas RPC (quitar `any`).

### #10 — Code-splitting del frontend (bundle >624 KB)
`React.lazy` + `Suspense` para las vistas pesadas (Viewer3D ya aislado en iframe; Preview/Analyzer)
para reducir el bundle inicial.

### #13 — gitignore de `web/public/v3d/rig_layout.json`  ⚠️ caveat
El backend lo **regenera** (`sync_rig_layout`). Gitignorearlo + borrarlo puede dejar el visor de un
clon nuevo con 404 hasta la primera regeneración → hacerlo **solo** tras confirmar que se regenera
en el arranque (o generarlo en `_startup`).

