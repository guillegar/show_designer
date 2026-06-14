# CLAUDE.md

Guía para Claude Code al trabajar en este repo. **Documento de retoma lean**: arquitectura,
estado vivo y convenciones. El detalle histórico profundo (changelogs, tabla de decisiones,
errores famosos, API MCP) está en **`docs/advanced/project-history.md`**. El layout del repo,
en **`STRUCTURE.md`**. La auditoría técnica, en **`ANALYSIS.md`**.

> ⚠️ **REGLA PERMANENTE (el usuario lo pidió):** al hacer cambios, **actualiza siempre la
> documentación** para que refleje el estado real — este `CLAUDE.md` (arquitectura/estado) y los
> docs de `docs/` que apliquen. No dejar la doc desfasada.

Estado a **2026-06-14** · **v2.0 · 918 tests · ROADMAP v2+v3 COMPLETOS · ROADMAP v4 I1+I2+I3+I4+I5 APLICADAS** — backend headless + frontend React, 4 vistas funcionando.
**A1+A2+A3+A4+A5+B1+B2+B3+B4+C1+C2+C3+D1+D2+E1+E2+E3+E4+F1+F2+F3+F4+G1+G2+G3+G4+H1+H2+H3+H4+I1+I2+I3+I4+I5 APLICADAS (2026-06-12/14)**: modulación + automatización + patterns + editor de detalle + ergonomía de composición + waveform en timeline + mixer master/cadena por pista + render offline + playback baked + autosave y versiones + performance grid + macros en vivo + soporte MIDI + auto-VJ por reglas + análisis en vivo + cues profesional + OSC I/O + export video preview + test de output y patch visual + 10 efectos built-in nuevos + plugin UI auto-generada + presets curados + live preview inspector + sACN E1.31 + sync de tempo BPM + salida DMX USB directa + SDK de plugins + instalador Windows + multi-show quick-switch + rendimiento a escala + grabación en vivo de macros + marcadores de timeline + grupos colapsables + vista arranger + exportación PDF/CSV. **Bloque B COMPLETO. Bloque C COMPLETO. Bloque D COMPLETO. Bloque E COMPLETO. Bloque F COMPLETO. Bloque G COMPLETO. Bloque H COMPLETO.**
  - ✅ **I5 APLICADA (2026-06-14, ROADMAP v4)**: Exportación PDF patch + CSV DMX.
    `server/timeline_export.py`: `export_patch_pdf` (fpdf2 o txt fallback; escritura
    atómica via `.tmp → replace`) + `export_dmx_csv` (reutiliza render.npz si existe,
    compute_frame on-the-fly si no; una fila/frame; t_ms,universe,ch_1..ch_512).
    Handlers `export_patch_pdf` y `export_dmx_csv` en `_LOCAL`. Live.tsx RenderPanel:
    botones "📄 PDF Patch" + "📊 CSV DMX" con indicador de ruta al completar.
    8 tests en `test_timeline_export.py`. **918 tests verdes.**
  - ✅ **I4 APLICADA (2026-06-14, ROADMAP v4)**: Vista Arranger — strip sobre la tira de lanes
    con secciones como bloques coloreados (calculadas desde markers I2). Botón "⊞ Arr" en
    toolbar. Drag horizontal de bloque → `duplicate_range` + `delete_range` (reordena sección).
    Doble-clic en bloque → scrollea al inicio de la sección. `.tl-arranger`, `.arr-block`,
    `.arr-drop-line`. Backend: `_h_delete_range` (borra clips que se solapan con el rango,
    invariante I1). 7 tests en `test_arranger.py`. **910 tests verdes.**
  - ✅ **I3 APLICADA (2026-06-14, ROADMAP v4)**: Grupos colapsables en timeline. `collapsedGroups:
    Set<string>` persistido en localStorage; `toggleGroupCollapse`. `lanes` useMemo computa grupo
    primario por barra (primera aparición en `groups`), inserta `group-header` al cambiar de grupo
    e inserta `group-collapsed` (una fila) si el grupo está colapsado en lugar de las barras
    individuales. `tl-heads`: cabecera ▶/▼ + nombre de grupo; fila colapsada con total de barras.
    `tl-lanes`: separador visual con color del grupo; miniatura SVG de clips (`gClips` por barra en
    el grupo). CSS: `.tl-group-hdr`, `.tl-grp-sep`, `.tl-grp-toggle`, `.tl-group-col`. Backend:
    `get_group_clips(group_name)` en `_LOCAL` del dispatcher. TS corregido (`clipsForLane` +
    `openLaneMenu` narrowing). 5 tests en `test_groups_collapse.py`. **903 tests verdes.**
  - ✅ **I2 APLICADA (2026-06-14, ROADMAP v4)**: Marcadores de timeline con nombre, color y
    categoría. `Marker` dataclass en `timeline_model.py` (`t_ms`, `name`, `color`, `category`);
    serializado en `show.json` (migración tolerante). `Timeline.markers` en
    `get_extra`/`restore_extra` del UndoManager (I1). Handlers `list_markers`, `add_marker`,
    `delete_marker`, `update_marker` en `_LOCAL` del dispatcher; mutadores en
    `_TIMELINE_MUTATORS`. Frontend: filtro de categoría en toolbar; edición inline de nombre
    (clic → input); menú clic-derecho con color picker + categoría + borrar. 8 tests en
    `test_cue_points_v2.py`. **893 tests verdes.**
  - ✅ **I1 APLICADA (2026-06-14, ROADMAP v4)**: Grabación en vivo de macros. `session.py`: estado
    `_recording/_record_start_ms/_recorded_lanes/_record_last_ms`; `_maybe_record_macros(t_ms)` con
    throttle 50ms (max 1 punto/50ms por macro) llamado al final de AMBAS rutas de `compute_frame` (live
    y baked); normalización brightness→v/2, speed→v/4, hue→(v+180)/360, strobe→v/30; `automation` añadido
    a `get_extra`/`restore_extra` del UndoManager (I1: undo revierte lanes). `dispatcher.py`: 3 handlers
    `start_record`/`stop_record`/`get_record_state`; `stop_record` llama `snapshot()` antes de crear lanes
    y usa `invalidate_caches()`. `tick.py`: evento `record_state` cada ~500ms durante grabación. `stream.ts`:
    `RecordStateEvent` + `onRecordState()`. `Live.tsx`: botón ⏺ REC / ⏹ STOP REC en `MacroStrip` (parpadeo
    rojo CSS); toast con número de lanes al parar; `ToastContainer`. 8 tests en `test_macro_record.py`.
    **885 tests verdes.**
  - ✅ **H4 APLICADA (2026-06-14)**: Rendimiento a escala. `tests/test_bench_scale.py` (6 benchmarks marcados `@pytest.mark.bench`): `to_dict` 5000 clips < 200 ms, `from_dict` 5000 clips < 200 ms, `list_clips` handler 5000 clips < 500 ms, `compute_frame` p95 < 60 ms con 200 clips activos, sin leaks > 1 MB tras 100 frames (`tracemalloc`). Paginación añadida: `_h_list_clips` en `_LOCAL` del dispatcher (prioridad sobre bridge) con `offset`/`limit` → `{clips, total, count, next_offset}`. **883 Python verdes.**
  - ✅ **H3 APLICADA (2026-06-13)**: Multi-show quick-switch. `ShowSession.switch_project(slug)` async: para playback, autosave inmediato, carga nueva timeline/audio/analysis, resetea estado runtime (baked, cues, live engine, identifies), emite `project_changed` al stream. Handlers: `list_projects` (lista proyectos + current), `switch_project` (lanza tarea async). Frontend: `ProjectSwitcher` dropdown en topbar (solo si hay >1 proyecto), overlay spinner durante el cambio, `stream.onProjectChanged` → `refreshAll()`. Tipo `ProjectChangedEvent` en stream.ts. 8 tests en `test_switch_project.py`. **877 Python verdes.**
  - ✅ **H2 APLICADA (2026-06-13)**: Instalador Windows. `showdesigner.spec` (PyInstaller --onedir, empaqueta web/dist + plugins + gdtf_profiles). `scripts/build_installer.ps1` (1. npm run build, 2. pyinstaller, 3. iscc opcional). `ShowDesigner.iss` (Inno Setup 6). `Luces.bat` detecta `ShowDesigner.exe` (modo frozen) vs `venv311` (modo desarrollo). 6 tests en `test_build.py`. **869 Python verdes.**
  - ✅ **H1 APLICADA (2026-06-13)**: SDK de plugins público. `tests/plugin_test_harness.py`: `assert_valid_plugin_effect()` verifica shape, dtype, rango [0,255], inmutabilidad de `bars_state`, coherencia de `PARAM_SCHEMA`. `plugins/effects/plugin_template.py`: plantilla con comentarios en cada campo. `docs/dev/plugin-sdk.md` actualizado con referencia al harness. 5 tests en `test_sdk_harness.py`. **863 Python verdes.**
  - ✅ **G4 APLICADA (2026-06-13)**: Salida DMX USB directa (ENTTEC Open DMX). `DmxUsbTarget` en `src/io/outputs/router.py` — framing ENTTEC (BREAK + START CODE 0x00 + 512 bytes) a 250 kbaud 8N2 con `pyserial`. Import lazy, error de puerto no lanza (log + no-op). `list_ports()` via `serial.tools.list_ports`. `OutputRouter.load()` reconoce `"type": "dmx_usb"`. Handlers: `list_dmx_ports`, `set_output_target` (actualiza output_targets.json + recarga router en engine). Frontend: `DmxUsbPanel` plegable en Patch.tsx con selector de puerto COM, campo universo y botón Aplicar. `pyserial>=3.5` en requirements.txt. 8 tests en `test_dmx_usb.py` (mock sin hardware real). **858 Python verdes.**
  - ✅ **G3 APLICADA (2026-06-13)**: Moving heads pan/tilt en el timeline. `PanTiltWaveEffect` en `src/core/channel_effects.py` (modes circle/fig8/bounce_pan/bounce_tilt, params F2-compatible). `channel_effects: List[Dict]` en `Clip.to_dict/from_dict` para múltiples sub-efectos por clip; `_render_clip_channels` renderiza la lista con fusión (LAST_WINS). ADR-004 (LTP mixing policy). Handlers: `list_channel_effects`, `set_clip_channel_effect`, `delete_clip_channel_effect`, `get_fixture_pan_tilt`. Frontend: tab "Movimiento" en ClipInspector con SVG preview 2D de trayectoria, selector de modo y sliders (speed/pan_range/tilt_range). 12 tests en `test_mover_effects.py`. **850 Python verdes.**
  - ✅ **G2 APLICADA (2026-06-13)**: Ableton Link / MIDI Clock sync de tempo. `server/tempo_sync.py`: `TempoSyncService` (mode off/link/midi_clock, `bpm`, `beat_phase`). `_calc_bpm()` pura testeable (mediana de inter-pulse intervals). Hilo de fondo para Link (`pylinkbpm`) y MIDI Clock (`mido`), imports opcionales con fallback limpio. `session._get_audio_context` inyecta `bpm` del sync cuando activo (copia shallow, no muta cache). Stream: campo `tempo_sync` en mensajes `state`. Frontend: `SyncPanel` en Live.tsx — BPM en tiempo real, selector Off/Link/MIDI Clock, dropdown de puertos MIDI, chip de estado. 3 handlers: `tempo_sync_get_state`, `tempo_sync_set_mode`, `tempo_sync_list_midi_ports`. 12 tests en `test_tempo_sync.py`. **838 Python verdes.**
  - ✅ **G1 APLICADA (2026-06-13)**: sACN (E1.31) como protocolo adicional. `SacnNodeTarget` en `src/io/outputs/router.py` — unicast o multicast, `sACNsender` instanciado una vez, `activate_output()` lazy por universo, `close()` limpio. `OutputRouter.load()` reconoce `"type": "sacn"` en `output_targets.json`. `sacn>=1.6` en requirements.txt. 9 tests en `test_sacn.py` (mock sin red real). **826 Python verdes.**
  - ✅ **F4 APLICADA (2026-06-13)**: Live preview en el inspector. Handler `preview_effect_frame(effect_id, params, t_ms)` en `_LOCAL` del dispatcher — llama a `effect.render()` con `bars_state` sintético, devuelve PNG base64 (scale 2×, Pillow). Fallback `LUCES_NO_PILLOW=1` → `frame_raw` JSON. `ClipInspector.tsx`: miniatura animada + slider t_ms (0-2000ms), `fetchPreview` con debounce 200ms + `useCallback`. CSS: `.preview-section`, `.preview-tms-row`. 7 tests en `test_preview_effect.py`. **816 Python verdes.**
  - ✅ **F3 APLICADA (2026-06-13)**: Biblioteca de presets curados. 30 presets (3 por cada efecto F1, IDs 1010-1019) en `_seed_f3_effects()` dentro de `server/presets.py`. Migración automática en `PresetBank._load()` — añade F3 a instalaciones existentes sin borrar nada. `EffectPreset` ampliado con `param_links: List[dict]` (A1 links preconfigurados). "Pulso Ámbar" (breathing) incluye `param_links=[{rate_hz←rms}]`. `_h_list_presets` acepta `effect_id` opcional para filtrar. `_h_set_clip_preset` propaga `param_links` del preset al clip. ClipInspector: sección "Presets sugeridos" (3 chips con color, clic aplica preset). 12 tests en `test_preset_library.py`. **809 Python verdes.**
  - ✅ **F2 APLICADA (2026-06-13)**: Plugin UI auto-generada. `PARAM_SCHEMA: ClassVar[Dict[str,dict]] = {}` en la clase base `Effect`. Los 14 efectos (10 F1 + 4 plugins existentes) definen su schema completo. `validate_params_against_schema` en `server/validators.py` — integrado en `set_clip_effect` y `set_clip_preset`. Handler `get_effect_schema(effect_id)` registrado en `_LOCAL`. `ClipInspector.tsx` genera controles dinámicos: slider+número (float/int), color picker agrupado (detecta triplets r/g/b), toggle (bool), select (enum), texto genérico (sin schema). `web/src/api/schema.ts`: `hexToRgb`, `rgbToHex`, `detectColorGroups`. `docs/dev/plugin-sdk.md` creado. 22 tests Python + 9 Vitest. **798 Python verdes · 30 Vitest verdes.**
  - ✅ **F1 APLICADA (2026-06-13)**: 10 efectos built-in nuevos en `plugins/effects/` (IDs 1010-1019): `gradient_sweep` (gradiente barrido), `pixel_chase` (punto con estela gaussiana), `theater_chase` (marquesina grupos alternos), `twinkle` (destellos aleatorios reproducibles), `fire` (simulación llama Fire2012), `strobe_color` (estrobo con duty cycle), `vu_meter` (barra VU reactiva RMS + peak hold), `rainbow_wave` (arcoíris vectorizado), `scanner` (spot gaussiano oscilante vectorizado), `breathing` (fade senoidal, opcionalmente audio-reactivo). Estado entre frames vía instancia (`_heat`, `_last_frame`, `_phases`, `_smooth_level`). 44 tests nuevos en `test_effects_nuevos.py`. **776 verdes.**

---

## 0. TL;DR

- 🗺️ **ROADMAP v2 COMPLETO (2026-06-13): `ROADMAP.md`** — "El Secuenciador" (nivel FL
  Studio): 15 fases en 4 bloques (Composición/Show/Directo/Impro). Tag: `v1.10-roadmap-v2`.
  700 tests verdes. Invariantes I1-I5 respetados en todas las fases.
  - ✅ **E4 APLICADA (2026-06-13, ROADMAP v3)**: test de output y patch visual. `session.blackout_override` (bool, no muta mixer), `session._identify` (dict fixture_id→t_expires), `session._test_universes` (dict universe→(r,g,b)). Handlers: `identify_fixture` (blanco 2 s, auto-off asyncio), `test_universe` (toggle universo con color), `blackout` (override instantáneo, evento stream `blackout_changed`), `get_output_status` (estado unificado). `FixtureTestPanel` en Patch.tsx: mapa de barras con 🔦 Identify + 🎨 Test + color picker. BLACKOUT toggle grande en cabecera del panel. 8 tests nuevos. **732 verdes.**
  - ✅ **E3 APLICADA (2026-06-13, ROADMAP v3)**: export video preview. `server/video_export.py` (NEW): `export_preview(npz_path, out_path, format, scale, fps, progress_cb)` — GIF siempre (Pillow), MP4 si ffmpeg en PATH, atomic write, np.kron para escalar. Handler `export_video` con executor (I4) + eventos `{type:'export_progress', pct}`. `_h_get_render_status` ampliado con `has_ffmpeg` y `render_ready`. `RenderPanel` en Live.tsx con botones 🎞 GIF / 🎬 MP4 y aviso "requiere ffmpeg". Pillow añadido a requirements.txt. 5 tests en test_video_export.py.
  - ✅ **E2 APLICADA (2026-06-13, ROADMAP v3)**: OSC entrada y salida. `server/osc_bridge.py`
    (NEW): `OscBridge` — AsyncIOOSCUDPServer IN (8001) + SimpleUDPClient OUT (8002).
    Handlers IN: /show/go_cue, /show/goto_t, /macro/brightness, /macro/strobe, /live/trigger,
    /live/stop_all. Emisión OUT throttled ≤10 Hz: /show/t_ms, /show/section, /show/beat,
    /show/rms. Config en output_targets.json["osc"] (atómico). 2 handlers: osc_get_state,
    osc_set_config. OscPanel plegable en Patch.tsx. python-osc en requirements. 8 tests.
    **719 verdes** (+ bench flaky load-dependent).
  - ✅ **E1 APLICADA (2026-06-13, ROADMAP v3)**: sistema de cues profesional. `CueEntry`+`CueList`
    en `timeline_model.py` (schema v4, migración tolerante v3→v4). `go_cue`/`go_next_cue`/`go_prev_cue`
    + fade frame-a-frame en `compute_frame` (ambas rutas) + auto-follow `asyncio.create_task`.
    `cue_changed` stream event throttled >1%. 9 handlers en dispatcher. `CuesPanel` en `Live.tsx`
    (GO/PREV/NEXT + barra de fade + lista). Space → go_next_cue. 10 tests nuevos. **711 verdes.**
  - ✅ **F0 APLICADA (2026-06-12)**: actx real, param_pipeline (stages), schema v3, ADRs. 448→495 verdes.
  - ✅ **A1 APLICADA (2026-06-12)**: modulación (`brightness ← rms`). ParamLink, ModulationStage, actx['norm'].
    25 tests. Regresión ~5% (I5).
  - ✅ **A2 APLICADA (2026-06-12)**: automatización (curvas). AutomationLane, shapes (linear/hold/smooth).
    Handlers `add_automation_lane`, `delete_automation_lane`, `set_automation_points`. 23 tests.
  - ✅ **A3 APLICADA (2026-06-12)**: patterns (bloques reutilizables). Pattern+PatternInstance
    en timeline_model.py. Expansión efímera cacheada (_pattern_rev). UndoManager extendido con
    get_extra/restore_extra (invariante I1). 9 handlers: `create_pattern_from_clips`,
    `add/move/delete_pattern_instance`, `update/delete_pattern`, `list_patterns`,
    `list_pattern_instances`, `dissolve_instance`. Frontend: tab Patterns en Browser, render de
    instancias en Timeline, applyPatternMovesOptimistic. 39 tests. 534 verdes.
  - ✅ **A4 APLICADA (2026-06-12)**: editor de detalle del clip. `MicroEvent` + `MicroEventStage`
    (src/core/micro_events.py, fast path si clip.events vacío). `Clip.events` en timeline_model.
    3 handlers: `add/delete/update_micro_event`. `ClipDetailModal` (Alt+dblclick): beat grid,
    micro-eventos SVG arrastrables, curvas de automatización editables (A2 deferred aquí).
    23 tests. 557 verdes. Bench +3.5% (dentro I5).
  - ✅ **A5 APLICADA (2026-06-13)**: ergonomía de composición. Fix TS `presets` en Timeline.tsx.
    `tlScrollRef` adjuntado a `tl-scroll`; scroll sync ruler↔tracks (translateX). `rulerRef`.
    Botones Ghost (◈) + Quantize (⊹ Q) en toolbar. Menú contextual en regla → "Duplicar sección X
    → aquí" llama `duplicate_range`. 1 test nuevo (`test_duplicate_range`). 558 verdes.
  - ✅ **B1 APLICADA (2026-06-13)**: waveform en el timeline. `_h_get_waveform` en
    `server/dispatcher.py` — librosa + 8000 buckets (min/max/rms) cacheados en
    `analizadas/<slug>/waveform.json` (atómico). Frontend: `<canvas>` absoluto en `tl-ruler`,
    redibuja por píxel al cambiar zoom, estado lazy (`showWaveform`). Botón `≋ WF` en toolbar.
    4 tests nuevos (`test_waveform.py`). 562 verdes.
  - ✅ **B2 APLICADA (2026-06-13)**: mixer master + cadena por pista. `src/core/postfx.py`
    (`apply_track_chain`, `apply_master`) — numpy vectorizado, fast path (identity = sin alloc).
    Integrado al final de `session.compute_frame` (orden fijo: timeline_render → postfx/master).
    Handlers `set_track_chain`, `set_master`, `get_mixer` en dispatcher. Mixer en undo (I1).
    Panel Mixer plegable en `Live.tsx`: sliders brightness por pista + M/S + strip master con
    `blackout_fade` (animable con A2 gratis). 20 tests nuevos (`test_postfx.py`). 582 verdes.
  - ✅ **B3 APLICADA (2026-06-13)**: render offline + playback baked. `server/offline_render.py`:
    `_render_worker` síncrono en executor (I4), copia congelada (`Timeline.from_dict(to_dict())`),
    hash MD5 para invalidación, guardado atómico. `Timeline.to_dict()` + `from_dict()` añadidos.
    Sesión: `baked_frames`, `baked_hash`, `render_in_progress`, `hub`. `load_baked_frames()`.
    `invalidate_caches()` + `invalidate_pattern_cache()` invalidan baked. `compute_frame` usa baked
    + aplica postfx/master sobre el frame bakeado. Handlers: `render_offline`, `get_render_status`,
    `toggle_baked`. Progress events `{type:'render_progress'}` en el stream (thread-safe).
    Frontend: `RenderPanel` en `Live.tsx` con botón Render + barra progreso + toggle Baked + aviso
    invalidación. `onRenderProgress` en `StreamClient`. 11 tests nuevos. 593 verdes.
  - ✅ **B4 APLICADA (2026-06-13)**: autosave + versiones de show. **Bloque B COMPLETO.**
  - ✅ **C2 APLICADA (2026-06-13)**: macros en vivo. `MacroStage` en `src/core/param_pipeline.py`
    (4º stage, fast path si brightness_mul==1.0 y speed_mul==1.0). 4 macros: `brightness_mul`
    (0..2), `speed_mul` (0..4), `hue_shift` (-180..180), `strobe_rate` (0..30 Hz). Estado live
    en `session.macros` (no persiste en show.json). `hue_shift` sumado al master antes de
    `apply_master` (sin mutar el dict del timeline). Strobe al final de `compute_frame` (ambas
    rutas: live y baked). Handler `set_macro` con validación de nombre y rango.
    `MacroStrip` en `Live.tsx`: 4 sliders con throttle, doble clic = reset, botón Reset all.
    9 tests nuevos. **628 verdes.**
  - ✅ **C3 APLICADA (2026-06-13)**: soporte MIDI (Web MIDI API). **Bloque C COMPLETO.**
    `web/src/api/midi.ts`: funciones puras `parseMidiKey`/`scaleCCToMacro` + `initMidi` async
    con handle degradado limpio. Note On/Off → `live_trigger`/`live_release`. CC → macros
    (lerp al rango del knob). MIDI Learn: toggle en MidiPanel, clic en slot/macro → toca
    control → queda mapeado. Mapa en localStorage `"show_designer_midi_map"` (independiente
    del show.json). `MidiPanel` plegable: estado/dispositivos/tabla/export/import JSON.
    `MacroStrip` refactorizada a controlada (estado elevado a `LiveView`). CERO cambios de
    backend. 15 tests nuevos Vitest. **700 verdes (incluyendo D1+D2). Bloque D COMPLETO. ROADMAP v2 COMPLETO.**
  - ✅ **D1 APLICADA (2026-06-13)**: Auto-VJ por reglas.
    `src/core/autovj.py`: Rule, RuleSet, AutoVJEngine, _EphemeralSlot (duck-typed, sin imports
    de server/). Triggers: on_beat/on_downbeat (±20ms searchsorted), on_kick (proxy norm),
    on_section_change, signal_above (histéresis thr_off=thr×0.8). Actions: fire_effect (pattern
    efímero + slot en live._active), fire_pattern (slot 15 reservado). Presets: FIESTA/CHILL/TECHNO.
    Integrado en `session.compute_frame` antes de `live_engine.compute_live_frame`; pasa
    `timeline.patterns + _ephemeral_patterns` (cero duplicación C1). Persistencia: autovj.json
    atómico, auto-carga al arrancar. 6 handlers en dispatcher: `autovj_get/set_ruleset`,
    `autovj_activate_preset`, `autovj_update_rule`, `autovj_save/load`. 40 tests nuevos.
    668 verdes.
  - ✅ **D2 APLICADA (2026-06-13)**: Análisis en vivo (entrada de audio). **Bloque D COMPLETO.**
    `server/live_input.py`: `LiveInput` (captura sounddevice, ring buffer con deque maxlen,
    detección de onset por umbral EMA + cooldown _ONSET_GAP_MS=150ms, estimación BPM por
    mediana de IOI + EMA α=0.8, beats sintéticos con fase del onset más reciente).
    Interfaz compatible con AnalysisService: `list_beats`, `list_downbeats`, `section_at`
    (siempre None), `get_audio_context` (rms/flux/norm; siempre el frame más reciente).
    `session.live_input`, `session._live_mode`: toggle D2 en `_get_audio_context` y en
    D1 `evaluate` (se pasa `live_input` como analysis cuando `_live_mode=True`).
    4 handlers: `live_input_list_devices`, `live_input_start`, `live_input_stop`,
    `live_input_get_state`. Tests sin HW real: `_process_block()` inyectable con PCM
    sintético (click-tracks numpy). 32 tests nuevos. **700 verdes. Bloque D COMPLETO.**
  - ✅ **C1 APLICADA (2026-06-13)**: performance grid (lanzar patterns en vivo). `server/live_engine.py`:
    `LiveSlot` (config: pattern_uid, key, quantize, mode) × 16 slots + `LiveEngine` (runtime: `_active`,
    `_armed` dicts, `compute_live_frame`). Cuantización bar/beat/free con degradación automática a free
    si no hay beats. 5 handlers: `live_assign_slot`, `live_trigger`, `live_release`, `live_stop_all`,
    `get_live_state`. `live_slots` persistido en show.json (migration-tolerant). Invariante I1 (undo
    cubre slots), I2 (cascade clearing al borrar pattern). Stream event `live_state_changed`. Frontend:
    `PerformanceGrid` (grid 4×4, teclas 1-8/Q-I, STOP ALL, modal de config, badge FREE). 11 tests.
    **619 verdes.**
    `server/session.py`: `autosave_now()` (atómico vía `Timeline.save()`), `_rotate_autosaves()`
    (máx 20 archivos), `start_autosave_task()` (asyncio, cada `LUCES_AUTOSAVE_INTERVAL` s, default
    60), `check_autosave_at_startup()` (mtime comparison, una vez por arranque).
    `server/web.py`: tarea de autosave + `_emit_autosave_banner` (delay 1.5 s).
    Handlers: `list_autosaves`, `restore_autosave` (path traversal bloqueado), `discard_autosave_prompt`.
    `stream.ts`: tipo `AutosaveAvailableEvent` + `onAutosaveAvailable()`.
    Frontend: `AutosaveBanner` (top-center, una sola vez), botón "Versiones…" + `VersionesModal`
    (tabla fecha/tamaño + "Cargar como copia"). 15 tests nuevos. **608 verdes.**

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
- ✅ **Fase 9 (bug UX, 2026-06-12) APLICADA: "el clip no se queda al soltarlo".** Síntoma real
  (aclarado por el usuario): el drag SÍ funciona, pero al soltar el clip volvía a su sitio. La
  hipótesis estática del "doble gesto" (stopPropagation) era FALSA — reproducido en vivo, la
  delegación Selecto→Moveable y `move_clip` siempre funcionaron. Causa raíz: **NO había update
  optimista** → al soltar se limpiaba el `transform` y el clip se quedaba en su `left` viejo
  ~456 ms hasta que terminaba el round-trip `move_clip→snapshot→refreshClips`. Fix (frontend):
  update optimista del store + **pin imperativo** (`pinClipEl`, reusa `msToX`) que fija el clip al
  instante sin esperar el re-render de ~1.3k clips + guardia `draggingRef` (no reconstruir targets
  a mitad de gesto) + token monótono en `refreshClips`. Verificado en vivo (:8000): drop instantáneo
  en X; `tsc` limpio, build OK, **432 verde**. Detalle en `ANALYSIS.md` → hallazgo 27.

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
- **Drop OPTIMISTA (Fase 9, NO romper):** al soltar, `commitMoves` parchea el store (`applyMovesOptimistic`)
  y `pinClipEl` fija el clip imperativamente (left/top/width, reusando `msToX`) ANTES del round-trip,
  para que se quede donde se suelta sin esperar a `move_clip→snapshot→refreshClips` ni al re-render de
  ~1.3k clips. `refreshClips` reconcilia después (con token monótono para descartar respuestas viejas).
  `draggingRef` evita reconstruir `moveTargets`/`updateRect` a mitad de gesto. Si tocas el commit, NO
  vuelvas a depender solo del round-trip o reaparece el "no se queda al soltar".
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
