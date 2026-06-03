# Show Designer Pro

Software profesional de control de iluminación en Python + PyQt5, controlable
tanto por humano (UI estilo Adobe / FL Studio) como por Claude (vía MCP).

**Versión actual**: v1.9 F2 (drag-create de channel clips + estabilidad anti-crash)
**Tests**: 363/363 verdes · **Cobertura**: 92.6%
**Licencia**: GPL-3.0

---

## Características principales

- **Timeline editor multi-pista** con waveform, ruler de bars/beats/segundos,
  clips arrastrables, snap a beats/bars, undo/redo, layers, locks.
- **51 efectos pixel** para tiras LED (flash, wave, gradient, pattern, spectral)
  + **plugins** autodescubiertos en `plugins/effects/*.py`.
- **24 channel effects** para fixtures DMX (movers, wash, beam, strobe)
  organizados en 5 categorías: position, color, intensity, optical, strobe.
- **Análisis de audio** offline con librosa + madmom + demucs: beats, downbeats,
  secciones, kicks/snares, MFCC/chroma, stems. Curación humana persistente.
- **Output**: Art-Net (UDP 6454) hacia barras WLED y nodos Art-Net→DMX para
  fixtures convencionales. 11 universos enrutados configurables.
- **Visualizador 3D** integrado (Three.js) con bloom, fog, fixtures
  reaccionando a DMX real en tiempo real.
- **Multi-proyecto**: cada show en `projects/<slug>/` con su rig, timeline
  y referencias a audio/análisis.
- **MCP server**: Claude controla la app vía 50+ tools JSON-RPC sobre WebSocket
  (`mcp__show-control__*`).
- **Export**: QLC+ XML workspace, CSV de clips, CSV DMX frame-a-frame.

---

## Arranque rápido

### Desde el escritorio
Doble-click en **Show Designer Pro.lnk** (creado en `~/Desktop/`).

### Desde terminal
```powershell
cd C:\Users\guille\Documents\Claude\Projects
python dual_app.py
```

Al arrancar verás:
```
[init] Library...        ← 51 efectos pixel + plugins
[init] Waveform...
[init] Analysis (via AnalysisService)...
[init] Timeline...
[init] ShowEngine...
[init] Rig cargado de fixtures.json: 14 fixtures
[+] OutputRouter cargado: 11 universos enrutados
[dual] Proyecto activo: 'El Taser de Mamá Remix'
[dual] MCP bridge arrancado en ws://127.0.0.1:9876
[dual] Viewer 3D arrancado: http://localhost:8080/  (WS :9877)
```

Abrir el viewer 3D en el navegador: `http://localhost:8080/`

---

## Uso básico de la UI

### Las 4 tabs principales

1. **🎨 Timeline Editor** — donde se construye el show. Browser de efectos a la
   izquierda, timeline al centro, propiedades a la derecha.
2. **📊 Feedback + Barras WLED** — preview en vivo de lo que sale por Art-Net,
   estado por barra.
3. **🎯 Patch** — vista top-down 2D del rig: arrastrar fixtures, editar
   canales DMX manualmente.
4. **🎵 Analyzer** — waveform con overlays de beats/sections/kicks editables.

### Crear clips en el timeline

**Pixel clips (barras LED, grupos)**
1. Tab "🎨 Pixel" del browser de efectos
2. Click sobre un efecto (ej. `rainbow_wave`)
3. Cursor cambia a cruz, label "✏ DRAW: rainbow_wave" en verde
4. Arrastra horizontalmente sobre una barra (track 0..9) o un grupo

**Channel clips (movers, wash, beam, strobe)**
1. Tab "⬡ Channel" del browser de efectos
2. Click sobre un efecto (ej. `pos_circle`, `col_rainbow`)
3. Cursor cambia a cruz, label "⬡ DRAW: pos_circle" en naranja
4. Arrastra horizontalmente sobre una **fixture lane** (al fondo del timeline,
   debajo de los grupos)

El sistema avisa con un warning amarillo si intentas dibujar un pixel effect
en una fixture lane o viceversa.

### Atajos de teclado clave

| Tecla | Acción |
|-------|--------|
| `Space` | Play/Pause |
| `S` | Stop |
| `Ctrl+S` | Guardar show (en `projects/<slug>/show.json`) |
| `Ctrl+O` | Abrir show desde archivo |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / Redo |
| `Ctrl+C` / `Ctrl+V` | Copy / Paste clips |
| `Ctrl+L` / `Ctrl+U` | Lock / Unlock |
| `D` / `C` / `Escape` | Modo Draw / Slice / Select |
| `Q` | Toggle Snap |
| `B` | Blackout |
| `+` / `-` | Zoom in/out |
| `Ctrl+0..9` | Saltar a cue point |
| `Shift+0..9` | Crear cue point en cursor |
| `Ctrl+1..4` | Cambiar tab Timeline/Feedback/Patch/Analyzer |
| `Ctrl+M` | Tab Analyzer (mnemónico "Music") |

### Multi-proyecto

Botón **📁 \<Nombre del proyecto\>** en la toolbar → dropdown:
- Lista de proyectos disponibles en `projects/`
- "📂 Abrir proyecto…" — cargar uno existente
- "🆕 Nuevo proyecto…" — crear desde audio + slug + nombre

Cambiar de proyecto guarda el actual y carga el nuevo en caliente (no hace
falta reiniciar).

### Exportar

Botón **📤 Exportar ▾** en la toolbar:
- **CSV** — lista de clips con metadatos (clip_id, track, start_ms, effect_id, …)
- **QLC+ XML workspace (.qxw)** — fixtures + scenes por cue + chaser

Se guardan en `projects/<slug>/exports/`.

---

## Control desde Claude (MCP)

`mcp_show_server.py` está registrado en `.mcp.json`. Cuando arranca Claude Code,
se lanza automáticamente y expone tools como:

- **Transport**: `play`, `pause`, `stop`, `seek`, `blackout`
- **Clips**: `list_clips`, `add_clip`, `add_channel_clip`, `move_clip`, `delete_clip`
- **Generation**: `generate_section`, `mirror_clips_lr`, `apply_palette_to_range`
- **Analyzer**: `analyzer_summary`, `analyzer_list_sections`, `analyzer_find_drops`…
- **Rig**: `list_fixtures`, `add_fixture`, `move_fixture`, `set_fixture_channel`
- **Persistencia**: `save_show`, `load_show`, `save_rig`

Ver `CLAUDE.md` (sección 7) para la lista completa.

---

## Crear plugins de efectos

Cualquier `.py` en `plugins/effects/` se auto-descubre al arrancar:

```python
# plugins/effects/mi_plugin.py
from effects_engine import Effect, EffectScope, EffectGeometry, EffectSymmetry

class MiEfecto(Effect):
    name        = "mi_efecto"
    family      = "custom"
    duration_ms = 2000
    scope       = EffectScope.ALL_BARS
    geometry    = EffectGeometry.GEOMETRY_3D
    symmetry    = EffectSymmetry.ASYMMETRIC
    description = "Mi efecto personalizado"

    def render(self, elapsed_time, bars_state, audio_context, **params):
        import numpy as np
        out = bars_state.copy()
        # ... lógica del efecto ...
        return out

PLUGIN_EFFECTS = {1010: MiEfecto()}   # IDs >= 1000 para plugins
```

Reiniciar la app → el efecto aparece en el browser tab "Pixel" en su familia.

---

## Tests

```powershell
python -m pytest tests/ -q
# → 363 passed in ~5s
```

Con cobertura:
```powershell
python -m pytest tests/ --cov --cov-report=term
# → 92.60% (objetivo CI: >= 60%)
```

CI en GitHub Actions: `.github/workflows/ci.yml`.

---

## Estructura del repo

```
Projects/
├── README.md                  ← este archivo
├── CLAUDE.md                  ← guía profunda de la arquitectura
├── .mcp.json                  ← registro del MCP server
├── .gitignore
├── .coveragerc
├── pytest.ini
│
├── dual_app.py                ← entry point (4 tabs)
├── timeline_editor.py         ← UI Timeline (~3500 LOC)
├── timeline_model.py          ← Clip, BarGroup, CuePoint, Timeline
├── show_engine.py             ← Scheduler + Assembler + Router
├── effects_engine.py          ← 51 efectos pixel + loader plugins
├── channel_effects.py         ← 24 channel effects (movers, etc.)
├── fixtures.py                ← FixtureRig + Profile + Fixture
├── analyzer_service.py        ← API unificada al análisis de audio
├── analyzer_panel.py          ← Tab Analyzer
├── feedback_app_with_barras.py ← Tab Feedback
├── patch_panel.py             ← Tab Patch (2D top-down)
├── project_manager.py         ← Multi-proyecto
├── exporter.py                ← QLC+ XML, CSV
├── mcp_bridge.py              ← WebSocket :9876 (server)
├── mcp_show_server.py         ← stdio MCP (client de Claude)
├── viewer3d_server.py         ← HTTP :8080 + WS :9877
├── shortcuts.py               ← Atajos configurables
│
├── profiles/                  ← Profiles de fixtures (JSON + GDTF)
├── loaders/                   ← Cargadores GDTF
├── outputs/                   ← Router DMX → WLED/Art-Net/sim
├── plugins/effects/           ← Plugins de efectos pixel
├── analizadas/                ← Análisis por canción
├── projects/                  ← Shows organizados por proyecto
├── shows_saved/               ← Shows exportados (legacy)
├── tests/                     ← 363 tests pytest
├── viewer3d/                  ← Cliente JS del viewer (Three.js)
├── .github/workflows/         ← CI
├── versions/                  ← Checkpoints v1.x_pN_*
└── _legacy/                   ← Scripts antiguos archivados
```

---

## Hardware soportado actualmente

- **10 barras WLED** (93 LEDs cada una) en universos Art-Net 1..10
  (IPs `192.168.1.201..210`)
- **4 movers wash** (16 canales DMX cada uno) en universo 11, DMX start
  1/17/33/49 — actualmente en modo simulado (sim_only) hasta tener nodo
  Art-Net→DMX físico

Para añadir hardware: ver `profiles/`, `output_targets.json` y la tab Patch.

---

## Más información

- **Arquitectura profunda**: `CLAUDE.md`
- **Checkpoints históricos**: `versions/*/CHANGELOG.md`
- **Estado en vivo**: `versions/v1.9_p2_stabilization/CHANGELOG.md`
