# Análisis técnico — Show Designer Pro v1.9

**Fecha**: 2026-06-11 · **Alcance**: código, arquitectura, rendimiento y organización del repo (~24k LOC Python)

**Verificación**: corrí la suite en un entorno Linux limpio (sin librosa/madmom/PyQt5):
**355 passed, 1 failed** (`test_plugin_system.py::test_plugin_render_no_audio_context`). El badge "363/363" del README está desactualizado.

---

## Resumen ejecutivo

El proyecto está bien encaminado: separación core/UI/IO real, suite de tests amplia, y la migración a backend headless (`server/`) reutilizando los handlers del bridge es una buena decisión. Los problemas principales son: **un test roto por contrato de shapes ambiguo**, **IDs de clips basados en `id()` de Python** (frágil para el protocolo JSON-RPC), **código de debug y rutas hardcodeadas en el core**, **duplicación creciente** (viewer3d ×4, proyecto el_taser ×3, dos UndoManager), y **~110 MB de audio/stems versionados en git**.

---

## P0 — Corregir ya (bugs y riesgos activos)

### 1. Test fallando: contrato de shape de los plugins
`SolidColorEffect` (plugins/effects/solid_color.py) devuelve `(1, LEDS, 3)` por diseño documentado, pero `test_plugin_render_no_audio_context` exige `(NUM_BARS, LEDS, 3)` a todo plugin con id ≥ 1000.

- **Causa raíz**: `Effect.render()` admite dos shapes de salida válidos pero el contrato no está formalizado (ni en la clase base ni en el test).
- **Propuesta**: declarar el shape esperado como atributo de clase (`output_shape: 'per_bar' | 'full'` o derivarlo de `scope`), validar en `EffectLibrary` al registrar, y que el test acepte ambos shapes según la declaración.

### 2. IDs de clips = `id(self)` (timeline_model.py:110, mcp_bridge.py `_find_clip_by_id`)
Los clientes JSON-RPC (Claude, web) referencian clips por `id(clip)`:

- No es estable entre sesiones ni tras `Timeline.load()` → cualquier referencia guardada se invalida.
- CPython puede **reusar** direcciones de memoria tras GC → un `clip_id` viejo puede apuntar a un clip distinto (borrado + creación = mismo id posible).
- **Propuesta**: añadir `uid: str = field(default_factory=lambda: uuid4().hex[:12])` a `Clip`, persistirlo en JSON, y migrar `_find_clip_by_id`. Mantener compat aceptando ints legacy durante una versión.

### 3. Debug prints hardcodeados en el hot path (show_engine.py:1014-1032)
`render_channels_for_fixture()` tiene tres `print("[DEBUG] ...")` condicionados a `fixture_id == 'mover_wash_L_back'`. Se ejecutan en el render loop (30 fps × fixtures). Eliminar.

### 4. Módulo `event_mapping` no existe
`ShowEngine.schedule_from_mapping_file()` y `maybe_reload_mapping()` importan `event_mapping`, que no está en el repo → siempre fallan con ImportError silenciado. Decidir: restaurar el módulo o borrar ambos métodos (y el panel que dependa de ellos).

### 5. `SystemExit` en import (mcp_bridge.py:41)
Si falta `websockets`, importar el módulo mata el proceso entero (`raise SystemExit`). Esto rompió la colección de pytest. Cambiar a `ImportError` con mensaje, y que el caller decida.

### 6. `except: pass` desnudo en el render del editor (timeline_editor.py:3752)
`_compute_frame` traga **cualquier** excepción de los efectos, incluido `KeyboardInterrupt`. Un efecto roto produce barras negras sin pista alguna. Mínimo: `except Exception as e:` + log con throttle (1 vez por effect_id).

---

## P1 — Arquitectura

### 7. Duplicación del viewer 3D (×4, ya divergentes)
`viewer3d/`, `src/viewer3d/`, `web/public/v3d/`, `web/dist/v3d/` — los md5 de `main.js` **ya no coinciden** entre las tres primeras copias. Es cuestión de tiempo que un fix se aplique en una sola.

- **Propuesta**: una única fuente (sugerencia: `web/public/v3d/` si el futuro es el server web), `web/dist/` solo como artefacto de build (y fuera de git — ya está en .gitignore pero hay archivos trackeados), y eliminar las otras dos. Si el viewer Qt necesita los archivos, servirlos desde la misma ruta.

### 8. Proyecto `el_taser` triplicado
`projects/el_taser/`, `src/projects/el_taser/`, `src/io/projects/el_taser/` (y STRUCTURE.md dice `data/projects/`). Probablemente residuo de un refactor de `project_manager`. Dejar **una** ubicación canónica (la que use `get_manager()`), borrar el resto, y actualizar STRUCTURE.md, que ya no refleja la realidad (no menciona `server/` ni `web/`).

### 9. Dos UndoManager
`server/undo_manager.py` y `timeline_editor.py:139` implementan undo por separado → el historial del editor Qt y del server web pueden divergir en semántica. Extraer a `src/core/undo.py` y que ambos lo consuman.

### 10. Constantes hardcodeadas de un rig/canción concretos en el core
`show_engine.py` define `BARS` (IPs 192.168.1.201-210), `ANALYSIS_FILE`/`TIMESERIES_FILE` apuntando a `el_taser_de_mama_remix`, y `render_stub` con el mapa de secciones de esa canción. `fixtures.py` + `OutputRouter` + `AnalysisService` ya existen justamente para esto.

- **Propuesta**: mover `render_stub` y `BARS` a un módulo `legacy_show.py` (o a `_legacy/`), y que `ShowEngine` no tenga ningún default específico de canción: si no hay `analysis` inyectado, queda descargado en vez de cargar El Taser.

### 11. Transición Qt → web sin plan de retirada explícito
Hoy conviven `dual_app.py` (PyQt5) y `server/` + `web/` cubriendo lo mismo (52 handlers compartidos, 22 extra en dispatcher). La reutilización de handlers está bien resuelta, pero cada feature nueva ahora cuesta el doble de superficie de test/UI. Recomendación: declarar en CLAUDE.md cuál es el camino principal, congelar features en el secundario y ponerle fecha de retirada (o asumir mantener ambos a propósito).

---

## P2 — Rendimiento

### 12. `TimelineScheduler.get_active_events()` es O(n) por frame (show_engine.py:183)
Con `auto_schedule_from_analysis()` se programan cientos/miles de eventos (beats + onsets + kicks), y cada frame recorre **todos**. A 30 fps con ~2000 eventos son ~60k comparaciones/s más el lookup de effect por evento.

- **Propuesta**: mantener `self.events` ordenado por `time_sec` y usar `bisect` con una ventana `[t - max_duration, t]` (max_duration = duración máxima de efecto del catálogo, ~2 s). Pasa de O(n) a O(log n + k). El patrón bucket-index de `timeline_editor._compute_frame` ya demuestra la solución en el propio repo.

### 13. Normalización de RMS/flux recalculada cada frame (show_engine.py:766-767)
`_compute_frame_legacy` hace `rms.min()/max()` sobre el array completo en cada tick. Precalcular `rms_norm`/`flux_norm` una vez en `_load_data()`.

### 14. `get_audio_context()` interpola ~46 curvas por frame
13 MFCC + 12 chroma + 6 tonnetz + 7 contrast + 8 mel + 5 escalares, con `np.interp` por coeficiente (búsqueda binaria repetida sobre el mismo `times`). Optimización sencilla: calcular el índice una vez (`np.searchsorted`) y hacer lerp manual de todos los arrays con ese índice; o cachear por bucket de tiempo como ya hace el editor con `_CACHED_ACTX`.

### 15. Bucles por-LED en Python en el path legacy (render_stub, fill_bar)
93 LEDs × 10 barras × 30 fps en bucles Python puros. Es el path legacy (el nuevo es numpy), así que solo importa si `use_effects=False` sigue siendo un modo soportado; si no, es un motivo más para el punto 10.

### 16. `section_at()` lineal por frame (menor)
Las secciones son ~8, así que es despreciable, pero ya tenéis `bisect` importado: lista de starts ordenada y listo.

---

## P3 — Calidad de código y hábitos

### 17. 187 `except Exception` + 251 `print()` en src/server
El patrón "log con print y seguir" es deliberado para no matar el render loop (razonable), pero:

- Sin `logging`, no hay niveles ni forma de silenciar/filtrar; la consola en vivo se llena de ruido.
- Varios `except Exception: pass` totalmente mudos (`send_artnet`, `send_artnet_to`) ocultan problemas de red reales (típico: IP mal configurada y "no funciona y no dice nada").
- **Propuesta**: módulo `src/log.py` con `logging` estándar (consola + archivo rotativo), reemplazo mecánico de prints, y en los paths de red un contador de errores con log throttled (1/s) en vez de silencio.

### 18. Recursos sin cierre
`ShowEngine.sock` y los sockets de `OutputRouter` nunca se cierran; `Timeline.save()` escribe sin write-tmp-rename (un crash a mitad de `json.dump` corrompe `show_timeline.json`). Propuesta: `close()` en ShowEngine/Router llamado desde `closeEvent`/shutdown del server, y guardado atómico (escribir a `.tmp` + `os.replace`).

### 19. `timeline_editor.py` con 3806 LOC y 11 clases
`TimelineView` (1455 líneas) y `TimelineEditorWindow` (1423) concentran demasiado. No urge, pero cuando toquéis el editor: extraer `UndoManager` (punto 9), `WaveformData`, `AudioEngine`, `MinimapWidget` y los paneles a archivos propios bajo `src/ui/timeline/`. Reduce conflictos y tiempos de carga mental.

### 20. Línea ilegible en el hot path (timeline_editor.py:3750-3751)
```python
frame = np.maximum(frame,r) if clip.scope=='global' else (
    frame.__setitem__((clip.track,), np.maximum(frame[clip.track],r[clip.track])) or frame)
```
Usar un if/else normal de 4 líneas.

### 21. Código muerto
`FADE_START = 9999.0` / `FADE_DUR` en `render_stub` (no se usan), `_find_local_maxima` (sin callers aparentes), `send_universe_via_router` con rama else vacía. Pasar `vulture` o similar y limpiar.

---

## Higiene del repo

### 22. ~110 MB de audio versionado en git
Trackeados: `El Taser de Mama Remix.mp3` (8.8 MB), `Himno_Espana.mp3` (3.9 MB) y **101 MB de stems wav** (`analizadas/.../htdemucs/*.wav`). Cada clone arrastra todo y el historial solo crece.

- **Propuesta**: `git rm --cached` de mp3/wav + añadir `*.mp3`, `*.wav`, `analizadas/**/stems/` al .gitignore. Si queréis versionarlos, Git LFS. Los stems son regenerables con demucs (`scripts/process_stems.py`).

### 23. Archivos sueltos en sitios raros
`src/ui/crash.log` (los .log están en .gitignore pero este vive en src), mp3 en la raíz, `show_timeline.json` (428 KB de datos de usuario) en la raíz versionado. Mover datos de usuario a `data/` o `projects/` como dice la propia STRUCTURE.md.

### 24. CLAUDE.md de 48 KB / 637 líneas
Como memoria de trabajo para Claude es contraproducente: consume contexto en cada sesión. Dividir: CLAUDE.md corto (~100 líneas: arquitectura, comandos, convenciones) + `docs/architecture.md` con el detalle profundo, referenciado.

### 25. Documentación desincronizada
README dice "363/363 tests" (hoy: 1 falla y hay 377 recolectables), STRUCTURE.md no menciona `server/` ni `web/` (la parte más nueva e importante), y dice que los profiles están en `data/profiles/` cuando están en `profiles/`.

---

## Plan sugerido (orden de ataque)

| Fase | Items | Esfuerzo |
|------|-------|----------|
| 1. Quick wins | 1, 3, 4, 5, 6, 20, 21 | ~½ día |
| 2. Higiene repo | 22, 23, 24, 25 | ~½ día |
| 3. UIDs de clips | 2 | 1 día (con migración + tests) |
| 4. De-duplicación | 7, 8, 9 | 1 día |
| 5. Rendimiento | 12, 13, 14 | 1 día |
| 6. Logging + recursos | 17, 18 | 1 día |
| 7. Core agnóstico + split del editor | 10, 11, 19 | continuo |
| 8. Retirada total del editor Qt | 26 | ~½ día |

Las fases 1-2 no tocan comportamiento y dejan la suite en verde. La 3 es la de mayor riesgo (protocolo JSON-RPC) — hacerla aislada y con tests de compat.

---

## Fase 8 — Retirada total del editor Qt (decisión del usuario, 2026-06-12)

Decisión: el editor PyQt5 se ELIMINA del repo (no solo se congela). Sustituye al "split del
editor" del hallazgo 19, que queda CANCELADO (no se trocea código que se borra).

**Contexto**: el código Qt no ralentiza la app web en ejecución (`server/main.py` nunca importa
`src/ui/`), pero sí cuesta: PyQt5 en requirements (instalación pesada), ~7.700 LOC de
mantenimiento, y confusión sobre cuál es el camino soportado. Verificado (2026-06-12): PyQt5
solo se importa en `src/ui/*`, `src/utils/shortcuts.py`, `src/viewer3d/viewer3d_server.py` y un
import perezoso en `mcp_bridge.py:~1487` (rama Qt de `_qt_call` que el camino headless no ejecuta).
Fuera de `src/ui/`, solo `tests/test_timeline_waveform.py` importa `src.ui` (el módulo Qt-free
`waveform.py`).

### 26. Pasos

1. **Checkpoint**: commit limpio + tag `pre-qt-removal` (rollback trivial).
2. **Borrar**: `src/ui/` completo, `src/utils/shortcuts.py` (solo Qt), y
   `src/viewer3d/` (server 3D del modo Qt; la web sirve el viewer desde `web/public/v3d/`).
   Revisar si `viewer3d/` raíz aún existe como residuo y borrarlo también.
3. **Decidir `waveform.py`**: si ningún código web lo consume, borrar junto con
   `tests/test_timeline_waveform.py`; si se prevé usarlo para pintar waveform en el server,
   moverlo a `src/core/` o `src/analysis/` (es Qt-free).
4. **mcp_bridge.py**: eliminar la rama Qt de `_qt_call`/`_qt_call_dual` (el import perezoso de
   QTimer y el marshalling); queda solo la política headless (`_qt_call_impl` de ShowSession).
   Revisar los shims `_NullView`/`_NullProps` de `server/session.py` por si se simplifican.
5. **requirements.txt**: quitar `PyQt5==5.15.9`.
6. **Launchers**: borrar `launch_show_designer.bat` si lanza `dual_app.py`; verificar que
   `Luces.bat` / `Luces Espana.bat` / `Cerrar Luces.bat` solo usan `server.main`.
7. **Docs**: actualizar CLAUDE.md (quitar entry point legacy y la decisión de retirada — ya
   ejecutada), README, STRUCTURE.md, docs/ (ui-guide), y este archivo (marcar 11, 19 y 26).
8. **Verificar**: `pytest tests/` en verde; arrancar `python -m server.main` y comprobar las
   4 vistas + viewer 3D + MCP compat :9876.

**Nota**: borrar del working tree no encoge el repo git (el historial conserva los archivos).
Suficiente con el borrado normal; no hace falta reescribir historial.
