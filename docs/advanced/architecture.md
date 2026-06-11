# Architecture Guide 🏗️

High-level overview of Show Designer Pro's architecture. For detailed technical documentation, see [CLAUDE.md](https://github.com/guillegar/show_designer/blob/master/CLAUDE.md).

## Design Principles

1. **Low Coupling** — Modules are independent and composable
2. **High Cohesion** — Related functionality stays together
3. **Headless Backend** — Core logic separate from UI
4. **Plugin-Friendly** — Custom effects and tools via plugins

## Core Components

```
┌─────────────────────────────────────────────────────┐
│                   Show Designer Pro                  │
├─────────────────────────────────────────────────────┤
│ Timeline Model                                       │
│   ├── Clip (effect instance with params)           │
│   ├── BarGroup (logical grouping)                  │
│   ├── CuePoint (10 cue slots)                      │
│   └── Timeline (container of clips/groups)          │
│                                                      │
│ Show Engine                                          │
│   ├── Timeline Scheduler (when to play clips)      │
│   ├── Effect Renderer (calculate LED colors)       │
│   ├── Channel Assembler (pack DMX data)            │
│   └── Output Router (send to hardware)             │
│                                                      │
│ Fixture System                                       │
│   ├── FixtureProfile (capabilities, channels)      │
│   ├── Fixture (instance with position, DMX addr)   │
│   └── FixtureRig (collection of fixtures)          │
│                                                      │
│ Effects Library                                      │
│   ├── 51 Pixel Effects (LED strips)                │
│   ├── 24 Channel Effects (DMX)                     │
│   └── Plugin System (custom effects)               │
│                                                      │
│ Audio System                                         │
│   ├── AnalysisService (beats, sections, features) │
│   ├── Curation (non-destructive editing)           │
│   └── AudioContext (passes features to effects)    │
│                                                      │
│ I/O                                                  │
│   ├── ProjectManager (multi-project support)       │
│   ├── Exporters (QLC+, CSV)                        │
│   ├── Loaders (GDTF, JSON profiles)               │
│   └── OutputRouter (WLED, Art-Net, sim)           │
│                                                      │
│ UI (PyQt5 — being deprecated)                       │
│   ├── Timeline Editor (drag-drop clips)            │
│   ├── Feedback App (live preview)                  │
│   ├── Patch Panel (2D rig editor)                  │
│   └── Analyzer (audio analysis UI)                 │
│                                                      │
│ MCP Server                                           │
│   ├── Bridge (WebSocket :9876)                     │
│   └── 50+ JSON-RPC tools for Claude               │
│                                                      │
│ 3D Viewer                                            │
│   ├── Three.js scene (HTTP :8080)                  │
│   └── Real-time fixture visualization             │
└─────────────────────────────────────────────────────┘
```

## Data Flow

### Playback

```
Timeline.clips
    ↓
ShowEngine.compute_frame()
    ├── Schedule: which clips are active?
    ├── Render: calculate colors from effects
    ├── Mix: combine colors (LTP mixing)
    └── Assemble: pack into DMX universes
    ↓
OutputRouter.send_universe()
    ├── WLED devices (Art-Net)
    ├── DMX nodes (Art-Net→RS485)
    └── Simulator (3D viewer)
```

### User Interaction

```
UI Click (timeline, patch, etc.)
    ↓
PyQt Signal
    ↓
Show Engine Method
    ├── Mutate model (add/remove/move clip)
    ├── Schedule re-render
    └── Emit signal
    ↓
UI Refresh
    └── Display new state
```

### Claude Control

```
Claude (natural language)
    ↓
MCP Tool Call
    (e.g., mcp__show-control__add_clip)
    ↓
mcp_bridge.py Handler
    ├── Parse JSON-RPC
    ├── Call ShowEngine method
    ├── Return result
    └── Broadcast update via WebSocket
    ↓
UI Updates
    └── Display Claude's changes
```

## Key Abstractions

### Clip

A clip is an instance of an effect at a specific time:

```python
class Clip:
    clip_id: str          # Unique ID
    effect_id: int        # Which effect?
    start_ms: int         # When?
    duration_ms: int      # How long?
    track: int            # Which bar/group? (-1 for channel)
    layer: int            # Z-order (for mixing)
    category: str         # 'pixel' or fixture type
    channel_effect_id: int  # For DMX fixtures
    params: dict          # Effect-specific parameters
    label: str            # User-facing name
```

### Effect

An effect calculates colors or channel values:

```python
class Effect:
    name: str             # Unique name
    family: str           # Grouping (flash, wave, etc.)
    duration_ms: int      # Default length
    scope: EffectScope    # ALL_BARS, PER_BAR or GLOBAL

    def render(self, elapsed_time, bars_state, audio_context, **params):
        # Returns an RGB array whose shape is fixed by `expected_output_shape`
        # (derived from scope): PER_BAR -> (1, LEDS, 3) (engine assigns it to the
        # clip's bar); ALL_BARS/GLOBAL -> (NUM_BARS, LEDS, 3) (full frame).
        ...
```

### Fixture

A fixture is a physical or virtual light:

```python
class Fixture:
    fixture_id: str       # "bar_0" or "mover_1"
    profile_id: str       # Which profile? (LED vs mover vs wash)
    universe: int         # Which Art-Net universe?
    dmx_start: int        # Starting DMX channel
    label: str            # "Front Left Bar"
    position: [x, y, z]   # 3D coordinates
```

## Threading & Timing

Show Designer uses:

- **Main thread** — Qt event loop (UI responsiveness)
- **Render thread** — 30 FPS calculation of frames
- **Background thread** — MCP WebSocket (external control)
- **Async thread** — Audio playback (pygame.mixer)

All mutations go through `QTimer.singleShot(0, fn)` to serialize Qt calls.

## Persistence

Projects are stored as JSON:

```
projects/el_taser/
├── project.json    # Metadata (name, BPM, duration)
├── show.json       # Timeline + clips
├── rig.json        # Fixtures
├── presets.json    # Saved clip presets
└── feedback.json   # UI state
```

Analysis is cached in:

```
analizadas/el_taser/
├── analysis.json       # Beats, sections, features (regenerable)
├── curation.json       # User edits (never overwritten)
├── timeseries.npz      # Raw audio features
└── stems/              # Demucs stem separation
```

## Extensibility

### Adding a Pixel Effect

1. Create class inheriting `Effect`
2. Implement `render()` method
3. Add to `BUILTIN_EFFECTS` or plugin folder
4. Appears in browser automatically

### Adding a Channel Effect

1. Create class inheriting `ChannelEffect`
2. Implement `render()` method
3. Add to `CHANNEL_EFFECTS` or plugin folder
4. Appears for compatible fixture types

### Adding an MCP Tool

1. Add handler in `mcp_bridge.py`
2. Register in `tools` dict
3. Returns JSON-RPC result
4. Appears in Claude automatically

### Adding Hardware Output

1. Subclass `OutputTarget`
2. Implement `send_universe()` method
3. Register in `output_targets.json`
4. OutputRouter uses it automatically

## Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| Render 100 clips | <16ms | At 30 FPS |
| Add/remove clip | <1ms | Instant |
| Load project | ~500ms | Including audio analysis cache load |
| Audio analysis (new) | ~30s per 3min | One-time; cached after |
| Art-Net send | ~5ms | To 10 WLED bars + 4 movers |

## Testing

All components have unit tests:

```python
# tests/test_show_engine.py
def test_render_calculates_correct_colors():
    ...

# tests/test_effects_render.py
def test_all_51_effects_render_without_error():
    ...

# tests/test_output_router.py
def test_router_sends_correct_universes():
    ...
```

**Target**: 95%+ coverage. Currently 92.6%.

## Future Architecture Changes

**Planned for v1.10+**:

- Headless backend (remove Qt dependency)
- Web UI (React + Vite)
- Async/await throughout
- WebSocket real-time collab
- Distributed rendering (multiple backends)

---

## Where to Find Code

| Component | Location |
|-----------|----------|
| Timeline | `src/core/timeline_model.py` |
| Show Engine | `src/core/show_engine.py` |
| Fixtures | `src/core/fixtures.py` |
| Pixel Effects | `src/core/effects_engine.py` |
| Channel Effects | `src/core/channel_effects.py` |
| Analysis | `src/analysis/analyzer_service.py` |
| UI | `src/ui/{dual_app,timeline_editor}.py` |
| MCP | `src/mcp/{mcp_bridge,mcp_show_server}.py` |
| 3D Viewer | `src/viewer3d/viewer3d_server.py` |
| Output Router | `src/io/outputs/router.py` |

---

## Design Decisions (& Why)

See [CLAUDE.md Section 4](https://github.com/guillegar/show_designer/blob/master/CLAUDE.md#4-decisiones-tomadas-y-el-porqué) for detailed rationale on:

- Low coupling between components
- Python + PyQt5 (not Chromium)
- Art-Net as primary output
- Separate timeline/feedback stream
- Plugin system architecture
- And more...

---

**Questions?** Check the [FAQ](../faq.md) or email guille@example.com
