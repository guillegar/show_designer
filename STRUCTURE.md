# 📁 Estructura del Proyecto

```
Show Designer Pro v2/
│
├── src/                          ← TODO el código fuente
│   │
│   ├── core/                     ← 💎 NÚCLEO DEL SHOW
│   │   ├── show_engine.py        Scheduler + DMX assembler + layer mixing
│   │   ├── timeline_model.py     Clip, Marker, CuePoint, Timeline data model
│   │   ├── fixtures.py           FixtureProfile, Fixture, FixtureRig
│   │   ├── effects_engine.py     51 efectos pixel para LED strips
│   │   └── channel_effects.py    24 ChannelEffects para fixtures DMX
│   │
│   ├── ui/                       ← 🎨 INTERFAZ GRÁFICA (PyQt5)
│   │   ├── dual_app.py           Entry point + 4 tabs principales
│   │   ├── timeline_editor.py    Editor visual de clips (~3500 LOC)
│   │   ├── feedback_app_with_barras.py  Control en vivo + análisis
│   │   ├── patch_panel.py        Vista 2D top-down del rig
│   │   └── analyzer_panel.py     Análisis visual de audio (4ª tab)
│   │
│   ├── analysis/                 ← 🎵 ANÁLISIS DE AUDIO
│   │   └── analyzer_service.py   API unificada de análisis (librosa + madmom)
│   │
│   ├── io/                       ← 📦 ENTRADA/SALIDA
│   │   ├── loaders/
│   │   │   └── gdtf_profile.py   Importa fixtures GDTF
│   │   ├── outputs/
│   │   │   └── router.py         OutputRouter + mapeo universos → targets
│   │   └── exporter.py           QLC+ XML + CSV
│   │
│   ├── mcp/                      ← 🤖 MCP BRIDGE (Claude Control)
│   │   ├── mcp_bridge.py         WebSocket JSON-RPC :9876
│   │   └── mcp_show_server.py    FastMCP stdio → Claude Code
│   │
│   ├── viewer3d/                 ← 3️⃣ VISUALIZADOR 3D
│   │   ├── viewer3d_server.py    HTTP :8080 + WS :9877
│   │   ├── index.html
│   │   ├── main.js               Three.js scene + WebSocket
│   │   ├── moving_head.js        MovingHead class + shaders
│   │   └── rig_layout.json       Auto-generado desde FixtureRig
│   │
│   ├── plugins/                  ← 🔌 PLUGIN SYSTEM
│   │   └── effects/
│   │       └── example_plugin.py MeteorShower + Heartbeat (IDs 1000+)
│   │
│   └── utils/                    ← 🛠️ UTILIDADES
│       └── shortcuts.py          Atajos configurables
│
├── tests/                        ← ✅ SUITE DE TESTS (363 tests, 92.6% cobertura)
│   ├── test_analyzer_service.py
│   ├── test_channel_effects.py
│   ├── test_effects_render.py
│   ├── test_gdtf_loader.py
│   ├── test_generation_tools.py
│   ├── test_project_manager.py
│   └── ... (12 archivos de test)
│
├── docs/                         ← 📚 DOCUMENTACIÓN
│   ├── README.md                 Guía user-facing
│   ├── SETUP.md                  Instalación paso a paso
│   ├── CLAUDE.md                 Arquitectura profunda (este es el IMPORTANTE)
│   ├── STRUCTURE.md              Este archivo
│   └── QUICK_START.txt           Inicio rápido (3-5 min)
│
├── data/                         ← 💾 DATOS DEL USUARIO
│   ├── profiles/                 6 fixture profiles JSON (WLED + genéricos)
│   ├── projects/
│   │   └── el_taser/             Proyecto de prueba: "El Taser de Mamá"
│   │       ├── project.json
│   │       ├── show.json
│   │       ├── rig.json
│   │       └── exports/
│   └── analizadas/               Análisis cachés de canciones
│       ├── el_taser_de_mama_remix/
│       ├── billie_eilish_bad_guy/
│       └── ...
│
├── versions/                     ← 🔙 CHECKPOINTS HISTÓRICOS (rollback)
│   ├── v1.0_pre_mcp/
│   ├── v1.6_pre_dmx/
│   ├── v1.7_p{2,3,4,5,6,78}_*/   (9 fases de v1.7)
│   ├── v1.8_p{1,2,3,4,5,6}_*/    (6 fases de v1.8)
│   └── v1.9_p{1,2}_*/            (2 fases de v1.9)
│
├── _legacy/                      ← 📦 ARCHIVOS HISTÓRICOS (no usados)
│   ├── old_scripts/              test_*.py antiguos, scripts one-off
│   └── timeline_editor_versions/ v01-v04 históricos
│
├── 📄 RAÍZ (configuración)
│   ├── requirements.txt          Dependencias Python
│   ├── pytest.ini                Config de tests
│   ├── .coveragerc               Coverage mínimo 60%
│   ├── .gitignore                Patrones Git
│   ├── .mcp.json                 Registro MCP server
│   └── (venv/)                   ← Entorno virtual (crear con `python -m venv venv`)
│
```

---

## 📊 Tamaños y Contenidos

| Carpeta | Tamaño | Contenido |
|---------|--------|----------|
| **src/** | 808 KB | Código fuente (~21 archivos .py) |
| **tests/** | 700 KB | 363 tests pytest (92.6% cobertura) |
| **data/** | 25 MB | Fixtures, proyectos, análisis de audio |
| **versions/** | 4.5 MB | Checkpoints de rollback (v1.0 a v1.9) |
| **docs/** | 64 KB | Documentación (README, SETUP, CLAUDE) |
| **_legacy/** | 324 KB | Archivos históricos (ignorar) |

**Total: ~32 MB** (sin venv de ~200 MB)

---

## 🎯 Dónde encontrar cada cosa

### "Quiero editar la interfaz gráfica"
→ `src/ui/` (timeline_editor.py, feedback_app_with_barras.py, etc.)

### "Quiero entender cómo funcionan los efectos"
→ `src/core/effects_engine.py` (51 efectos pixel) o `src/core/channel_effects.py` (24 DMX effects)

### "Quiero agregar soporte para un nuevo tipo de fixture"
→ `src/io/loaders/gdtf_profile.py` (importar GDTF) o crear `.json` en `data/profiles/`

### "Quiero entender la arquitectura completa"
→ `docs/CLAUDE.md` (documentación profunda con decisiones de diseño)

### "Quiero ejecutar tests"
→ `pytest tests/` (desde la raíz)

### "Quiero exportar a QLC+"
→ `src/io/exporter.py`

### "Quiero que Claude controle la app"
→ `src/mcp/` (MCP bridge + server)

### "Quiero ver los movers en 3D"
→ `src/viewer3d/` (Three.js + shaders)

---

## 🚀 Flujo de arranque típico

```
1. Usuario: python src/ui/dual_app.py
   ↓
2. dual_app.py arranca:
   - Crea ShowEngine (núcleo: src/core/show_engine.py)
   - Arranca viewer3d_server en :8080
   - Arranca mcp_bridge en :9876
   ↓
3. Tabs se conectan al ShowEngine compartido:
   - Timeline editor (src/ui/timeline_editor.py)
   - Feedback (src/ui/feedback_app_with_barras.py)
   - Patch panel (src/ui/patch_panel.py)
   - Analyzer (src/ui/analyzer_panel.py)
   ↓
4. ShowEngine renderiza:
   - Efectos pixel via src/core/effects_engine.py
   - Efectos channel via src/core/channel_effects.py
   - Envía Art-Net via src/io/outputs/router.py
   ↓
5. Viewer 3D (src/viewer3d/) visualiza en tiempo real
```

---

## 🔗 Dependencias internas (imports)

```python
# Desde UI (src/ui/) importan core/analysis/io:
from src.core import show_engine, timeline_model, fixtures
from src.analysis import analyzer_service
from src.io import exporter

# Desde core (src/core/) NO importan UI:
# (así se mantiene bajo acoplamiento)

# MCP (src/mcp/) habla con core via JSON-RPC:
# (no importa directamente, todo por WebSocket)

# Viewer3D (src/viewer3d/) es totalmente JavaScript:
# (se comunica via WebSocket con viewer3d_server)
```

---

## 💡 Principios de organización

1. **Separación por dominio**: UI, core, análisis, I/O, MCP — cada uno toca su área
2. **Bajo acoplamiento**: Core NO conoce Qt. MCP NO toca la base de datos. Etc.
3. **Datos centralizados**: `data/` es source of truth para user data
4. **Tests al lado**: `tests/` refleja la estructura de `src/`
5. **Documentación viva**: `CLAUDE.md` describe decisiones reales

---

¡A programar! 🎨✨
