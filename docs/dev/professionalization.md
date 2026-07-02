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
- [🟡] **#7 Dispatch async** — decisión tomada: el global `run_in_executor` se **descarta** (rompería
  la invariante mono-hilo). Patrón correcto = offload por handler (ya en waveform/render/key).
- [x] **#6 print → logger** — **COMPLETO (server/ + src/)**: 31 + 106 migrados. Quedan solo 3 prints
  deliberados y comentados (banner CLI de `main.py`; 2 chequeos de deps a stderr en
  `mcp_show_server.py` — proceso stdio MCP, el logger no existe aún en ese punto).
- [x] **#5 Despiece de `dispatcher.py`** — **COMPLETO (ADR-005, 5 tandas)**: `server/handlers/`
  con **27 módulos de dominio**; `dispatcher.py` = **508 líneas no vacías (−89% desde 4517)**,
  fachada pura (auth + undo-snapshot + gesture-log + dispatch + merge). Re-exports de compat se
  quedan como superficie estable de los tests (decisión en el ADR). Bonus: fix de 3 paths
  `__file__`-relativos rotos y `load_all()` con autodescubrimiento.

## P2 — Pulido y operabilidad
- [🟡] **#9 Despiece de `Timeline.tsx`** — **EN MARCHA**: `views/timeline/` con `WaveformCanvas`,
  `GenerateShowModal`, `GenerateSectionModal` y `MarkerContextMenu` → **1791 → 1529 líneas**
  (gesto/optimista intactos). Resto: incremental (toolbar, ruler, lanes).
- [x] **#10 Code-splitting frontend** — `React.lazy` en todas las vistas menos Timeline: bundle
  inicial **624 → 524 kB** (gzip 192 → 166); 6 chunks bajo demanda. Verificado servido (HTTP 200).
- [x] **#11 Higiene de config/secretos** — `docs/dev/configuration.md` (`LUCES_*` + secretos de output_targets).
- [x] **#12 Releases** — `CHANGELOG.md` + `docs.yml` (deploy MkDocs a GitHub Pages).
- [x] **#13** — `rig_layout.json` gitignoreado/destrackeado (verificado: `ShowSession.__init__` →
  `sync_rig_layout` lo regenera en cada arranque → sin 404 en clon nuevo).

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

### 2026-07-01 · sesión 5 — ADR-005 COMPLETO (tandas 3-5)
- **Tanda 3** (7 módulos): mixer, render_export, autosave, osc, movers, switch, tempo.
  **BUGFIX** revelado por la migración: 3 handlers localizaban `output_targets.json` con
  `Path(__file__).parent.parent` — correcto en `server/` pero roto un nivel más adentro
  (¡el de `patch.py` llevaba roto desde la tanda 1!). Anclados a `PROJECT_DIR`.
- **Tanda 4** (8 módulos): patch_visual, gdtf, output_test (con los 3 strays del rango K2),
  webhooks_config, viewer3d, pixelmap, showgen, bundle_market. **FIX estructural**: `load_all()`
  autodescubre módulos con pkgutil — la lista hardcodeada quedó obsoleta en silencio cuando ruff
  la reformateó (14 tests en rojo lo delataron). Dependencias cruzadas: viewer3d importa
  STAGE_W/D de patch_visual; replay_gesture usa `dispatcher._LOCAL` vía import perezoso.
- **Tanda 5** (5 módulos + anexo): clips_edit, feedback, presets, automation, patterns;
  export_csv/qlc anexados a render_export. **dispatcher.py = 508 líneas no vacías (−89%)**.
- Verificación por tanda: ruff verde + suite completa **1063/0**; al final, smoke de arranque
  real (:8000, ping + waveform + 1358 clips).

### 2026-07-01 · sesión 4 — frente frontend (en paralelo al worktree del dispatcher)
- Reparto de trabajo: la tarea en background (worktree aislado) continúa los dominios del
  dispatcher; esta sesión avanza SOLO frontend para evitar conflictos de merge.
- **#9**: 2 extracciones más a `views/timeline/` — `GenerateSectionModal` (✨ Generar clips en
  sección; estado sección/disparo/barras propio) y `MarkerContextMenu` (I2: color/categoría/
  borrar). Timeline.tsx **1600 → 1529** (total −262 desde 1791).
- **Tipado RPC** (hallazgo de la revisión: exceso de `any`): `control.call<T>()` tipado en TODOS
  los fetch de `store.ts` (clips/fixtures/effects/sections/presets/cues/markers/groups/patterns/
  instances + analyzer_summary) y `App.tsx` (list_projects, auth_get_role). **0 `: any`** en
  ambos ficheros; `RawSection` modela el `label` legacy del analyzer.
- Verificación: tsc+vite build, 36 Vitest, smoke real (:8000 — bundle nuevo servido + WS +
  1358 clips).

### 2026-07-01 · sesión 3 — ADR-005 tanda 2 + Fase 6 cerrada
- **#5 (tanda 2)**: 4 dominios más extraídos — `live.py` (C1+C2+I1, 9 handlers + `_live_emit`),
  `markers.py` (I2+I3, mutadores declarados en el módulo), `autovj.py` (D1+D2, 10 handlers),
  `cues.py` (E1, 9 handlers). `dispatcher.py` **2963 → 2459** (total **-46%** desde 4517).
  Gotcha del script de corte: los bloques deben extraerse **top-down** (el marcador final de cada
  corte es el inicial del siguiente); en orden inverso el marcador desaparece antes de usarse.
- **#6 (src/)**: barrido mecánico con heurística de nivel — 106 prints migrados en 9 ficheros.
  Corrección manual: los 2 prints de chequeo de deps de `mcp_show_server.py` se REVIRTIERON a
  `print(..., file=sys.stderr)` con comentario (el logger no existe aún y stdout es el canal MCP).
  **La Fase 6 de ANALYSIS.md queda cerrada.**
- Verificación de ambas: suite completa **1063/0** + ruff verde tras cada tanda.

### 2026-07-01 · sesión 2 — logging, ADR-005, splitting
- **#6 (server/)**: 31 `print()` → `_log.info/warning/error` en `session.py`, `web.py`,
  `audio_headless.py`, `dispatcher.py`. `main.py` conserva su banner CLI como print (UX de
  arranque visible con cualquier `LUCES_LOG_LEVEL`).
- **#5 (ADR-005)**: `server/handlers/` — registro (`LOCAL`/mutadores/`load_all()` + decorador para
  nuevos) y 3 dominios extraídos verbatim: `waveform.py` (117), `projects.py` (450), `patch.py`
  (324). `dispatcher.py` **4517 → 2963 líneas**; fachada con merge + re-exports de compat.
  Gotcha real: `_h_get_fixture_pan_tilt` estaba FÍSICAMENTE dentro de la sección de proyectos
  (pertenece a movers) → devuelto al dispatcher. 2 mocks de tests actualizados al módulo nuevo
  (regla: `mock.patch` apunta al módulo DONDE SE USA el símbolo). **Suite 1063/0.**
- **#10**: `React.lazy`+`Suspense` (Timeline eager por ser la pestaña default). Bundle
  624→524 kB; chunks Live/Patch/Analyzer/ProjectManager/Preview/Viewer3D. Smoke real: chunk
  servido HTTP 200 desde :8000.
- **#9**: `views/timeline/` — `WaveformCanvas.tsx` (fetch+draw autónomos) y
  `GenerateShowModal.tsx` (estado propio). Timeline.tsx **1791 → 1600**; CERO cambios en la
  lógica de drag/drop/optimista (Fase 9 intacta).
- **#13**: `rig_layout.json` fuera de git (regeneración en arranque verificada en código:
  `session.py:150`).

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

