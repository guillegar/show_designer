# Features ✨

## Timeline Editor

- **Multi-track timeline** with waveform, bar/beat/second ruler
- **Drag-and-drop clips** — create, move, copy, paste, delete
- **Snap to beats/bars** — precise timing aligned to music
- **Undo/Redo** — never lose work
- **Layers** — clip layering with LTP (Highest Priority) mixing
- **Lock/Unlock** — protect clips from accidental edits
- **Cue points** — 10 searchable cue slots (0-9) for live triggering
- **Markers** — custom section markers

## Effects Library

### 51 Pixel Effects (LED Strips)

For WLED bars and LED strips:

- **Flash** — single pulse or strobe
- **Wave** — linear or circular waves
- **Rainbow** — color cycling, phase shifting
- **Strobe** — frequency-controllable
- **Gradient** — color gradients with speed
- **Pattern** — geometric patterns
- **Spectral** — audio-reactive frequency bands
- **Chase** — moving chase patterns
- **Pulse** — intensity breathing
- **Glitch** — digital distortion effects
- **Plus 40 more...** (fire, plasma, kaleidoscope, etc.)

### 24 Channel Effects (DMX Fixtures)

For movers, wash, beam, strobe:

**Position** (6 effects)
- Circle, spiral, figure-8, random, pan sweep, tilt sweep

**Color** (6 effects)
- Rainbow, complementary, split complementary, analogous, hue shift, random

**Intensity** (4 effects)
- Pulse, flicker, strobe, ramp

**Optical** (5 effects)
- Gobo select, gobo rotation, frost, iris, focus

**Strobe** (3 effects)
- Single, double, random strobe

## Audio Analysis

**Automatic detection** via librosa + madmom + demucs:

- 🎵 **Beats** — precise beat grid
- 📍 **Downbeats** — measure-level timing
- 📊 **Sections** — intro, verse, chorus, drop, breakdown, bridge, outro
- 🎚️ **Features** — MFCC, chroma, spectral centroid, energy
- 🎤 **Stems** — vocals, drums, bass, other (via demucs)
- 🎯 **Events** — kicks, snares, hats (via madmom)

**Non-destructive curation** — edit section labels and event thresholds without re-analyzing.

## 3D Visualization

Real-time Three.js viewer:

- 📺 **Bloom & Fog** — cinematic rendering
- 🌀 **OrbitControls** — mouse camera control
- 💡 **10 WLED bars** — 93 LEDs each, reacting to clips
- 🎪 **4 Moving heads** — wash fixtures with pan/tilt/color response
- 🔦 **Volumetric beams** — realistic beam visualization
- 📡 **DMX-responsive** — fixtures react to manual channels

## Multi-Project Support

Organize shows by project:

```
projects/
├── el_taser/
│   ├── project.json      ← metadata
│   ├── rig.json          ← fixtures
│   ├── show.json         ← timeline + clips
│   ├── feedback.json     ← saved feedback state
│   └── presets.json      ← clip presets
├── my_event/
└── ...
```

- Quick switch between projects
- Each project has its own rig and timeline
- Auto-save on project switch

## Export Options

### QLC+ XML

Export your show as a QLC+ workspace:
- Fixtures
- Scenes (per cue)
- Chasers (clip sequences)

Load in QLC+ for live playback or further editing.

### CSV Export

**Clips CSV**
```
clip_id, bar, track, start_ms, duration_ms, effect_id, params
0,      3,   0,     12000,    5000,       51,        color=red,speed=0.5
```

**DMX CSV**
```
time_ms, universe, channel, value
0,      1,        1,       255
50,     1,        1,       200
...
```

## Plugin System

Create custom effects easily:

```python
# plugins/effects/my_effect.py
from src.core.effects_engine import Effect, EffectScope

class MyEffect(Effect):
    name = "my_effect"
    family = "custom"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    
    def render(self, elapsed_time, bars_state, audio_context, **params):
        # Your logic here
        return bars_state

PLUGIN_EFFECTS = {1010: MyEffect()}
```

Plugins are auto-discovered on startup. No restart needed for reload.

## MCP Control (Claude Integration)

50+ JSON-RPC tools for Claude:

- **Transport** — play, pause, stop, seek, blackout
- **Clips** — list, add, move, delete, edit
- **Generator** — generate_section, mirror_clips, apply_palette
- **Analyzer** — find drops, find breakdowns, get features
- **Rig** — list fixtures, add fixture, move fixture
- **Persistence** — save/load shows

Ask Claude: *"Create a 30-second drop effect on bars 1-5"* → Claude generates the clips for you.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| **Space** | Play / Pause |
| **S** | Stop |
| **Ctrl+S** | Save |
| **Ctrl+O** | Open |
| **Ctrl+Z / Ctrl+Shift+Z** | Undo / Redo |
| **Ctrl+C / Ctrl+V** | Copy / Paste |
| **Ctrl+L / Ctrl+U** | Lock / Unlock |
| **D / C / Esc** | Draw / Cut / Select |
| **Q** | Toggle snap |
| **B** | Blackout |
| **+/-** | Zoom in/out |

[Full list →](usage/shortcuts.md)

## Performance

- ✅ 363 tests (92.6% coverage)
- ✅ Headless backend ready (v1.10)
- ✅ 30 FPS render pipeline
- ✅ Real-time DMX output
- ✅ Sub-10ms clip calculation

---

**Want to dive deeper?** → [Architecture Guide](advanced/architecture.md)
