# 3D Viewer Guide 📺

Real-time visualization of your light show using Three.js.

## Opening the Viewer

1. **Run Show Designer**: `python -m server.main`
2. **Open browser**: http://localhost:8000/
3. You should see 10 WLED bars + 4 moving heads

## Features

- **Real-time rendering** — Updates at 30 FPS
- **Bloom & Fog** — Cinematic lighting effects
- **ACES Tonemapping** — Realistic color grading
- **Interactive camera** — Orbit controls (drag to rotate, scroll to zoom)
- **DMX response** — Fixtures react to channel values

## Controls

| Action | Control |
|--------|---------|
| **Rotate camera** | Drag with left mouse button |
| **Pan camera** | Right-click drag (or middle mouse) |
| **Zoom** | Scroll wheel |
| **Reset camera** | Double-click |
| **Toggle fullscreen** | F key |

## What You See

### WLED Bars

- 10 bars with 93 LEDs each
- Arranged in rows
- Colors match exact RGB output
- Updates in real-time during playback

### Moving Heads

- 4 wash fixtures
- Pan/Tilt controlled by DMX
- Color reactive (red, green, blue channels)
- Beam visualization (volumetric shader)

## Debugging

The viewer helps debug:

- **Are the LEDs lighting up?** → Check connections
- **Wrong colors?** → Check RGB order in WLED settings
- **Movers not responding?** → Check DMX universe routing
- **Fixtures missing?** → Check `fixtures.json`

## Performance

- **GPU required** — Uses WebGL
- **Target 60 FPS** — May drop on older GPUs
- **~1MB per frame** — Network bandwidth for streaming

## Auto-Layout

The viewer auto-generates `viewer3d/rig_layout.json` from `fixtures.json`. When you add/move fixtures in the Patch tab, the layout updates automatically.

## Architecture

- **Server**: served by the main backend (`server/web.py`; static files in `web/public/v3d/`)
- **Client**: `viewer3d/main.js` + `moving_head.js` (Three.js)
- **Communication**: WebSocket (frame streaming + DMX state)

## Customization

For advanced customization (camera position, lighting, etc.), edit `viewer3d/main.js`.

---

**Trouble seeing lights?** Check:
1. Is Show Designer running?
2. Is port 8080 open?
3. Browser console (F12) for errors
4. Try refreshing (F5)

---

See [Architecture Guide](architecture.md) for technical details.
