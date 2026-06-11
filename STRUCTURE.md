# 📁 Estructura del Proyecto

> Estado real a **2026-06-11** (v1.10, arquitectura WEB). Para arquitectura y decisiones
> profundas ver `CLAUDE.md` y `docs/advanced/project-history.md`.

La app corre **headless** (Python, sin Qt) y sirve una **web React**. La UI PyQt5 (`src/ui/`)
sigue funcionando pero está en retirada. Lo nuevo vive en `server/` (Python) y `web/` (React+TS+Vite).

```
show-designer/
│
├── src/                      ← CÓDIGO NÚCLEO (reutilizado por Qt y por la web)
│   ├── core/                 💎 Núcleo del show
│   │   ├── show_engine.py        Scheduler + DMX assembler + layer mixing
│   │   ├── timeline_model.py     Clip, BarGroup, CuePoint, Marker, Timeline
│   │   ├── fixtures.py           FixtureProfile, Fixture, FixtureRig
│   │   ├── effects_engine.py     51 efectos pixel + carga de plugins
│   │   └── channel_effects.py    24 ChannelEffects (movers/wash/beam/strobe)
│   ├── analysis/             🎵 análisis de audio (analyzer_service: librosa + madmom)
│   ├── io/                   📦 loaders GDTF, OutputRouter, exporter, project_manager
│   ├── mcp/                  🤖 mcp_bridge (WS :9876) + mcp_show_server (FastMCP stdio)
│   ├── ui/                   🎨 UI PyQt5 LEGACY (dual_app, timeline_editor, patch, analyzer)
│   ├── core/undo.py          ↩ UndoManager FUENTE ÚNICA (server + editor Qt, hallazgo 9)
│   ├── viewer3d/             3️⃣ solo viewer3d_server.py (Qt) — los .js viven en web/public/v3d
│   ├── plugins/              🔌 (residuo histórico — los plugins activos están en /plugins)
│   ├── utils/                🛠️ shortcuts.py
│   └── _paths.py             PROJECT_DIR (raíz del repo)
│
├── server/                   ← BACKEND HEADLESS (v1.10, asyncio, SIN Qt) — python -m server.main
│   ├── main.py                   entry point (:8000)
│   ├── web.py                    FastAPI: estáticos + /ws/control + /ws/stream (+ compat MCP :9876)
│   ├── dispatcher.py             reusa handlers de mcp_bridge + handlers web-only
│   ├── session.py                ShowSession: timeline+show_engine+rig+analysis+audio
│   ├── tick.py                   loop 30 FPS → compute_frame → Art-Net → broadcast
│   ├── undo_manager.py           UndoManager del server
│   ├── audio_headless.py         reloj maestro (pygame.mixer + time.monotonic)
│   ├── validators.py             validación de params
│   ├── json_rpc.py, presets.py, toggles.py, exporters.py
│
├── web/                      ← FRONTEND React+TS+Vite
│   ├── src/                      Topbar, Tabs, Transport, views/ (Timeline/Live/Analyzer/Patch)
│   ├── public/v3d/               ⭐ VIEWER 3D canónico (Vite lo copia a dist/v3d/ en cada build)
│   ├── dist/                     build artifact (regenerado por `npm run build`; no editar a mano)
│   ├── index.html, package.json, vite.config.ts, tsconfig.json
│
├── plugins/effects/          ← 🔌 PLUGINS ACTIVOS (IDs ≥1000, autodescubiertos por effects_engine)
│   ├── example_plugin.py (meteor/heartbeat), solid_color.py, waving_flag.py, spanish_flag.py
│
├── profiles/                 ← fixture profiles JSON (WLED + genéricos) + GDTF
├── projects/                 ← ⭐ PROYECTOS canónicos: projects/<slug>/{project,show,rig,presets,feedback}.json
│   └── el_taser/  himno_espana/
├── analizadas/               ← análisis cacheado por canción (analysis.json + curation.json;
│                                 timeseries.npz y stems/ NO se versionan — ver .gitignore)
├── scripts/                  ← utilidades one-off (process_stems, create_himno_show, verify_*)
├── tests/                    ← ✅ 20 archivos, 416 tests verde (pytest)
├── docs/                     ← MkDocs (mkdocs.yml); detalle profundo en docs/advanced/
├── data/                     ← (legacy, casi vacío)
│
├── CLAUDE.md                 ← doc de retoma (arquitectura + decisiones + estado auditoría)
├── STRUCTURE.md              ← este archivo
├── README.md, SETUP.md, CONTRIBUTING.md, ANALYSIS.md, LICENSE
├── requirements.txt, pytest.ini, .coveragerc, .gitignore, .mcp.json, mkdocs.yml
├── Luces.bat / Cerrar Luces.bat / Luces Espana.bat   ← launchers Windows (web)
└── El Taser de Mama Remix.mp3, Himno_Espana.mp3      ← audio (en disco, NO versionado)
```

---

## 🚀 Cómo arranca (v1.10 web)

```
python -m server.main          → http://localhost:8000 (sirve web/dist + WS)
cd web && npm run dev          → Vite :5173 (dev del frontend, proxea WS a :8000)
python src/ui/dual_app.py      → UI PyQt5 legacy (red de seguridad)
```

El navegador NO recalcula luces: consume el frame binario real (10×93×3) del `/ws/stream`.
Claude controla por MCP igual que antes (dispatcher sirve el mismo JSON-RPC en :9876).

## 🔗 Acoplamiento (lo que importa)

- `server/` y `src/ui/` reutilizan SIN cambios `src/core`, `src/analysis`, `src/io`, `src/mcp`.
- Los **efectos pixel** reciben `(t, params, num_leds)` y devuelven RGB; no conocen Qt, red ni rig.
- El **routing físico** (universo → WLED/artnet/sim) vive en `output_targets.json`, aparte del rig.

## 🧭 Dónde encontrar cada cosa

| Quiero… | Ir a |
|---------|------|
| Editar la web | `web/src/views/` (Timeline.tsx, etc.) |
| Tocar el backend headless | `server/` (web.py, session.py, dispatcher.py, tick.py) |
| Entender/añadir efectos | `src/core/effects_engine.py` o un plugin en `plugins/effects/` |
| Añadir un fixture | `profiles/*.json` o `src/io/loaders/gdtf_profile.py` |
| Control por Claude | `src/mcp/` (bridge + server) |
| Viewer 3D | `web/public/v3d/` (canónico) |
| Ejecutar tests | `pytest tests/` (416) |
