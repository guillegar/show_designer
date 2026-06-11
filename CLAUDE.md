# CLAUDE.md

Guía para Claude Code al trabajar en este repo. **Documento de retoma lean**: arquitectura,
estado vivo y convenciones. El detalle histórico profundo (changelogs, tabla de decisiones,
errores famosos, API MCP) está en **`docs/advanced/project-history.md`**. El layout del repo,
en **`STRUCTURE.md`**. La auditoría técnica, en **`ANALYSIS.md`**.

> ⚠️ **REGLA PERMANENTE (el usuario lo pidió):** al hacer cambios, **actualiza siempre la
> documentación** para que refleje el estado real — este `CLAUDE.md` (arquitectura/estado) y los
> docs de `docs/` que apliquen. No dejar la doc desfasada.

Estado a **2026-06-11** · **v1.10 (web)**: backend headless + frontend React, 4 vistas funcionando.

---

## 0. TL;DR

- **Entry point (v1.10, web):** `python -m server.main` → http://localhost:8000. Dev frontend:
  `cd web && npm run dev` (Vite :5173 proxea WS a :8000). Rebuild: `cd web && npm run build`.
- **UI Qt RETIRADA** (Fase 8, 2026-06-12): se borró del repo toda la UI PyQt5 (`src/ui/`,
  `src/utils/`, `src/viewer3d/`) y PyQt5 de requirements. **La web es el ÚNICO camino.** Rollback en
  el tag git `pre-qt-removal`.
- Software de iluminación profesional. El motor (Python) corre **headless** (sin Qt) y sirve una web
  React; el audio suena en el PC (reloj maestro) y el navegador es control + visualizador.
  Controlable por humano (web) y por Claude (MCP, compat en :9876).
- Hardware: **10 barras WLED** (93 LEDs c/u) en universos Art-Net 1..10 (IPs `192.168.1.201..210`).
- Proyectos en `projects/<slug>/` (canónico). Show de prueba: `el_taser` (`El Taser de Mama
  Remix.mp3`, 273.3 s). Audio NO se versiona (en disco; ver `.gitignore`).
- Licencia: **Prosperity Public License 3.0.0 (PPL)** — código original propio.
- **Checkpoints = git** (un commit por fase/feature; ya NO existe la carpeta `versions/`).
- Launchers Windows: `Luces.bat` (reinicio limpio + abre navegador), `Cerrar Luces.bat` (apaga),
  `Luces Espana.bat` (= `Luces.bat` + `set LUCES_PROJECT=himno_espana`).

### Estado auditoría (`ANALYSIS.md`) — 25 hallazgos P0→P3, plan en 7 fases
- **Fase 1 (quick wins) APLICADA** (2026-06-11): hallazgos 1,3,4,5,6,20,21 (contrato de shape en
  `Effect.expected_output_shape`, prints debug fuera, `event_mapping` borrado, `SystemExit`→sentinel,
  `except:pass`→log throttled, código muerto). 416 verde.
- **Fase 2 (higiene repo) APLICADA** (2026-06-11): hallazgos 22-25 (destrackeado ~112 MB de
  audio/stems/npz + `.gitignore`; `show_timeline.json` destrackeado; este CLAUDE.md partido;
  README/STRUCTURE.md sincronizados a 416 tests y arquitectura web).
- **Fase 3 (UUIDs de clips) APLICADA** (2026-06-11): hallazgo 2. `Clip.uid` (uuid4 hex[:12])
  reemplaza `id(self)`: persistido en `to_dict`/`from_dict` (clave `id`=uid string), lookup por
  uid en `ShowSession.find_clip_by_id` y `mcp_bridge._find_clip_by_id` con **fallback int legacy**.
  Firmas MCP `clip_id: int`→`str` (`mcp_show_server.py`); frontend tipa clip id como `string`
  (store.ts/Timeline.tsx). +9 tests (`test_clip_uid.py`). 425 verde + TS typecheck limpio.
- **Fase 4 (de-duplicación) APLICADA** (2026-06-12): hallazgos 7,8,9. Viewer 3D: fuente única
  `web/public/v3d/` (`VIEWER3D_DIR` y `viewer3d_server.VIEWER_DIR` repunteados; borradas las copias
  divergentes `viewer3d/` raíz y `src/viewer3d/*.js`, queda solo el server Qt). el_taser: borrados
  los residuos `src/projects/`, `src/io/projects/`, `data/projects/` (canónico = `projects/`).
  UndoManager: fuente única `src/core/undo.py` (`UndoManager` callback + `ClipSnapshotUndoManager`
  push); `server/undo_manager.py` re-exporta, el editor Qt importa. 425 verde.
- **Fase 5 (rendimiento) APLICADA** (2026-06-12): hallazgos 12,13,14, todos **parity-exactos**.
  (12) `TimelineScheduler.get_active_events` O(n)→O(log n+k) con bisect sobre eventos ordenados +
  ventana `[t-max_dur, t]`; (13) `rms_norm`/`flux_norm` precalculados (cache por id del timeseries)
  en `_compute_frame_legacy`; (14) `AnalysisService.get_audio_context` usa UN `searchsorted` + lerp
  vectorizado para las ~46 curvas (antes un `np.interp` por coeficiente). +3 tests de parity
  (`test_perf_parity.py`). 428 verde. (Nota: la ruta web `session.compute_frame` usa `_cached_actx`,
  así que el mayor beneficio es para Qt/analyzer/legacy.)
- **Fase 6 (logging+recursos) APLICADA** (2026-06-12): hallazgos 17,18. **`src/log.py`**: logging
  estándar (consola + archivo rotativo opcional vía `LUCES_LOG_FILE`, nivel vía `LUCES_LOG_LEVEL`) +
  `log_throttled()` (1/s por clave) para paths calientes. (17) los `except Exception: pass` MUDOS de
  los sends de red (`WledTarget`/`ArtnetNodeTarget.send`, `ShowEngine.send_artnet*`) ahora **loguean
  throttled** (el bug "IP mal configurada y no dice nada"). (18) `ShowEngine.close()` +
  `OutputRouter.close()` (cierran sockets, idempotentes) cableados al `@app.on_event("shutdown")` del
  server; `Timeline.save()` **atómico** (`.tmp` + `os.replace`). +4 tests (`test_logging_resources.py`).
  432 verde. NOTA: el barrido mecánico de los ~251 `print()` restantes a logger es **incremental por
  módulos** (no se hizo en bloque por churn/riesgo); de momento migrados los paths de red + `router.py`.
- **Fase 7 (core agnóstico + split editor) APLICADA** (2026-06-12): hallazgos 10,11,19.
  (10) `render_stub` + `BARS` (IPs de El Taser) + `_beat_env` + mapa de secciones → movidos a
  **`src/legacy_show.py`** (import perezoso para evitar circular; el core ya NO tiene defaults de
  canción; `ANALYSIS_FILE`/`TIMESERIES_FILE` muertos borrados). (11) **decisión de retirada
  explícita** (abajo). (19) primer paso del split: `WaveformData` → `src/ui/timeline/waveform.py`
  (Qt-free, testeable); el grueso (TimelineView 1455 LOC, paneles) es CONTINUO y queda diferido
  (Qt no es testeable sin PyQt5 aquí + se retira). +2 tests. 434 verde.
- **Fase 8 (retirada total del editor Qt) APLICADA** (2026-06-12): hallazgo 26 (sustituye y CANCELA
  el split del 19). Borrados `src/ui/`, `src/utils/`, `src/viewer3d/` + `launch_show_designer.bat` +
  `tests/test_timeline_waveform.py`; rama Qt de `_qt_call` (mcp_bridge) eliminada; PyQt5 fuera de
  requirements; `CREDITS.md` movido a `web/public/v3d/`. Tag `pre-qt-removal` = rollback. 432 verde.
- ✅ **AUDITORÍA `ANALYSIS.md` COMPLETA**: 8 fases aplicadas (1→8), un commit por fase sobre
  `timeline-fixes-2`. Único trabajo incremental que queda: barrido masivo `print`→logger (Fase 6,
  hecho en paths de red). Progreso en el memory `analysis_audit_progress.md`.

---

## 0.5 Arquitectura WEB (v1.10) — leer si tocas la web

La UI PyQt5 se **retiró** (Fase 8) en favor de una **web React + backend Python headless**. El backend
reutiliza SIN CAMBIOS `src/core`, `src/analysis`, `src/io`, `src/mcp`. Todo vive en `server/`
(Python) y `web/` (React+TS+Vite).

```
Navegador (web/ — Vite+React+TS)
  Topbar · Tabs · Transport      ← estado por /ws/stream
  Timeline · Live · Analyzer · Patch  ← JSON-RPC /ws/control + frames binarios
        │ HTTP estáticos   │ /ws/control (JSON-RPC)   │ /ws/stream (frames+estado+dmx)
        ▼                  ▼                          ▼
server/ (headless, asyncio, SIN Qt) — python -m server.main  (:8000)
  web.py        FastAPI: dist + /ws/control + /ws/stream (+ compat MCP :9876)
  dispatcher.py REUSA handlers de mcp_bridge.py + handlers web-only (set_loop/set_rec/
                set_volume/set_track_mute|solo/set_clip_effect/set_clip_preset/...).
                Mutadores de rig regeneran rig_layout.json (_RIG_MUTATORS). Validación
                vía server/validators.py. Desacople (B1): la política de `_qt_call` la
                provee la SESIÓN (`_qt_call_impl`); el bridge la detecta vía getattr.
  tick.py       loop asyncio 30 FPS: compute_frame → Art-Net → broadcast (dmx ~7.5 FPS,
                broadcast en paralelo con gather, estado JSON throttle ~10 FPS).
  session.py    ShowSession: dueño headless de timeline+show_engine+rig+analysis+library+
                audio. compute_frame = port Qt-free (bucket-index O(activos)). Undo en
                server/undo_manager.py. Reloj maestro = HeadlessAudioPlayer (pygame.mixer).
```

Claves:
- **Continuidad MCP/Claude**: el dispatcher sirve el mismo JSON-RPC en `:9876`, así
  `mcp_show_server.py` NO se toca. Claude controla con `mcp__show-control__*`.
- **El navegador NO recalcula luces**: consume el frame binario real (10×93×3 = 2790 B) del `/ws/stream`.
- **Tests** del backend web: `test_session.py`, `test_dispatcher.py`, `test_web.py` (este con
  `LUCES_NO_MCP_COMPAT=1` para no abrir :9876), `test_validators`, `test_undo_manager`,
  `test_stream_hub`, `test_timeline_fixes`. **416 verdes** en total.
- Deps web: `fastapi`, `uvicorn[standard]`, `httpx` (test); frontend `vite react zustand` +
  **`react-moveable` + `react-selecto`** (interacción del timeline).
- **Proyecto de arranque**: `ShowSession` usa la env var **`LUCES_PROJECT`** (slug); sin ella, el
  default de `ProjectManager.ensure_migrated()` = `projects[0]` alfabético (= `el_taser`). `load_show`
  por MCP solo intercambia `timeline.clips`, no el audio ni la sesión. Vive en `server/web.py` (`_startup`).

### Timeline web — interacción (si tocas `web/src/views/Timeline.tsx`)
- Sobre **react-moveable** (drag + resize + snap a guías) y **react-selecto** (rubber-band). NO hay
  matemática de punteros a mano (se eliminó: causaba bugs). Geometría pura en `timelineGeometry.ts`
  (`xToMs/msToX/buildLaneLayout/yToLane`, hit-test de filas con altura variable).
- Arrastre vertical: el clip sigue al cursor; en `onDrag` se hit-testea bar+layer con rects medidos;
  al soltar commitea `new_track`/`new_layer` vía `move_clip` (`_h_move_clip` soporta ambos + start/end).
- Pintar (modo draw): efecto base → `set_clip_effect`; preset → `set_clip_preset` (web-only en
  `dispatcher.py`). Atajos: `V/D/C` (select/draw/cut), `Q` (snap), `Ctrl+0` (reset zoom), `[`/`]`
  (±50ms), `Ctrl+C/V`, `Ctrl+A`/`Ctrl+Shift+A`, `?` (ayuda). Aux: `ClipInspector`, `Toast`, `HelpOverlay`.

### Viewer 3D en la web (no volver a romperlo)
- Va en `<iframe src="/v3d/">` (`web/src/views/Viewer3D.tsx`). Los archivos se sirven desde
  **`web/public/v3d/`** (Vite los copia a `web/dist/v3d/` en CADA build; `npm run build` VACÍA `dist/`,
  así que los ficheros DEBEN vivir en `public/v3d/`, no en `dist/v3d/`). Three.js por CDN (importmap).
- `session.py.sync_rig_layout()` regenera `rig_layout.json`; el dispatcher lo llama tras cada
  `_RIG_MUTATORS` (move/set/add/delete_fixture, save_rig, load_show). El viewer recarga con cache-bust
  al re-montarse la pestaña (no hay update en vivo mientras editas en Patch).

### Recetas de color (para el proyecto bandera y similares)
- **Color sólido estable**: plugin `solid_color.py` (`SolidColorEffect`, id **1004**, params r,g,b) →
  forma `(1,LEDS,3)` CONSTANTE; con `scope="per_bar"`+`layer=0` el motor hace `frame[clip.track]=r[0]`.
  NO usar efectos *flash* (se apagan tras su `duration_ms`).
- **Color con onda (ondeante)**: `waving_flag.py` (`WavingColorEffect`, id **1005**, params
  r,g,b,bar_index,speed,amplitude,bar_k,led_k) → modula brillo con `sin(w·t - bar_index·bar_k - led·led_k)`.
  Pasa `bar_index` distinto por clip para que la onda viaje entre barras.
- Proyecto `himno_espana`: 10 clips per-bar, ROJO en barras 0,1,2,7,8,9 y AMARILLO en 3,4,5,6, efecto
  `waving_color`. (Detalle en el memory `solid_color_stable_pattern.md`.)

---

## 1. Arquitectura — bajo acoplamiento (lo que el usuario más valora)

Núcleo que consume el backend web (`server/`): `src/core` (show_engine,
timeline_model, fixtures, effects_engine, channel_effects), `src/analysis` (analyzer_service),
`src/io` (loaders GDTF, OutputRouter, exporter, project_manager), `src/mcp` (bridge + FastMCP server).

Principios de acoplamiento (los que importan):
- **Efectos pixel no conocen Qt, ni red, ni FixtureRig**. Reciben `(elapsed_time, bars_state,
  audio_context, **params)` y devuelven array RGB. Contrato de forma: `Effect.expected_output_shape`
  (PER_BAR→`(1,93,3)`, ALL_BARS/GLOBAL→`(10,93,3)`).
- **ChannelEffect** igual: `(t, fixture, audio_context, params) → {channel_name: value}`. Sin Qt/red/router.
- `show_engine` ↔ `OutputRouter`: el assembler delega `send_universe_via_router(uni, bytes_512)`; el
  router decide WLED / artnet_node / sim_only según `output_targets.json` (separado de `fixtures.json`).
- `FixtureProfile` carga indistintamente de `.json` o `.gdtf`; quien usa el modelo no sabe de dónde vino.

> La tabla completa de las "8 piezas", el diagrama de la era Qt y las decisiones de diseño con su
> porqué están en `docs/advanced/project-history.md`.

---

## 2. Cómo arrancar (cold start)

```powershell
cd C:\Users\guille\Documents\Claude\Projects\show-designer
python -m venv venv311                 # si no existe
.\venv311\Scripts\Activate.ps1
pip install -r requirements.txt
python -m server.main                  # web en http://localhost:8000  (único entry point)
```

- Claude por MCP: `.mcp.json` ya configurado; los tools aparecen como `mcp__show-control__*`.
- Reinicios: si tocas `mcp_bridge.py`/`dispatcher.py` → reinicia el server; si tocas
  `mcp_show_server.py` → reinicia **Claude Code**. Puertos zombies (errno 10048):
  `Get-Process python | Stop-Process -Force`.

---

## 7. Comandos comunes

```powershell
pytest tests/ -v                                  # 416 tests (~20s)
pytest tests/test_session.py -v                   # un archivo
pytest tests/test_effects_render.py::test_x -v    # un test
pytest tests/ --cov=src --cov-report=html         # cobertura (htmlcov/)
```

---

## 10. Tics del usuario (recordar)

- Escribe en español, a veces sin tildes y con erratas. **No corregirle.**
- Quiere **rapidez** y **resultados visibles**: prefiere ver el visualizer encendido antes que
  arquitectura perfecta.
- Le preocupa el **acoplamiento**: cualquier refactor que lo reduzca → win.
- Quiere código **suyo**: original, sin copiar de terceros. Dependencias reales (Three.js MIT,
  pygdtf LGPL) se usan como librerías y se acreditan en `CREDITS.md`.
- **Auto Mode activo**: avanzar sin pedir permiso para decisiones razonables; parar solo si la
  dirección es genuinamente ambigua.
- **Checkpoints con git** (un commit por fase). Antes pedía carpetas `versions/`; ahora usa git.
- **Pregunta principios estructurales**: cuando una decisión afecta a TODO el sistema, preguntar
  antes con AskUserQuestion. Un mal principio cuesta caro de revertir.
