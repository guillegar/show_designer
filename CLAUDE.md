# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Documento de retoma. Si abres una sesión nueva sin historial, **lee esto antes de tocar nada**. Resume arquitectura, decisiones y estado vivo del proyecto a fecha **2026-06-01** (**v1.10 en curso — MIGRACIÓN A WEB: backend headless + frontend React, las 4 vistas funcionando**).

---

## 0. TL;DR

- Carpeta raíz: `C:\Users\guille\Documents\Claude\Projects\`
- **Punto de entrada (v1.10, web):** `python -m server.main` (sirve la web en http://localhost:8000) + para desarrollo del frontend `cd web && npm run dev`.
- **Entry point legacy (PyQt5, deprecado pero funcional):** `python src/ui/dual_app.py`. Se mantiene como red de seguridad durante la transición; la web es ya la UI primaria.
- Software de iluminación profesional. **v1.10**: el motor (Python) corre **headless** (sin Qt) y sirve una web React; el audio suena en el PC (reloj maestro) y el navegador es la superficie de control + visualizador. Controlable por humano (web) y por Claude (MCP, compat en :9876).
- Hardware actual: **10 barras WLED** (93 LEDs cada una) en universos Art-Net 1..10 (IPs `192.168.1.201..210`).
- Show de prueba: `show_timeline.json` para "El Taser de Mamá Remix" (`El Taser de Mama Remix.mp3`, 273.3 s).
- Plan maestro detallado en `C:\Users\guille\.claude\plans\mellow-rolling-cray.md`.
- Licencia: **GPL-3.0** (compatible con ASLS Studio del que tomamos inspiración).

---

## 0.5 v1.10 — Arquitectura WEB (NUEVO, leer si tocas la web)

La UI PyQt5 se está jubilando en favor de una **web React + backend Python headless**.
El backend reutiliza SIN CAMBIOS `src/core`, `src/analysis`, `src/io`, `src/outputs`,
`src/mcp`. Todo lo nuevo vive en `server/` (Python) y `web/` (React+TS+Vite).

```
Navegador (web/ — Vite+React+TS)
  Topbar · Tabs · Transport      ← estado por /ws/stream
  Timeline · Live · Analyzer · Patch  ← JSON-RPC /ws/control + frames binarios
        │ HTTP estáticos   │ /ws/control (JSON-RPC)   │ /ws/stream (frames+estado+dmx)
        ▼                  ▼                          ▼
server/ (headless, asyncio, SIN Qt) — python -m server.main  (:8000)
  web.py        FastAPI: dist + /ws/control + /ws/stream (+ compat MCP :9876)
  dispatcher.py REUSA los 52 handlers de mcp_bridge.py (parchea _qt_call inline)
                + handlers web-only: set_loop/set_rec/set_volume/set_track_mute|solo/
                  list_feedback/add_feedback/analyzer_waveform_peaks
  tick.py       loop asyncio 30 FPS: compute_frame → Art-Net → broadcast (dmx a 7.5 FPS)
  session.py    ShowSession: dueño headless de timeline+show_engine+rig+analysis+
                library+audio. compute_frame = port Qt-free de TimelineEditorWindow.
                Expone los MISMOS atributos que esperan los handlers (tl_view/props
                son shims no-op). Reloj maestro = HeadlessAudioPlayer (pygame.mixer
                + time.monotonic, con modo silencioso si no hay tarjeta).
```

Claves:
- **Continuidad MCP/Claude**: el dispatcher sirve el mismo JSON-RPC en `:9876`, así
  `mcp_show_server.py` NO se toca. Claude sigue controlando con `mcp__show-control__*`.
- **El navegador NO recalcula luces**: consume el frame binario real (10×93×3 = 2790 B)
  del `/ws/stream`. `lights.jsx` del handoff fue solo referencia, no se portó.
- **Tests**: `tests/test_session.py`, `tests/test_dispatcher.py`, `tests/test_web.py`
  (este último con `LUCES_NO_MCP_COMPAT=1` para no abrir :9876). **382 verdes**.
- Deps nuevas: `fastapi`, `uvicorn[standard]`, `httpx` (test), `pygame`/`pygdtf`/
  `websockets` ya estaban en uso. Frontend: Node/npm + `vite react zustand`.
- **Arrancar**: `python -m server.main` y abrir http://localhost:8000 (sirve `web/dist`).
  Dev del frontend: `cd web && npm install && npm run dev` (Vite :5173 proxea WS a :8000).
  Rebuild para producción: `cd web && npm run build`.

---

## 1. Arquitectura — 7 partes, **bajo acoplamiento**

```
┌─────────────────────────────────────────────────────────────────┐
│                       dual_app.py (launcher)                    │
│ ┌──────────────┬──────────────────┬──────────────────────────┐  │
│ │ Tab Timeline │ Tab Feedback     │ Tab Patch (top-down 2D)  │  │
│ │ timeline_    │ feedback_app_    │ patch_panel.py           │  │
│ │ editor.py    │ with_barras.py   │                          │  │
│ └──────┬───────┴────────┬─────────┴────────────┬─────────────┘  │
│        └────────┬───────┴─────────┬────────────┘                │
│                 ▼                 ▼                             │
│        ┌─────────────────┐  ┌──────────────┐                    │
│        │ ShowEngine      │  │ FixtureRig   │                    │
│        │ show_engine.py  │◄─┤ fixtures.py  │                    │
│        └────────┬────────┘  └──────┬───────┘                    │
│                 │                  │                            │
│        ┌────────▼────────┐         │                            │
│        │ EffectLibrary   │         │                            │
│        │ effects_engine  │         │                            │
│        └─────────────────┘         │                            │
│                 ▲                  │                            │
│        ┌────────┴────────┐         │                            │
│        │ Timeline (model)│         │                            │
│        │ timeline_model  │         │                            │
│        └─────────────────┘         │                            │
└──────┬───────────────────┬─────────┴───────────────────────┬────┘
       │                   │                                 │
       │ ws :9876          │ ws :9877                        │ UDP 6454
       ▼                   ▼                                 ▼
┌────────────┐   ┌──────────────────────┐          ┌───────────────┐
│ mcp_bridge │   │ viewer3d_server.py   │          │ Art-Net DMX   │
│ JSON-RPC   │   │ HTTP :8080 + WS :9877│          │ → WLED barras │
└─────┬──────┘   └──────────┬───────────┘          └───────────────┘
      │                     ▼
      │              ┌─────────────────┐
      │              │ viewer3d/*.js   │
      │              │ Three.js + bloom│
      │              │ + moving_head   │
      │              └─────────────────┘
      ▼
┌──────────────────┐
│ mcp_show_server  │ ◄── stdio MCP ◄── Claude Code
│ (FastMCP stdio)  │
└──────────────────┘
```

### Las 8 piezas (v1.7 añade DMX assembler/router)

| # | Pieza | Archivos | LOC | Rol |
|---|-------|----------|-----|-----|
| 1 | **Modelo** | `timeline_model.py` + `fixtures.py` | ~520 | Clip, BarGroup, CuePoint, Marker, Fixture, FixtureProfile, FixtureRig. `FixtureProfile.supported_categories()` deduce automáticamente {pixel, position, color, intensity, optical, strobe}. |
| 2 | **Efectos engine** | `effects_engine.py` | ~1700 | 51 efectos `pixel` (LED strips). `ChannelEffect` para wash/beam/strobe **pendiente Fase 6**. |
| 3 | **Show engine** | `show_engine.py` | ~1100 | TimelineScheduler + `send_artnet()` UDP legacy (10 WLED) + **Universe Assembler** + delegación a `OutputRouter`. Layer-mixing per-fixture. |
| 4 | **Output Router** (v1.7) | `outputs/router.py` + `output_targets.json` | ~190 | `OutputRouter` mapea universo → `WledTarget` / `ArtnetNodeTarget` (stub) / `SimOnlyTarget`. |
| 5 | **Loaders fixtures** (v1.7) | `loaders/gdtf_profile.py` | ~230 | Importa `.gdtf` via `pygdtf`; mapea atributos GDTF → nombres canónicos. `fixtures.load_profile()` acepta `.json` y `.gdtf` indistintamente. |
| 6 | **UI desktop** | `dual_app.py`, `timeline_editor.py`, `feedback_app_with_barras.py`, `patch_panel.py`, `analyzer_panel.py`, `shortcuts.py` | ~5600 | PyQt5. TabbedDualApp con 4 tabs (Timeline / Feedback / Patch / Analyzer). Un único `ShowEngine` compartido. |
| 7 | **Viewer 3D** | `viewer3d_server.py` + `viewer3d/*.{html,js,json}` | ~700 + JS | Servidor HTTP estáticos en :8080, WebSocket :9877 que broadcast frames RGB. `viewer3d/main.js` + `moving_head.js`. **Movers demo estática pendiente DMX real (Fase 4)**. |
| 8 | **API MCP** | `mcp_bridge.py` + `mcp_show_server.py` + `.mcp.json` | ~1700 | Bridge JSON-RPC :9876 → FastMCP stdio → Claude. ~50 endpoints. |
| 9 | **Audio + análisis** | `analyzer.py`, `analyzer_pro.py`, `analyzer_service.py`, `analizadas/<song>/` | ~1500 | librosa+madmom+demucs offline → `AnalysisService` schema v3 + `Curation`. |

### Acoplamientos reales (los que importan)

- `timeline_editor` ↔ `show_engine`: el timeline llama `show_engine.send_frame(rgb_list)` (flujo LED legacy intacto).
- `show_engine` ↔ `OutputRouter`: el assembler delega `send_universe_via_router(universe_id, bytes_512)`. Router decide WLED / artnet_node / sim_only según `output_targets.json`.
- `show_engine` ↔ `FixtureRig`: `assemble_universe(uni, t)` itera `rig.by_universe(uni)` y arma 512 bytes.
- `dual_app` ↔ `mcp_bridge`: dual instancia `MCPBridge(app_provider=lambda: timeline_win)`. El bridge solo conoce esa interfaz.
- `dual_app` ↔ `viewer3d_server`: `viewer3d.broadcast_frame(frame)` en cada tick.
- `patch_panel` ↔ `FixtureRig`: emite `rig_changed` → dual persiste `fixtures.json` + regenera `viewer3d/rig_layout.json`.
- `FixtureProfile` ↔ todo: archivos `.json` o `.gdtf` cargan al mismo `FixtureProfile` interno. Quien use el modelo no sabe de dónde vino.
- **Efectos pixel no conocen Qt, ni red, ni FixtureRig**. Reciben `(t, params, num_leds)` y devuelven array RGB. Esto es lo que el usuario llama "bajo acoplamiento".
- **ChannelEffect (Fase 6)** seguirá el mismo principio: recibirá `(t, fixture, audio_context, params) → {channel_name: value}` y nunca tocará Qt/red/router.

---

## 2. Cómo arrancar (cold start)

```powershell
cd C:\Users\guille\Documents\Claude\Projects
python -m venv venv                    # crear venv si no existe
.\venv\Scripts\Activate.ps1            # activar
pip install -r requirements.txt        # instalar dependencias
python src/ui/dual_app.py              # arrancar (ruta actualizada v1.9 F2+)
```

Comprobar al arrancar (en consola):
- `[+] OutputRouter cargado: 11 universos enrutados`
- `[+] ShowEngine inicializado vía AnalysisService (song_id=39f24ab9db32, bpm=119.68, downbeats_source=fallback_4_4)`
- `[dual] MCP bridge arrancado en ws://127.0.0.1:9876`
- `[dual] Viewer 3D arrancado: http://localhost:8080/  (WS :9877)`
- `[dual] ShowEngine compartido entre ambas pestañas`
- `[dual] Render unificado: el Timeline pinta ambas pestañas`

Para que **Claude controle la app por MCP**: `.mcp.json` ya está configurado. Claude Code lanza `python mcp_show_server.py` por stdio al iniciar la sesión. Los tools aparecen como `mcp__show-control__*`.

**IMPORTANTE — reinicios**:
- Si tocas `mcp_bridge.py` → reinicia `dual_app.py`.
- Si tocas `mcp_show_server.py` → reinicia **Claude Code** (no basta con reiniciar dual_app).
- Puertos zombies: `Get-Process python | Stop-Process -Force` antes de relanzar si ves errno 10048.

---

## 3. Estado actual (2026-05-29)

### ✅ Terminado

- **v1.0 checkpoint** en `versions/v1.0_pre_mcp/` (40 features + CHANGELOG + SHA-256).
- **MCP server completo** (~50 endpoints):
  - Transport: `get_state`, `play`, `pause`, `stop`, `seek`, `blackout`
  - Clips R/W: `list_clips`, `add_clip`, `move_clip`, `delete_clip`, `set_clip_*`
  - Grupos: `list_groups`, `add_group`, `delete_group`, `set_group_bars`
  - Cues: `list_cue_points`, `set_cue`, `trigger_cue`, `clear_cue`, `rename_cue`
  - Markers: `list_markers`, `add_marker`, `delete_marker`
  - Fixtures: `list_fixtures`, `list_fixture_profiles`, `add_fixture`, `delete_fixture`, `move_fixture`, `set_fixture_property`, `save_rig`
  - **Analyzer (v1.6)**: `analyzer_summary`, `analyzer_list_sections`, `analyzer_list_beats`, `analyzer_list_downbeats`, `analyzer_list_events`, `analyzer_get_features_at`, `analyzer_get_features_range`, `analyzer_find_drops`, `analyzer_find_breakdowns`, `analyzer_list_stems_events`, `analyzer_set_section_label`, `analyzer_add_manual_event`, `analyzer_disable_event`, `analyzer_set_event_threshold`
  - Persistencia: `save_show`, `load_show`, `list_saved_shows`
  - Viewer: `open_3d_viewer`
- **Show El Taser**: 8 cue points asignados (`0, 52, 76, 86, 183, 193, 213, 218 s`), 55 flashes cada 5 s en `bar_3`.
- **Viewer 3D Three.js**: bloom, fog, ACES tonemapping, OrbitControls, 10 LEDBar + 4 MovingHead (beam volumétrico con shader custom). Sirve en `http://localhost:8080/`.
- **Patch Panel 2D top-down** (3ª tab), conectado a `FixtureRig`.
- **Fixtures genéricos**: `FixtureProfile` + `Fixture` + `FixtureRig` con persistencia en `fixtures.json`. Profiles JSON en `profiles/{wled_strip_93, generic_mover_16ch, dimmer_1ch}.json`.
- **Auto-sync rig**: `dual_app._sync_rig_to_viewer3d()` regenera `viewer3d/rig_layout.json` cuando el rig cambia (via patch panel o MCP).
- 14 fixtures vivos: 10 `led_strip` (univ 1..10) + 4 `moving_head` wash (univ 11, dmx_start 1/17/33/49).
- **Release v1.6 "Audio Brain" completa** (todas las fases A/B/C/D):
  - **`analyzer_service.py`** (~900 LOC) — `AnalysisService` con schema v3 + migrador v1/v2→v3 + `Curation` separada. Una sola puerta al análisis para show_engine / timeline_editor / generate_show_taser / mcp_bridge.
  - **`analyzer_panel.py`** (~600 LOC) — 4ª tab "🎵 Analyzer" con waveform + overlays toggleables (beats/downbeats/kicks/snares/hats/secciones/manuales/disabled), tablas editables de secciones y eventos, click derecho para añadir manuales y cue seeds, botón "Aplicar a Timeline".
  - **Vocabulario híbrido + libre** de tipos de sección: `intro, verse, chorus, drop, breakdown, buildup, bridge, outro, silence` + texto libre.
  - **Curación no destructiva** en `analizadas/<song>/curation.json`: re-correr `analyzer_pro.py` no pisa.
  - **dtempo expuesto** en `audio_context` (los efectos ya pueden reaccionar al tempo dinámico).
  - **Madmom fallback con bandera** `downbeats_source ∈ {madmom, fallback_4_4, none}`.
  - **53 tests pytest** en `tests/{test_analyzer_service.py, test_curation.py, test_mcp_analyzer.py}` (2.0s). Cubren migrador v1/v2/v3, carga real, curación end-to-end, todos los 14 handlers MCP analyzer.
  - **Atajo Ctrl+M** → tab Analyzer. `Ctrl+1..4` → tabs.

- **Release v1.7 "DMX Multi-Fixture" COMPLETA** — Todas las 9 fases terminadas:
  - **Fase 0**: checkpoint `versions/v1.6_pre_dmx/` con CHANGELOG + SHA-256 + comando restauración.
  - **Fase 1**: 3 profiles JSON nuevos en `profiles/` — `generic_wash_15ch`, `generic_beam_18ch`, `generic_strobe_2ch`.
  - **Fase 2**: `loaders/gdtf_profile.py` con `pygdtf`. Checkpoint `versions/v1.7_p2_gdtf_loader/`.
  - **Fase 3**: Universe Assembler + Output Router. Checkpoint `versions/v1.7_p3_assembler/`.
  - **Fase 4**: Viewer 3D con DMX real — `broadcast_dmx_state()`, `get_fixture_dmx_states()`, `applyDmxState()` en JS, clase `Strobe`. Movers reaccionan a `manual_channels`. Checkpoint `versions/v1.7_p4_viewer3d_real/`.
  - **Fase 5**: Channel Editor en Patch Panel — `ChannelEditorWidget` con sliders 0-255 por canal. Se muestra al seleccionar fixture no-LED. `Clip.category` + `Clip.channel_effect_id` añadidos al modelo. Checkpoint `versions/v1.7_p5_channel_editor/`.
  - **Fase 6**: Catálogo `ChannelEffect` — `channel_effects.py` con 24 efectos en 5 categorías (position/color/intensity/optical/strobe). `ChannelEffectLibrary`. `show_engine._render_clip_channels` usa librería real. Checkpoint `versions/v1.7_p6_channel_effects/`.
  - **Fase 7**: MCP tools nuevos — `list_channel_effects`, `add_channel_clip`, `get_dmx_universe`, `apply_channel_preset`. Checkpoint `versions/v1.7_p78_mcp_tests/`.
  - **Fase 8**: 48 tests en `tests/test_channel_effects.py`. Total: **151/151 tests verdes** en 2.73s.

### 🔄 En curso / dudas abiertas
- `feedback_app_with_barras.py` aún carga `analysis.json` directamente (no usa `AnalysisService`). Funciona, pero no respeta curación. Bajo coste arreglarlo cuando toque.
- Stems demucs no procesados aún para El Taser — la API MCP `list_stems_events` devuelve `{available: False}`. Cuando se procesen, los efectos `StemModulated` ya pueden engancharse.

### ❌ Explícitamente fuera de scope (el usuario lo dijo)

- **MIDI** no interesa por ahora.
- **sACN** no interesa por ahora.
- **Git** no usar (el usuario no quiere operaciones git).
- No reinventar lo que ASLS Studio o Three.js ya hacen bien.

---

## 4. Decisiones tomadas (y el porqué)

| Decisión | Por qué |
|----------|---------|
| **Python puro, sin Chromium embedido, sin daemons** | Stack simple; el viewer 3D vive en el navegador del usuario, no embedido. |
| **Art-Net puro como output principal** | Ya funcionaba con WLED + Art-Net→DMX node. sACN/OLA añaden complejidad sin ganancia inmediata. |
| **MCP por WebSocket interno + stdio externo** | Permite separar la app Qt (event loop principal) del proceso MCP que Claude Code lanza. El bridge JSON-RPC desacopla los dos. |
| **FastMCP en thread separado con `run_coroutine_threadsafe`** | FastMCP corre su propio asyncio loop; necesitamos un loop secundario en thread daemon para nuestras llamadas RPC. Si no, "Cannot run the event loop while another loop is running". |
| **`_qt_call(app, fn)` con `QTimer.singleShot(0, fn)`** | Las mutaciones de modelo desde MCP llegan en el thread del WebSocket. QTimer.singleShot(0) las marshalla al thread de Qt sin bloquear. |
| **Único `ShowEngine` compartido entre tabs** | Antes había 2 ShowEngines → 2 streams UDP a las mismas IPs (LEDs parpadeaban raro). `dual_app._share_show_engine()` cierra el socket del feedback y reusa el del timeline. |
| **Render unificado: timeline calcula el frame, todos lo pintan** | Evita dos cómputos paralelos. `_link_renders()` reconecta el `render_timer` del timeline a un `shared_tick` que pinta timeline + feedback + broadcast 3D + envía Art-Net. |
| **Idle FPS reducido a 10 Hz** | Cuando nada se reproduce, no hay razón para 30 fps. Ahorra CPU del usuario. |
| **`viewer3d/rig_layout.json` auto-generado** | Single source of truth = `fixtures.json` (FixtureRig). El layout JS lo deriva. |
| **MovingHead JS escrito desde cero, inspirado en ASLS** | El usuario dijo explícitamente: *"tu leelo e inspirate todo lo necesario pero no copies el código, aunque es imposible, porque quiero que sea mío"*. Conceptos replicados (base→yoke→head→beam, fresnel, falloff), implementación nueva. Atribución en `viewer3d/CREDITS.md`. |
| **Shader beam: fresnel + `min(a, 1.0)` en alpha** | Con AdditiveBlending y DoubleSide, los dos lados del cilindro hueco acumulan luminosidad. Sin clamp en RGB (ACES tonemapping comprime), sí clamp en alpha. |
| **Bars: body BEHIND LEDs + LEDs ligeramente más grandes** | Antes los LEDs estaban dentro del body opaco y no se veían. Ahora `body.position.z = -bodyDepth` y LEDs `0.95×` body en lugar de iguales. |
| **Movers responden a DMX real desde Fase 4** | `get_fixture_dmx_states()` lee `manual_channels` de cada fixture no-LED y los broadcast al viewer 3D cada tick. Patch panel sliders → mover gira en tiempo real. |
| **ChannelEffect puro: t+ctx+params→dict** (v1.7 F6) | Mismo principio que los pixel effects: sin Qt, sin red, sin rig. `_render_clip_channels()` los llama lazy. Facilita tests y catálogo ampliable sin tocar show_engine. |
| **track=-1 para channel clips** (v1.7 F5) | Clips de canal (category!='pixel') usan track=-1. La UI del timeline no los renderiza (no hay track -1 visible), y el motor los filtra por scope='fixture:<id>'. |
| **GPL-3.0** | Compatible con ASLS Studio (el código del que nos inspiramos es GPL-3.0). |
| **GDTF + JSON híbrido para profiles** (v1.7) | GDTF para fixtures comerciales (descargar de gdtf-share.com). JSON propio para WLED + genéricos sin marca + prototipos. Internamente UN solo `FixtureProfile`. Decisión: el usuario dijo *"gdtf tiene que usar lo que dudo es si usar los json tambien o no"* → híbrido porque WLED no tiene GDTF natural. |
| **Categorías por capacidad, deducidas auto** (v1.7) | 6 categorías: pixel/position/color/intensity/optical/strobe. `FixtureProfile.supported_categories()` las deduce del `channel_map`. Cada `ChannelEffect` declara `category` + `required_channels`. **Imposible** aplicar MoverCircle a una barra LED. Razón del usuario: *"creo que habria quee separar en efecto para cada tipo de fixure, no se puede aplicar movimiento a una barra"*. |
| **LTP por layers en mezcla de canales** (v1.7) | Cuando varios clips channel-level activos tocan el mismo canal de un fixture, el de mayor `layer` gana. Coherente con sistema RGB existente. Permite a un wash tener clips paralelos en position+color+intensity sin chocar. |
| **Assembler+Router en paralelo al flujo legacy** (v1.7) | El show El Taser sigue por `send_frame()` viejo (10 WLED bit-exact). El assembler+router viven para tests + futura Fase 4 (broadcast extendido al viewer 3D) + cuando lleguen movers reales. Zero riesgo de regresión. |
| **`output_targets.json` separado de `fixtures.json`** (v1.7) | El routing físico es responsabilidad del operador del sistema, no del diseñador del rig. Cuando llegue un nodo Art-Net→DMX, basta cambiar `{"11": {"type": "sim_only"}}` → `{"11": {"type": "artnet_node", "ip": "192.168.1.50"}}`. Sin tocar código. |
| **UTF-8 forzado a stdout/stderr en dual_app** | Windows console por defecto cp1252 → cualquier emoji o flecha (`→`) crashea `print()`. `sys.stdout.reconfigure(encoding='utf-8')` al inicio de dual_app evita la familia entera de bugs. |

---

## 5. Errores famosos y sus fixes (para no volver a tropezar)

| Error | Causa raíz | Fix |
|-------|-----------|-----|
| `Cannot run the event loop while another loop is running` en mcp_show_server | FastMCP corre asyncio; llamar `asyncio.run()` dentro choca. | `_bg_loop` global + `asyncio.run_coroutine_threadsafe`. Ver `mcp_show_server.py:_ensure_bg_loop`. |
| `clear_cue` no limpiaba el cue | El handler delegaba en `app._clear_cue` que no existía con esa signatura. | Mutar el modelo directamente en `_h_clear_cue` y refrescar UI con `_qt_call`. |
| `list_fixture_profiles` → "Método desconocido" | dual_app corriendo con código viejo del bridge en memoria. | Reiniciar dual_app. **Regla**: cambios en `mcp_bridge.py` requieren restart de dual_app. |
| Puerto 9876/9877 ocupado (errno 10048) | Procesos python zombies. | `Get-Process python \| Stop-Process -Force`. |
| Beam shader casi negro | `vRadialT` siempre era 1 (vértices del cilindro están todos al mismo radio). | Cálculo real de fresnel con `vWorldNormal` en el fragment. |
| Beams enterrados bajo el suelo | Beam length 14 m apuntando hacia abajo con tilt pequeño. | `tilt ∈ [62°, 67°]` + `beamLength = 7.5 m`. |
| "Los movers están pero apagados" | `wallAlpha` base muy bajo (0.18). | Subido a 0.55, eliminado el `discard` temprano. |
| "Los focos se ven pero las barras no" | LEDs renderizados dentro del body opaco. | Body desplazado en Z, LEDs ligeramente más grandes que body. |
| "La barra de tiempo del analyzer no avanza" | `shared_get_time()` devolvía el `fb.audio_player.get_current_time()` cuando la tab activa NO era el Timeline (0 porque feedback nunca arrancó). + `_on_tab_changed(idx>=2)` reseteaba audio al cambiar a Patch/Analyzer. + `print(f"→")` con cp1252 crasheaba. | `shared_get_time()` ahora prioriza el audio playing como master. `_on_tab_changed` retorna temprano si `idx >= 2`. `sys.stdout.reconfigure(encoding='utf-8')` al inicio. |
| Encoding cp1252 en `print` con emojis/flechas en Windows | Console default no UTF-8. | `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` al inicio de `dual_app.py`. |
| **App se cierra sola (v1.9 F2)** — la app arrancaba bien pero moría en cuestión de segundos. Inicialmente parecía aleatorio. | `_handle_client` en `mcp_bridge.py` solo capturaba `ConnectionClosed`. Conexiones TCP crudas al puerto 9876 (Test-NetConnection, healthcheck Claude Code MCP) lanzaban `websockets.exceptions.InvalidMessage` DURANTE el handshake (antes de `_handle_client`). Sin `loop.set_exception_handler`, la excepción mataba el thread daemon → race con Qt → app silenciosamente cerrada. | `loop.set_exception_handler` con `_silenciables = (InvalidMessage, ConnectionResetError, EOFError, BrokenPipeError, OSError)`. Mismo patrón aplicado a `viewer3d_server.py`. `logging.getLogger("websockets.*").setLevel(CRITICAL)` para silenciar tracebacks ruidosos. `sys.excepthook` global en `dual_app.main()` para fail-soft de slots Qt. |
| **`Bar -1 L0 · #0` al seleccionar channel clip (v1.9 F2)** | `PropertiesPanel.set_clips` no distinguía pixel vs channel clips. Cambiar el combo de efectos reescribía `effect_id` y `label` del channel clip → corrupción. | Rama temprana en `set_clips`: si `category != 'pixel'`, panel reducido con combo deshabilitado y title `⬡ <effect_id> · <fixture_id> (<category>)`. Rama pixel re-habilita el combo. |
| **Activar Draw sin elegir efecto creaba clip white_flash fantasma (v1.9 F2)** | `draw_effect_id` defaulteaba a 0 (WhiteFlash). | `draw_effect_id = None` por defecto. Guard en `mousePressEvent` rama TOOL_DRAW. Label "(sin efecto)" + status warning en `_set_tool`. |
| **App "no responde" al tocar una fixture lane (v1.9 F4)** — congelada con stdout saturado por tracebacks repetidos. | (a) `_draw_track_headers` línea 863 usaba `fx.name` que no existe en `Fixture` (regresión de v1.8 F2; debería ser `fx.label`). (b) El `sys.excepthook` sin throttling logueaba la MISMA excepción en cada repintado de Qt → buffer de stdout saturado → main loop sin tiempo para procesar eventos. | (a) `fx.name` → `fx.label`. (b) Throttling de 2s por `(exc_type, filename, lineno)` en el excepthook → repeticiones silenciadas. |

---

## 6. Layout del repo (lo que importa)

```
Projects/
├── 📚 DOCUMENTACIÓN
│   ├── README.md              ← guía user-facing (cómo arrancar, atajos)
│   ├── CLAUDE.md              ← este archivo (arquitectura + decisiones)
│   ├── STRUCTURE.md           ← estructura de src/ (qué va dónde)
│   ├── SETUP.md               ← instalación paso a paso
│
├── 📁 src/                    ← CÓDIGO FUENTE (reorganizado v1.9 F2+)
│   ├── core/                  Núcleo (show_engine, timeline_model, fixtures, effects)
│   │   ├── show_engine.py
│   │   ├── timeline_model.py
│   │   ├── fixtures.py
│   │   ├── effects_engine.py
│   │   └── channel_effects.py
│   ├── ui/                    Interfaz Qt5
│   │   ├── dual_app.py        ← entry point (4 tabs, sys.excepthook global)
│   │   ├── timeline_editor.py ← editor principal
│   │   ├── feedback_app_with_barras.py
│   │   ├── patch_panel.py
│   │   └── analyzer_panel.py
│   ├── analysis/              Análisis de audio
│   │   └── analyzer_service.py ← API unificada (librosa + madmom)
│   ├── io/                    Loaders, exporters, routing
│   │   ├── loaders/gdtf_profile.py
│   │   ├── outputs/router.py
│   │   ├── exporter.py        ← QLC+ XML + CSV
│   │   └── project_manager.py ← multi-proyecto (v1.8 F3)
│   ├── mcp/                   MCP bridge (Claude control)
│   │   ├── mcp_bridge.py      ← WebSocket :9876
│   │   └── mcp_show_server.py ← FastMCP stdio
│   ├── viewer3d/              Visualizador 3D
│   │   ├── viewer3d_server.py ← HTTP :8080 + WS :9877
│   │   ├── index.html, main.js, moving_head.js
│   │   └── rig_layout.json    ← auto-generado
│   ├── plugins/               Plugin system (v1.8 F4)
│   │   └── effects/example_plugin.py
│   └── utils/                 Utilidades
│       └── shortcuts.py       ← atajos configurables
│
├── 📁 tests/                  363 tests verdes (92.6% cobertura)
│   ├── test_analyzer_service.py, test_curation.py, test_mcp_analyzer.py
│   ├── test_gdtf_loader.py, test_output_router.py, test_universe_assembler.py
│   ├── test_channel_effects.py, test_generation_tools.py, test_plugin_system.py
│   ├── test_exporter.py, test_project_manager.py, test_effects_render.py
│   ├── test_drag_create_channel.py
│   └── fixtures/test_wash_4ch.gdtf
│
├── 📁 data/                   Datos del usuario
│   ├── profiles/              6 fixture profiles (JSON + GDTF support)
│   ├── projects/el_taser/     Proyecto de prueba
│   └── analizadas/            Análisis cachés
│
├── 📁 versions/               Checkpoints históricos (rollback)
│   ├── v1.0_pre_mcp/, v1.6_pre_dmx/
│   ├── v1.7_p{2,3,4,5,6,78}_{gdtf,assembler,...}/
│   ├── v1.8_p{1,2,3,4,5,6}_{gen,export,proj,polish,...}/
│   └── v1.9_p{1,2}_{drag_channel,stabilization}/
│
├── 📁 _legacy/                Scripts antiguos (no se usan en runtime)
│   ├── old_scripts/           40+ scripts de demostración
│   └── timeline_editor_versions/ v01-v04 históricos
│
├── ⚙️ CONFIGURACIÓN
│   ├── requirements.txt        Dependencias Python (PyQt5, librosa, madmom, etc)
│   ├── pytest.ini, .coveragerc Config de tests
│   ├── .mcp.json              Registro MCP server
│   ├── .gitignore, .github/workflows/ci.yml
│   └── launch_show_designer.bat ← launcher actualizado (apunta a src/ui/dual_app.py)
│
├── viewer3d/
│   ├── index.html
│   ├── main.js                ← scene Three.js + WebSocket
│   ├── moving_head.js         ← MovingHead class + shaders beam
│   ├── rig_layout.json        ← auto-generado desde FixtureRig
│   └── CREDITS.md
│
├── analizadas/
│   └── <song_slug>/
│       ├── analysis.json      ← crudo (regenerable)
│       ├── timeseries.npz     ← crudo
│       └── curation.json      ← humano, NUNCA pisado al re-analizar
│
├── shows_saved/               ← shows exportados (legacy)
├── show_timeline.json         ← (legacy, migrado a projects/el_taser/show.json)
│
├── versions/                  ← checkpoints de rollback
│   ├── v1.0_pre_mcp/          ← checkpoint pre-MCP
│   ├── v1.6_pre_dmx/          ← pre-v1.7 (53 tests)
│   ├── v1.7_p{2,3,4,5,6,78}_*/  ← fases v1.7 (151 tests al final)
│   ├── v1.8_p{1,2,3,4,5,6}_*/ ← fases v1.8 (353 tests al final)
│   ├── v1.9_p1_drag_channel_clips/  ← drag-create (363 tests)
│   └── v1.9_p2_stabilization/ ← anti-crash bridge + viewer3d
│
├── _legacy/                   ← (v1.9 F2) archivado, no se usa en runtime
│   ├── old_scripts/           ← test_*.py al raíz, unify_*, wled_framework, etc.
│   └── timeline_editor_versions/  ← v01-v04 históricos
│
├── references/
│   └── asls-studio/           ← clone para LEER inspiración (NO copiar)
└── venv311/                   ← venv Python 3.11
```

## Reglas de rollback

Antes de cada fase potencialmente destructiva → `versions/vX.Y_pN_xxx/` con:
- Snapshot de los archivos modificados (no de todo el repo).
- `CHANGELOG.md` con: cambios concretos, dependencias nuevas, SHA-256 de
  archivos críticos, comando `xcopy` de restauración, verificación post-restauración.

Para rollback completo a una fase anterior estable:
```
xcopy versions\v1.9_p2_stabilization\* . /Y /I
```

---

## 7. Comandos comunes (desarrollo)

### Tests
```powershell
# Todos los tests (363, tarda ~4-5s)
pytest tests/ -v

# Un archivo específico
pytest tests/test_analyzer_service.py -v

# Un test específico
pytest tests/test_analyzer_service.py::test_summary -v

# Tests paramétricos (123 casos en test_effects_render.py)
pytest tests/test_effects_render.py -v

# Con cobertura (mínimo 60%, salva en htmlcov/)
pytest tests/ --cov=src --cov-report=html

# Smoke test rápido (sólo analyzer_service, 2s)
pytest tests/test_analyzer_service.py -v
```

### Lint y format (opcional)
```powershell
# No hay formatters configurados por defecto, pero puedes:
# pylint src/core/show_engine.py
# flake8 src/ --max-line-length=120
```

### Ejecutar
```powershell
# Aplicación completa
python src/ui/dual_app.py

# Solo MCP server (para testing sin Qt)
python src/mcp/mcp_show_server.py

# Solo viewer 3D en http://localhost:8080/
python src/viewer3d/viewer3d_server.py
```

### Resetear puertos
```powershell
# Si ves "Port 9876/9877 already in use"
Get-Process python | Stop-Process -Force
```

---

## 8. APIs que ya existen y suelen ser útiles vía MCP

```python
# Estado vivo
mcp__show-control__get_state                  # → {time_sec, playing, current_section, clip_count, ...}
mcp__show-control__list_clips                 # filter: bar, group, section, time_range
mcp__show-control__list_fixtures              # → 14 fixtures actuales
mcp__show-control__list_cue_points
mcp__show-control__list_markers

# Editar el show
mcp__show-control__add_clip(start_ms, duration_ms, effect_id, scope, layer, params)
mcp__show-control__move_clip(clip_id, new_start_ms, new_layer?)
mcp__show-control__set_clip_params(clip_id, params)
mcp__show-control__set_clip_color(clip_id, color_hex)
mcp__show-control__set_cue(slot, time_ms, name)
mcp__show-control__add_marker(time_ms, name)

# Rig
mcp__show-control__add_fixture(fixture_id, profile_id, universe, dmx_start, position, ...)
mcp__show-control__move_fixture(fixture_id, position)
mcp__show-control__set_fixture_property(fixture_id, key, value)

# Persistencia
mcp__show-control__save_show
mcp__show-control__save_rig

# Analyzer (v1.6) — Claude razona sobre la música
mcp__show-control__analyzer_summary
mcp__show-control__analyzer_list_sections(with_curated=True)
mcp__show-control__analyzer_list_beats(start_sec, end_sec?)
mcp__show-control__analyzer_list_downbeats(start_sec, end_sec?)
mcp__show-control__analyzer_list_events(kind, start_sec?, end_sec?)
mcp__show-control__analyzer_get_features_at(time_sec, names=[...])
mcp__show-control__analyzer_get_features_range(start_sec, end_sec, downsample_to, names)
mcp__show-control__analyzer_find_drops(min_energy_jump=0.4)
mcp__show-control__analyzer_find_breakdowns(min_low_energy_sec=4)
mcp__show-control__analyzer_list_stems_events(stem)
# Curación
mcp__show-control__analyzer_set_section_label(idx, name, type)
mcp__show-control__analyzer_add_manual_event(time_sec, kind, name?)
mcp__show-control__analyzer_disable_event(time_sec, kind, tolerance_ms=20)
mcp__show-control__analyzer_set_event_threshold(kind, value)
```

Tools deferred: **siempre** cargar las del show con `ToolSearch(query="mcp__show-control", max_results=20)` antes de invocarlas.

---

## 9. Estado actual y próximos pasos

### v1.7 "DMX Multi-Fixture" COMPLETA (2026-05-29)
151 tests, 9 fases. GDTF loader + Universe Assembler + Router + Channel Editor +
24 ChannelEffects + 4 MCP tools de DMX.

### v1.8 "Generation + Multi-project + Polish" COMPLETA (2026-05-29)
- **F1**: 3 MCP generation tools (`generate_section`, `mirror_clips_lr`,
  `apply_palette_to_range`) + 36 tests
- **F2**: Fixture lanes visuales en el timeline editor (lectura/selección/borrado)
- **F3**: Multi-proyecto — `projects/<slug>/` con auto-migración del legacy
- **F4**: Plugin system — `plugins/effects/*.py` autodescubiertos (IDs >= 1000)
- **F5**: Exporters — QLC+ XML workspace + CSV de clips
- **F6**: Tests CI — `.coveragerc`, `pytest.ini`, GitHub Actions, 92.6% cobertura
- **353/353 tests verdes** al finalizar

### v1.9 EN CURSO (2026-05-29)
- **F1 COMPLETA — Drag-create de channel clips**: browser con tabs Pixel/Channel,
  modo Draw bimodal (`draw_kind ∈ {pixel, channel}`), validación lane/effect-kind
  con warnings, crea Clips con `category` + `channel_effect_id` + `scope='fixture:<id>'`.
  10 tests nuevos en `test_drag_create_channel.py`.
- **F2 COMPLETA (CRÍTICA) — Estabilización anti-crash**:
  - Bug del bridge `mcp_bridge.py`: `_handle_client` solo capturaba
    `ConnectionClosed`. Conexiones TCP crudas (Test-NetConnection, healthchecks)
    lanzaban `InvalidMessage` DURANTE el handshake (antes de `_handle_client`)
    → mataba el thread daemon → race con Qt → app cerrada silenciosa.
  - Fix: `loop.set_exception_handler` silenciando `InvalidMessage`,
    `ConnectionResetError`, `EOFError`, `BrokenPipeError`, `OSError`.
  - `logging.getLogger("websockets.*").setLevel(CRITICAL)` para silenciar
    tracebacks ruidosos.
  - Mismo bug presente en `viewer3d_server.py` → mismo fix aplicado.
  - `PropertiesPanel.set_clips` detecta channel clips y los muestra en modo
    reducido (combo de efectos pixel deshabilitado, no reescribe el clip).
  - `sys.excepthook` global en `dual_app.main()` → slots Qt no matan el proceso.
  - **363/363 tests verdes**, 15 conexiones TCP crudas verificadas sin crash.

### Próximos bloques candidatos (v1.10+)

- **OSC support**: TouchOSC/Lemur input para control en vivo (MIDI sigue
  fuera de scope, pero OSC sí). Output también, para piezas externas.
- **Editor de params de channel clips**: panel propio para editar
  speed/radius/color del ChannelEffect seleccionado (ahora solo se editan
  start/end y se asume defaults).
- **MP4 export del viewer 3D**: ffmpeg capturando WS frames + audio.
- **Live mode mejorado**: cue panel grande, tap tempo manual, snapshots,
  override de clips en tiempo real para concierto real.
- **Stems demucs para El Taser**: procesar y activar `analyzer_list_stems_events`.
- **Auto-show generator**: MCP tool end-to-end que dada una canción
  genera un show coherente (intro/drops/breakdowns/outro) usando análisis +
  reglas + plantillas.

### Cleanup completado en v1.9 F2

- Archivos `test_*.py` al raíz (no la suite oficial) → `_legacy/old_scripts/`
- `timeline_editor_v0{1,2,3,4}.py` → `_legacy/timeline_editor_versions/`
- Scripts one-off antiguos (`unify_*.py`, `wled_framework.py`, `touchdesigner_bridge.py`)
  → `_legacy/old_scripts/`
- `__pycache__` regenerable → eliminados (excepto `venv311`)
- `dual_app.log`, `dual_app.err`, `timeline_editor_crash.log` → eliminados (regenerables)
- `.gitignore` creado con patrones estándar
- `README.md` user-facing creado

---

## 10. Tics del usuario (cosas que conviene recordar)

- Escribe en español, a veces sin tildes y con erratas ("focos se veian", "elacoplamiento", "gdtf tiene que usar lo que dudo es si usar los json tambien"). No corregirle.
- Quiere **rapidez** y **resultados visibles**: prefiere ver el visualizer encendido antes que arquitectura perfecta.
- Le preocupa el acoplamiento. Cualquier refactor que reduzca acoplamiento entre piezas → win.
- Quiere código **suyo**. ASLS Studio se LEE para inspirarse, no se copia ni siquiera con permiso. La excepción es Three.js (MIT) y pygdtf (LGPL). Atribución obligatoria en `CREDITS.md`.
- Auto Mode está activo: hay que avanzar sin pedir permiso para decisiones razonables. Solo parar si la dirección es genuinamente ambigua.
- **Guarda versiones**: el usuario insistió *"recuerda guardar versiones por si estropeamos el codigo"*. Cada fase de v1.7 → checkpoint en `versions/v1.7_pN_xxx/` con CHANGELOG + SHA-256.
- **Pregunta principios estructurales**: cuando una decisión afecta a TODO el sistema (ej. categorías de efectos), conviene preguntar antes con AskUserQuestion. El usuario sabe lo que quiere, y un mal principio cuesta caro de revertir.
