# Quick Start 🚀

Get Show Designer Pro running in **5 minutes**.

## Prerequisites

  **Python 3.11+** ([download](https://www.python.org/downloads/))
  **Git** ([download](https://git scm.com/))
  **Windows 10+** or Linux/macOS (experimental)

## Installation

### 1. Clone the repository

```powershell
git clone https://github.com/guillegar/show_designer.git
cd show_designer
```

### 2. Create virtual environment

```powershell
python  m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
pip install  r requirements.txt
```

This installs:
  PyQt5 (UI)
  librosa + madmom (audio analysis)
  demucs (stem separation)
  websockets + fastapi (backend)
  pytest + coverage (testing)

## Running the App

### From terminal

```powershell
python  m server.main
```

### From desktop (Windows)

A shortcut **Show Designer Pro.lnk** is created on your Desktop. Double click to run.

## What you'll see

On startup, you'll see:

```
[init] Library...        ← Loading 51 pixel effects + plugins
[init] Waveform...
[init] Analysis (via AnalysisService)...
[init] Timeline...
[init] ShowEngine...
[+] OutputRouter loaded: 11 routed universes
[dual] Active project: 'El Taser de Mamá Remix'
[dual] MCP bridge started on ws://127.0.0.1:9876
[dual] 3D Viewer started: http://localhost:8000/ (WS :9877)
```

## Open the 3D Viewer

Open your web browser and go to:

```
http://localhost:8000/
```

You'll see:
  10 WLED bars (93 LEDs each)
  4 moving head wash fixtures
  Real time light visualization

## Create your first clip

1. **Go to Timeline tab** (🎨)
2. **Select a Pixel effect** (left panel, "Pixel" tab, e.g., `rainbow_wave`)
3. **Draw mode** — Click the effect, cursor changes to a crosshair
4. **Draw a clip** — Drag horizontally on a bar (track 0 9) to create a clip
5. **Press Space** — Play!

## Control with Claude

If you're using Claude Code:

```python
# These tools are automatically available:
mcp__show control__list_clips
mcp__show control__add_clip
mcp__show control__play
mcp__show control__pause
mcp__show control__analyzer_find_drops
# ... 50+ more tools
```

Ask Claude: *"Add 10 flashes on bar 3 every 5 seconds"*

Claude will create the clips for you.

## Keyboard Shortcuts

| Key | Action |
|     |        |
| **Space** | Play / Pause |
| **S** | Stop |
| **Ctrl+S** | Save show |
| **Ctrl+Z** | Undo |
| **Ctrl+Shift+Z** | Redo |
| **D** | Draw mode |
| **C** | Cut mode |
| **Escape** | Select mode |
| **Q** | Toggle snap |
| **B** | Blackout |

[Full keyboard shortcuts →](usage/shortcuts.md)

## Next Steps

  [📊 Read Features →](features.md)
  [🏗️ Architecture & Advanced →](advanced/architecture.md)
  [📚 Full Documentation →](https://github.com/guillegar/show_designer)
  [🤝 Contributing →](development/contributing.md)

## Troubleshooting

### Port 9876 already in use

```powershell
Get Process python | Stop Process  Force
```

Then restart the app.

### ModuleNotFoundError

Make sure you activated the virtual environment:

```powershell
.\venv\Scripts\Activate.ps1
```

### App is slow / lagging

This is normal on first startup (analyzing audio). Subsequent runs are instant. If persistent:

1. Check CPU usage (should be <20% idle)
2. Check disk I/O (loading large audio files?)
3. Try a smaller test project

### Need help?

  [GitHub Issues](https://github.com/guillegar/show_designer/issues)
  [FAQ](faq.md)
  [Architecture Guide](advanced/architecture.md)

   

**Stuck?** Check the [Installation](installation.md) page for detailed setup instructions.
