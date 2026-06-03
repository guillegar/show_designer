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

- **Horizontal axis** — Time (with ruler showing bars/beats/seconds)
- **Vertical axis** — 10 bars + groups + fixtures
- **Clips** — Colored rectangles showing effect instances
  - Drag to move
  - Right-click to edit/delete
  - Double-click to select properties

### Right Panel: Properties

When a clip is selected:

- **Start / Duration** — Timing in ms
- **Layer** — Z-order (higher = priority)
- **Effect selector** — Choose which effect
- **Effect parameters** — Customize (speed, color, etc.)

### Toolbar

- **Transport** — Play, Pause, Stop
- **Project selector** — Switch between shows
- **Export button** — QLC+ or CSV
- **Snap toggle** — Align to beat grid
- **Zoom** — +/- buttons to zoom in/out

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
