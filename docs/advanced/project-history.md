# Historia y detalle profundo del proyecto

> Compañero de `CLAUDE.md` (que se mantiene lean). Aquí vive el detalle histórico que NO
> hace falta cargar en cada sesión: changelogs v1.0→v1.9, tabla completa de decisiones de
> diseño, errores famosos y sus fixes, y la referencia de la API MCP. Consultar bajo demanda.

---

## Decisiones tomadas (y el porqué)

| Decisión | Por qué |
|----------|---------|
| **Python puro, sin Chromium embedido, sin daemons** | Stack simple; el viewer 3D vive en el navegador del usuario, no embedido. |
| **Art-Net puro como output principal** | Ya funcionaba con WLED + Art-Net→DMX node. sACN/OLA añaden complejidad sin ganancia inmediata. |
| **MCP por WebSocket interno + stdio externo** | Permite separar la app Qt (event loop principal) del proceso MCP que Claude Code lanza. El bridge JSON-RPC desacopla los dos. |
| **FastMCP en thread separado con `run_coroutine_threadsafe`** | FastMCP corre su propio asyncio loop; necesitamos un loop secundario en thread daemon para nuestras llamadas RPC. Si no, "Cannot run the event loop while another loop is running". |
| **`_qt_call(app, fn)` con `QTimer.singleShot(0, fn)`** | Las mutaciones de modelo desde MCP llegan en el thread del WebSocket. QTimer.singleShot(0) las marshalla al thread de Qt sin bloquear. (v1.10: en headless la política la provee la sesión vía `_qt_call_impl`.) |
| **Único `ShowEngine` compartido entre tabs** | Antes había 2 ShowEngines → 2 streams UDP a las mismas IPs (LEDs parpadeaban raro). `dual_app._share_show_engine()` cierra el socket del feedback y reusa el del timeline. |
| **Render unificado: timeline calcula el frame, todos lo pintan** | Evita dos cómputos paralelos. `_link_renders()` reconecta el `render_timer` del timeline a un `shared_tick` que pinta timeline + feedback + broadcast 3D + envía Art-Net. |
| **Idle FPS reducido a 10 Hz** | Cuando nada se reproduce, no hay razón para 30 fps. Ahorra CPU del usuario. |
| **`rig_layout.json` auto-generado** | Single source of truth = `fixtures.json` (FixtureRig). El layout JS lo deriva. |
| **MovingHead JS escrito desde cero** | Implementación original propia. Arquitectura base→yoke→head→beam con fresnel + falloff en shaders. Three.js (MIT) como única dependencia de render. |
| **Shader beam: fresnel + `min(a, 1.0)` en alpha** | Con AdditiveBlending y DoubleSide, los dos lados del cilindro hueco acumulan luminosidad. Sin clamp en RGB (ACES tonemapping comprime), sí clamp en alpha. |
| **Bars: body BEHIND LEDs + LEDs ligeramente más grandes** | Antes los LEDs estaban dentro del body opaco y no se veían. Ahora `body.position.z = -bodyDepth` y LEDs `0.95×` body. |
| **Movers responden a DMX real desde v1.7 Fase 4** | `get_fixture_dmx_states()` lee `manual_channels` de cada fixture no-LED y los broadcast al viewer 3D cada tick. Patch panel sliders → mover gira en tiempo real. |
| **ChannelEffect puro: t+ctx+params→dict** (v1.7 F6) | Mismo principio que los pixel effects: sin Qt, sin red, sin rig. `_render_clip_channels()` los llama lazy. Facilita tests y catálogo ampliable sin tocar show_engine. |
| **track=-1 para channel clips** (v1.7 F5) | Clips de canal (category!='pixel') usan track=-1. La UI del timeline no los renderiza, y el motor los filtra por scope='fixture:<id>'. |
| **Prosperity Public License 3.0.0 (PPL)** | Código original propio. Libre para uso personal/educativo; uso comercial requiere licencia. |
| **GDTF + JSON híbrido para profiles** (v1.7) | GDTF para fixtures comerciales (gdtf-share.com). JSON propio para WLED + genéricos + prototipos. Internamente UN solo `FixtureProfile`. El usuario: *"gdtf tiene que usar lo que dudo es si usar los json tambien o no"* → híbrido porque WLED no tiene GDTF natural. |
| **Categorías por capacidad, deducidas auto** (v1.7) | 6 categorías: pixel/position/color/intensity/optical/strobe. `FixtureProfile.supported_categories()` las deduce del `channel_map`. **Imposible** aplicar MoverCircle a una barra LED. El usuario: *"habria quee separar en efecto para cada tipo de fixure, no se puede aplicar movimiento a una barra"*. |
| **LTP por layers en mezcla de canales** (v1.7) | Cuando varios clips channel-level tocan el mismo canal, el de mayor `layer` gana. Coherente con el sistema RGB. |
| **Assembler+Router en paralelo al flujo legacy** (v1.7) | El show El Taser sigue por `send_frame()` viejo (10 WLED bit-exact). El assembler+router viven para tests + viewer 3D + movers reales. Zero riesgo de regresión. |
| **`output_targets.json` separado de `fixtures.json`** (v1.7) | El routing físico es responsabilidad del operador, no del diseñador del rig. Cambiar `{"11": {"type": "sim_only"}}` → `{"11": {"type": "artnet_node", "ip": "..."}}` sin tocar código. |
| **UTF-8 forzado a stdout/stderr en dual_app** | Windows console por defecto cp1252 → cualquier emoji o flecha (`→`) crashea `print()`. `sys.stdout.reconfigure(encoding='utf-8')` al inicio. |

---

## Errores famosos y sus fixes (para no volver a tropezar)

| Error | Causa raíz | Fix |
|-------|-----------|-----|
| `Cannot run the event loop while another loop is running` en mcp_show_server | FastMCP corre asyncio; llamar `asyncio.run()` dentro choca. | `_bg_loop` global + `asyncio.run_coroutine_threadsafe`. Ver `mcp_show_server.py:_ensure_bg_loop`. |
| `clear_cue` no limpiaba el cue | El handler delegaba en `app._clear_cue` que no existía con esa signatura. | Mutar el modelo directamente en `_h_clear_cue` y refrescar UI con `_qt_call`. |
| `list_fixture_profiles` → "Método desconocido" | dual_app corriendo con código viejo del bridge en memoria. | Reiniciar dual_app. **Regla**: cambios en `mcp_bridge.py` requieren restart de dual_app. |
| Puerto 9876/9877 ocupado (errno 10048) | Procesos python zombies. | `Get-Process python \| Stop-Process -Force`. |
| Beam shader casi negro | `vRadialT` siempre era 1 (vértices del cilindro al mismo radio). | Cálculo real de fresnel con `vWorldNormal` en el fragment. |
| Beams enterrados bajo el suelo | Beam length 14 m apuntando hacia abajo con tilt pequeño. | `tilt ∈ [62°, 67°]` + `beamLength = 7.5 m`. |
| "Los movers están pero apagados" | `wallAlpha` base muy bajo (0.18). | Subido a 0.55, eliminado el `discard` temprano. |
| "Los focos se ven pero las barras no" | LEDs renderizados dentro del body opaco. | Body desplazado en Z, LEDs ligeramente más grandes que body. |
| "La barra de tiempo del analyzer no avanza" | `shared_get_time()` devolvía 0 cuando la tab activa no era Timeline; `_on_tab_changed(idx>=2)` reseteaba audio; `print("→")` cp1252 crasheaba. | `shared_get_time()` prioriza el audio playing como master; `_on_tab_changed` retorna si `idx>=2`; `reconfigure(utf-8)`. |
| Encoding cp1252 en `print` con emojis/flechas en Windows | Console default no UTF-8. | `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` al inicio de `dual_app.py`. |
| **App se cierra sola (v1.9 F2)** | `_handle_client` en `mcp_bridge.py` solo capturaba `ConnectionClosed`. Conexiones TCP crudas al 9876 (Test-NetConnection, healthcheck Claude) lanzaban `InvalidMessage` DURANTE el handshake → mataba el thread daemon → race con Qt → app cerrada silenciosa. | `loop.set_exception_handler` con `_silenciables = (InvalidMessage, ConnectionResetError, EOFError, BrokenPipeError, OSError)`. Mismo fix en `viewer3d_server.py`. `logging.getLogger("websockets.*").setLevel(CRITICAL)`. `sys.excepthook` global en `dual_app.main()`. |
| **`Bar -1 L0 · #0` al seleccionar channel clip (v1.9 F2)** | `PropertiesPanel.set_clips` no distinguía pixel vs channel; cambiar el combo reescribía `effect_id`/`label` del channel clip → corrupción. | Rama temprana en `set_clips`: si `category != 'pixel'`, panel reducido con combo deshabilitado. |
| **Draw sin efecto creaba white_flash fantasma (v1.9 F2)** | `draw_effect_id` defaulteaba a 0 (WhiteFlash). | `draw_effect_id = None` por defecto + guard en `mousePressEvent`. |
| **App "no responde" al tocar una fixture lane (v1.9 F4)** | (a) `_draw_track_headers` usaba `fx.name` (no existe; es `fx.label`). (b) `sys.excepthook` sin throttle logueaba la misma excepción en cada repaint → stdout saturado. | (a) `fx.name`→`fx.label`. (b) Throttle de 2s por `(exc_type, filename, lineno)` en el excepthook. |

---

## Estado "Terminado" histórico (v1.0 → v1.7)

- **v1.0 checkpoint** (pre-MCP, 40 features). **MCP server completo** (~50 endpoints): transport,
  clips R/W, grupos, cues, markers, fixtures, analyzer (v1.6, 14 handlers), persistencia, viewer.
- **Show El Taser**: 8 cue points (`0, 52, 76, 86, 183, 193, 213, 218 s`), flashes cada 5 s en `bar_3`.
- **Viewer 3D Three.js**: bloom, fog, ACES tonemapping, OrbitControls, 10 LEDBar + 4 MovingHead (beam
  volumétrico con shader custom).
- **Patch Panel 2D top-down**, **Fixtures genéricos** (`FixtureProfile`+`Fixture`+`FixtureRig`),
  **auto-sync rig** → `rig_layout.json`. 14 fixtures (10 led_strip univ 1..10 + 4 moving_head univ 11).
- **Release v1.6 "Audio Brain"** (fases A/B/C/D): `analyzer_service.py` (`AnalysisService` schema v3 +
  migrador v1/v2→v3 + `Curation`), `analyzer_panel.py` (4ª tab con overlays), vocabulario híbrido de
  secciones, curación no destructiva, dtempo en `audio_context`, madmom fallback con bandera, 53 tests.
- **Release v1.7 "DMX Multi-Fixture"** (9 fases): 3 profiles nuevos, `gdtf_profile.py` (pygdtf),
  Universe Assembler + Output Router, viewer 3D con DMX real (`broadcast_dmx_state`, clase `Strobe`),
  Channel Editor en Patch (`Clip.category` + `Clip.channel_effect_id`), catálogo `channel_effects.py`
  (24 efectos en 5 categorías), 4 MCP tools de DMX, 48 tests → **151/151 verdes**.

## v1.8 "Generation + Multi-project + Polish" COMPLETA
- **F1**: 3 MCP generation tools (`generate_section`, `mirror_clips_lr`, `apply_palette_to_range`) + 36 tests.
- **F2**: Fixture lanes visuales en el timeline editor (lectura/selección/borrado).
- **F3**: Multi-proyecto — `projects/<slug>/` con auto-migración del legacy.
- **F4**: Plugin system — `plugins/effects/*.py` autodescubiertos (IDs ≥ 1000).
- **F5**: Exporters — QLC+ XML workspace + CSV de clips.
- **F6**: Tests CI — `.coveragerc`, `pytest.ini`, GitHub Actions, 92.6% cobertura. **353/353 verdes**.

## v1.9 COMPLETA
- **F1 — Drag-create de channel clips**: browser tabs Pixel/Channel, modo Draw bimodal, validación
  lane/effect-kind, crea Clips con `category`+`channel_effect_id`+`scope='fixture:<id>'`. 10 tests.
- **F2 (CRÍTICA) — Estabilización anti-crash**: el bug del bridge (ver "errores famosos"),
  `loop.set_exception_handler`, modo reducido para channel clips, `sys.excepthook` global. **363 verdes**.

## v1.10 "Migración a WEB"
Backend headless (`server/`) + frontend React (`web/`), 4 vistas, reutiliza `src/core|analysis|io|mcp`
sin cambios. Reloj maestro `HeadlessAudioPlayer`. Ver §0.5 de `CLAUDE.md`.

> **Fase 8 (2026-06-12): la UI PyQt5 se RETIRÓ del repo.** Todo lo de abajo sobre `dual_app`,
> `timeline_editor`, los paneles Qt, las 4 *tabs* y `viewer3d_server` (:8080) es **historia**: ese
> código ya no existe (borrados `src/ui/`, `src/utils/`, `src/viewer3d/`). La única UI es la web.
> Rollback de la retirada: tag git `pre-qt-removal`.

## Próximos bloques candidatos (post-auditoría)
- OSC support (TouchOSC/Lemur); editor de params de channel clips; MP4 export del viewer 3D;
  Live mode mejorado (cue panel, tap tempo, snapshots); stems demucs para El Taser; auto-show generator.
- Fuera de scope (el usuario lo dijo): **MIDI**, **sACN**. No reinventar lo que Three.js ya hace bien.

---

## Referencia API MCP (`mcp__show-control__*`)

> Tools deferred: **siempre** `ToolSearch(query="mcp__show-control", max_results=20)` antes de invocarlas.

```python
# Estado vivo
get_state                 # → {time_sec, playing, current_section, clip_count, ...}
list_clips                # filter: bar, group, section, time_range
list_fixtures · list_cue_points · list_markers

# Editar el show
add_clip(start_ms, duration_ms, effect_id, scope, layer, params)
move_clip(clip_id, new_start_ms, new_layer?)
set_clip_params(clip_id, params) · set_clip_color(clip_id, color_hex)
set_cue(slot, time_ms, name) · add_marker(time_ms, name)

# Rig
add_fixture(fixture_id, profile_id, universe, dmx_start, position, ...)
move_fixture(fixture_id, position) · set_fixture_property(fixture_id, key, value)

# Persistencia
save_show · save_rig

# Analyzer (v1.6) — Claude razona sobre la música
analyzer_summary · analyzer_list_sections(with_curated=True)
analyzer_list_beats(start_sec, end_sec?) · analyzer_list_downbeats(...)
analyzer_list_events(kind, start_sec?, end_sec?)
analyzer_get_features_at(time_sec, names=[...])
analyzer_get_features_range(start_sec, end_sec, downsample_to, names)
analyzer_find_drops(min_energy_jump=0.4) · analyzer_find_breakdowns(min_low_energy_sec=4)
analyzer_list_stems_events(stem)
# Curación
analyzer_set_section_label(idx, name, type) · analyzer_add_manual_event(time_sec, kind, name?)
analyzer_disable_event(time_sec, kind, tolerance_ms=20) · analyzer_set_event_threshold(kind, value)
```

---

## Las 8 piezas (arquitectura clásica, era Qt)

| # | Pieza | Archivos | Rol |
|---|-------|----------|-----|
| 1 | **Modelo** | `timeline_model.py` + `fixtures.py` | Clip, BarGroup, CuePoint, Marker, Fixture, FixtureProfile, FixtureRig. `supported_categories()` deduce {pixel,position,color,intensity,optical,strobe}. |
| 2 | **Efectos engine** | `effects_engine.py` | 51 efectos `pixel` (LED strips) + carga de plugins. |
| 3 | **Show engine** | `show_engine.py` | TimelineScheduler + `send_artnet()` UDP (10 WLED) + Universe Assembler + delegación a `OutputRouter`. Layer-mixing per-fixture. |
| 4 | **Output Router** | `io/outputs/router.py` + `output_targets.json` | universo → WledTarget / ArtnetNodeTarget / SimOnlyTarget. |
| 5 | **Loaders fixtures** | `io/loaders/gdtf_profile.py` | importa `.gdtf` via `pygdtf`. `load_profile()` acepta `.json` y `.gdtf`. |
| 6 | **UI desktop (legacy)** | `ui/dual_app.py`, `timeline_editor.py`, `feedback_app_with_barras.py`, `patch_panel.py`, `analyzer_panel.py` | PyQt5, 4 tabs, un único `ShowEngine` compartido. |
| 7 | **Viewer 3D** | `viewer3d_server.py` + `*.js` (Three.js) | servidor estáticos + WS que broadcast frames RGB. Canónico web = `web/public/v3d/`. |
| 8 | **API MCP** | `mcp_bridge.py` + `mcp_show_server.py` | Bridge JSON-RPC :9876 → FastMCP stdio → Claude. |

> Nota histórica: la era Qt usaba un `dual_app.py` que orquestaba 4 tabs sobre un `ShowEngine`
> compartido, con `mcp_bridge` (:9876) y `viewer3d_server` (:8080/:9877). En v1.10 ese rol lo
> cumple `server/` (headless) sirviendo la web; el flujo de efectos/núcleo es el mismo.
