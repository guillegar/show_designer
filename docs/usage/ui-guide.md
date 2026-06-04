# UI Guide 🎨

Visual walkthrough of the four main tabs in Show Designer Pro.

## Tab 1: Timeline Editor

The heart of Show Designer.

### Left Panel: Effect Browser

- **Pixel** tab — 51 effects for LED strips (flash, wave, rainbow, etc.)
- **Channel** tab — 24 effects for DMX fixtures (position, color, intensity, etc.)
- Click an effect → cursor changes to crosshair
- Drag on timeline to create a clip

### Center: Timeline

- **Horizontal axis** — Time (BPM-synced grid; the grid density adapts to zoom)
- **Vertical axis** — 10 bars (each with stackable layers) + fixture lanes
- **Clips** — Colored rectangles showing effect instances. In **Select** mode:
  - **Click + drag horizontally** → move in time (snaps to the BPM grid, with guide lines)
  - **Click + drag vertically** → move to another **bar (track)** and/or **layer**;
    the clip follows the cursor and the destination row is highlighted
  - **Drag the left/right edge** → resize
  - **Drag over empty space** → rubber-band multi-select
  - Right-click → context menu (duplicate, mirror, split, mute, lock, delete)
  - Locked clips can't be moved or resized
- In **Draw** mode: click an existing clip to repaint it with the selected effect.

### Keyboard shortcuts (press `?` in the timeline for the full list)

| Key | Action |
|-----|--------|
| `V` / `D` / `B` / `C` | Select / Draw / Draw / Cut tool |
| `Q` | Toggle snap |
| `+` `−` / `Ctrl+0` | Zoom in/out (2–50×) / reset zoom |
| `[` `]` | Adjust default effect duration ±50 ms |
| `Ctrl+C` / `Ctrl+V` | Copy / paste clip |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |
| `Ctrl+A` / `Ctrl+Shift+A` | Select all clips in track / everywhere |
| `Ctrl+Click` | Add/remove clip from selection |
| `Delete` / `Backspace` | Delete selected clip |

### Right Panel: Properties (adaptive inspector)

When a clip is selected the inspector shows, sized to the effect's parameters:

- **Duration** — click to edit inline
- **Effect selector** — choose which effect
- **Scope** and **Color**
- **Effect parameters** — customize (speed, hue, etc.)
- **Lock / Mute / Delete** actions

### Toolbar

- **Transport** — Play, Pause, Stop
- **Tools** — Select / Draw / Cut + Undo/Redo
- **Snap toggle** + grid selector (bar / beat / ½ / ¼ / free)
- **Zoom** — −/value/+ and reset (Ctrl+0)
- **Last duration** indicator (the duration new painted clips inherit)
- **Generate / Export** — QLC+ or CSV

## Tab 2: Feedback + Bars WLED

Live preview of what's being sent to hardware.

- **10 LEDs strips** rendered in real-time
- Shows exact RGB values per LED
- Updates at 30 FPS while playing
- Useful for debugging color/brightness issues

## Tab 3: Patch Panel

2D top-down view of your rig.

- **Click to select fixtures**
- **Right-click to edit** DMX channels
- **Drag to move** fixtures around
- **Channel sliders** for manual testing

## Tab 4: Analyzer

Audio analysis and waveform editor.

- **Waveform** display with overlays
- **Toggle visibility**:
  - Beats (green)
  - Downbeats (red)
  - Sections (yellow background)
  - Events: kicks, snares, hats, onsets
- **Edit sections** in table below
- **Add manual events** with right-click
- **"Apply to Timeline"** button to sync with timeline

---

See [Keyboard Shortcuts](shortcuts.md) for keyboard commands.

**First time?** Start with [Quick Start](../quickstart.md).
