# UI Guide 🎨

Visual walkthrough of the four main tabs in Show Designer Pro.

## Tab 1: Timeline Editor

The heart of Show Designer.

### Left Panel: Effect Browser

- **Pixel** tab — LED-strip effects: built-in library + auto-discovered plugins (flash, wave, rainbow, fire, scanner…)
- **Channel** tab — DMX fixture effects (pan-tilt, color, dimmer, strobe)
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
| `Ctrl+E` | Zoom to selection |
| `←` `→` | Nudge selection ±1 grid step (`Shift` = ±1 bar) |
| `↑` `↓` | Move selection to another layer |
| `L` | Toggle A/B loop of the section under the playhead |
| `[` `]` | Adjust default effect duration ±50 ms |
| `Ctrl+C` / `Ctrl+V` | Copy / paste clip |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |
| `Ctrl+A` / `Ctrl+Shift+A` | Select all clips in track / everywhere |
| `Ctrl+Click` | Add/remove clip from selection |
| `Delete` / `Backspace` | Delete selected clip |

### Ruler & playback

- **Drag on the ruler** → define an **A/B loop region** (playback wraps inside it);
  single click inside the region removes it. `L` loops the current section.
- **Double-click on the ruler** → add a marker (inline rename opens right away)
- **Right-click on the ruler** → split all clips at the playhead / duplicate a section
- **⇥ Follow** toolbar toggle → auto-scroll keeps the playhead in view during playback
- While **drawing** a clip you see a live ghost rectangle; in **Cut** mode a scissor
  line follows the cursor. Drags snap to the BPM grid **and to other clips' edges**.
- Multi-selection shows `N sel · X.Xs` in the status bar. Bulk moves/deletes/pastes
  are atomic: one undo step reverts the whole operation.

### Patterns (reusable clip blocks)

A **pattern** is a saved group of clips you can drop repeatedly (e.g. a chorus look).

1. **Select the clips**: click one, then `Ctrl+Click` to add more (or rubber-band drag
   over empty space). The status bar shows the count.
2. **Right-click a selected clip → "Crear pattern (N clips)…"**, type a name, **Crear**.
   (Works from a single clip too.) The clips become one pattern instance.
3. **Reuse** from the left **Patterns** tab: click a pattern to drop an instance at the
   playhead, or drag it onto a track row.
4. Pattern **instances** show as dashed-border blocks. Right-click one → "Disolver en
   clips" (turn back into editable clips) or "Borrar instancia". Editing a pattern
   updates every instance at once.

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

- **Click to select fixtures** · **Drag to move** · **Right-click** for context menu
  (Edit / Duplicate / Identify / Delete)
- **Icons by type**: bars = rectangles, moving heads = circle with crosshair,
  pars/dimmers = circles
- **Zoom** (wheel) · **Pan** (middle button) · **⊡ Fit** button frames all fixtures
- **Multi-select**: Shift+click, rubber-band drag, or Ctrl+A. Bulk toolbar appears:
  Duplicate, Re-patch…, Align H/V, Distribute, Rename…, Delete
- **Keyboard**: arrows nudge selected fixture (Shift = bigger step), Ctrl+D duplicate,
  Delete remove, Esc clear selection
- **Fixture list filters**: universe chips (U1, U2…) + "📍 Sin pos" (unpositioned)
- **📥 Rig** button imports the rig from another project
- **▶ Test** runs a sequential identify on every fixture (click again to stop)
- **DMX map**: 512-channel bar per universe; free gaps shown with tooltips
- **Fixture editor**: full properties (label, universe/address, IP, rotation, notes,
  channel map) with live conflict detection

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
