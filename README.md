# Show Designer Pro 🎛️

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-1043%20py%20%2B%2036%20web-brightgreen)](#-calidad-y-tests)
[![Frontend CI](https://github.com/guillegar/show_designer/actions/workflows/frontend-ci.yml/badge.svg)](https://github.com/guillegar/show_designer/actions/workflows/frontend-ci.yml)
[![License: PPL 3.0](https://img.shields.io/badge/license-PPL%203.0-blue)](LICENSE)
[![Estado: v2.0](https://img.shields.io/badge/estado-v2.0%20estable-success)](CLAUDE.md)

> **Software profesional de iluminación.** Diseña coreografías de luz para tiras LED y fixtures
> DMX en un editor de *timeline* visual (estilo FL Studio / Adobe), míralas en un visor 3D en
> tiempo real, y contrólalas a mano (web) o con **Claude** vía MCP.

El motor corre **headless** (Python, sin Qt) y sirve una **web React**: el audio suena en el PC
(reloj maestro) y el navegador es control + visualizador. El mismo backend expone JSON-RPC para
que Claude lo controle por MCP.

```
┌──────────────┐   /ws/control (JSON-RPC)   ┌─────────────────────────┐   Art-Net / sACN / USB
│  Navegador   │ ◀────────────────────────▶ │  server/  (FastAPI,      │ ─────────────────────▶ Tiras LED
│  React + 3D  │   /ws/stream (frames RGB)   │  asyncio, tick 30 FPS)   │                         + fixtures DMX
└──────────────┘                             └───────────▲─────────────┘
                                                         │ JSON-RPC (:9876)
                                                   ┌─────┴─────┐
                                                   │  Claude   │  (MCP)
                                                   └───────────┘
```

---

## ✨ Qué puedes hacer

| | |
|---|---|
| 🎬 **Editor de timeline** | Multipista, *drag-drop* de clips, *snap* a beats, *undo/redo*, capas, patterns reutilizables, automatización y modulación de parámetros |
| 💡 **Efectos LED** | Biblioteca de efectos *pixel* built-in + sistema de **plugins autodescubiertos** (18 plugins, 25+ efectos) — flash, ondas, gradientes, fuego, scanner, VU, pixel-mapping de imagen/vídeo… |
| 🎯 **DMX por canal** | *Channel effects* para moving heads / wash / beam / strobe (pan-tilt, color, dimmer) con perfiles **GDTF** y JSON |
| 🎵 **Análisis de audio** | Beats, downbeats, secciones, BPM y tonalidad (librosa + madmom; separación de stems opcional vía demucs); además **análisis en vivo** desde entrada de audio |
| 📺 **Visor 3D** | Three.js en tiempo real (bloom + niebla), barras LED + movers que responden al DMX |
| 🤖 **Control por Claude** | 150+ comandos JSON-RPC vía MCP — pídele a Claude que genere o edite el show en lenguaje natural |
| 🎚️ **Directo** | Macros en vivo, grid de performance, cues profesionales, MIDI, OSC I/O, sync de tempo (tap / Link / MIDI Clock), auto-VJ por reglas |
| 📤 **Salida y export** | Art-Net, **sACN E1.31**, **ENTTEC Open DMX USB**; export de patch a PDF, DMX a CSV, **QLC+ XML**, preview de vídeo (GIF/MP4) y *bundle* de backup/restore |
| 🌐 **Integración** | API REST pública (`/api/v1`), webhooks (HMAC) y modo multiusuario con roles |

---

## 🚀 Inicio rápido

**Requisitos:** Python 3.11+, Windows 10/11 (Linux/macOS sin garantía). Node 18+ solo si vas a
recompilar el frontend.

```powershell
git clone https://github.com/guillegar/show_designer.git
cd show_designer

python -m venv venv311
.\venv311\Scripts\Activate.ps1
pip install -r requirements.txt

python -m server.main          # → http://localhost:8000
```

Abre **http://localhost:8000** en el navegador. Eso es todo: el backend sirve el frontend ya
compilado (`web/dist`).

**Desarrollo del frontend** (hot-reload, opcional):

```powershell
cd web
npm install
npm run dev                    # → http://localhost:5173 (proxea los WebSocket a :8000)
npm run build                  # recompila web/dist
```

**Launchers (Windows):** `Luces.bat` (reinicio limpio + abre el navegador), `Cerrar Luces.bat`
(apaga). Variantes que arrancan un show concreto: `Luces Espana.bat`, `Luces Barras.bat`,
`Luces Red Sun.bat`.

Guía detallada: [`docs/installation.md`](docs/installation.md) · [`docs/quickstart.md`](docs/quickstart.md)

---

## 🖥️ La interfaz (web)

Una sola página en el navegador, con pestañas:

| Pestaña | Para qué |
|---------|----------|
| **Proyectos** | Galería de shows; intercambiar componentes (canción / rig / secuencia / presets / auto-VJ), crear y copiar |
| **Timeline** | Diseñar el show: *drag-drop* de efectos, capas, patterns, marcadores, grupos, waveform |
| **Live** | Directo: transporte, macros, cues, grid de performance, render offline, MIDI/OSC |
| **Analyzer** | Análisis de audio: beats, secciones, BPM, tonalidad |
| **Patch** | Editor de rig: fixtures, mapa DMX, destinos Art-Net/sACN/USB, posición 3D |
| **Viewer3D / Preview** | Visualización 3D (Three.js) y preview 2D del frame en tiempo real |

Guía: [`docs/usage/ui-guide.md`](docs/usage/ui-guide.md) · Atajos: [`docs/usage/shortcuts.md`](docs/usage/shortcuts.md)

---

## 🔌 Hardware y salidas

| Salida | Estado | Notas |
|--------|--------|-------|
| **Tiras WLED** | ✅ | p. ej. 10 barras de 93 LEDs en universos Art-Net 1–10 |
| **Art-Net** | ✅ | unicast por universo, *routing* en `output_targets.json` |
| **sACN (E1.31)** | ✅ | unicast o multicast |
| **ENTTEC Open DMX (USB)** | ✅ | framing ENTTEC vía `pyserial` |
| **Fixtures DMX (movers/wash/beam)** | ✅ | perfiles GDTF o JSON |

El *routing* físico (universo → WLED / nodo Art-Net / sACN / USB / simulación) vive en
`output_targets.json`, **separado** del rig (`rig.json`). Guía: [`docs/hardware.md`](docs/hardware.md).

---

## 🤖 Control por Claude (MCP)

El backend expone el mismo JSON-RPC del dispatcher en `:9876` (compat MCP), así que Claude puede
controlar el show con `mcp__show-control__*` (configurado en `.mcp.json`).

```
Tú:     «añade un drop de estrobo cada 4 compases en el estribillo»
Claude: [genera los clips vía el dispatcher]   →  aparecen en el timeline ✅
```

Detalle: [`docs/advanced/mcp.md`](docs/advanced/mcp.md).

---

## 🧪 Calidad y tests

- **1043 tests Python** (pytest) + **36 tests de frontend** (Vitest) — verdes.
- Frontend con **TypeScript estricto** (`tsc -b` limpio) + build de producción (Vite).
- Benchmarks de rendimiento marcados `@pytest.mark.bench` (presupuesto de latencia por frame).
- **CI** (GitHub Actions): el frontend se compila y testea en cada push — [`.github/workflows/frontend-ci.yml`](.github/workflows/frontend-ci.yml). La suite Python se ejecuta localmente (deps de audio pesadas).

```powershell
pytest tests/                         # suite Python
pytest tests/test_session.py -v       # un archivo
cd web; npx vitest run; npm run build # frontend
```

Más detalle: [`docs/development/testing.md`](docs/development/testing.md).

---

## 📦 Estructura

```
show_designer/
├── src/core/         # show_engine, timeline_model, fixtures, effects_engine, channel_effects
├── src/analysis/     # análisis de audio (librosa + madmom)
├── src/io/           # loaders GDTF, OutputRouter, project_manager, exporters
├── src/mcp/          # bridge JSON-RPC (:9876) + servidor FastMCP
├── server/           # backend headless: web.py, dispatcher.py, session.py, tick.py …
├── web/              # frontend React + TS + Vite  (web/public/v3d = visor 3D)
├── plugins/effects/  # plugins de efectos (IDs ≥1000, autodescubiertos)
├── profiles/         # perfiles de fixture (WLED + GDTF)
├── projects/         # shows: el_taser, el_taser_barras, himno_espana, pista_patinaje, red_sun
├── tests/            # pytest
└── docs/             # documentación (MkDocs)
```

Mapa completo: [`STRUCTURE.md`](STRUCTURE.md). Arquitectura y decisiones: [`CLAUDE.md`](CLAUDE.md)
y [`docs/advanced/architecture.md`](docs/advanced/architecture.md).

---

## 📚 Documentación

| Doc | Contenido |
|-----|-----------|
| [`CLAUDE.md`](CLAUDE.md) | Arquitectura profunda, decisiones de diseño y estado actual (doc de retoma) |
| [`STRUCTURE.md`](STRUCTURE.md) | Organización de directorios y archivos |
| [`SETUP.md`](SETUP.md) | Instalación paso a paso |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Cómo contribuir, flujo de PRs y tests |
| [`docs/`](docs/index.md) | Sitio completo (MkDocs): instalación, uso, plugins, API REST, ADRs… |

---

## 🤝 Contribuir

Las contribuciones son bienvenidas — lee [`CONTRIBUTING.md`](CONTRIBUTING.md). En resumen: crea una
rama (`fix/…` o `feature/…`), mantén `pytest tests/` en verde, líneas ≤ 120 columnas, y un commit
por cambio coherente. Dudas o ideas grandes → abre una
[Discussion](https://github.com/guillegar/show_designer/discussions).

---

## 📄 Licencia

**Prosperity Public License 3.0.0** — libre para uso personal, educativo y open-source; el uso
comercial requiere licencia (incluye periodo de prueba de 30 días). Términos completos en
[`LICENSE`](LICENSE).

**Créditos de terceros** (Three.js, pygdtf, …): [`web/public/v3d/CREDITS.md`](web/public/v3d/CREDITS.md).

---

<sub>Show Designer Pro — código original propio. Las dependencias se usan como librerías y se acreditan.</sub>
