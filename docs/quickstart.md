# Quick Start 🚀

Get Show Designer Pro running in **5 minutes**.

## Prerequisites

- **Python 3.11+** ([download](https://www.python.org/downloads/))
- **Git** ([download](https://git-scm.com/))
- **Windows 10/11** (Linux/macOS experimental)
- **Node 18+** — only if you plan to recompile the frontend

## Installation

```powershell
git clone https://github.com/guillegar/show_designer.git
cd show_designer

python -m venv venv311
.\venv311\Scripts\Activate.ps1
pip install -r requirements.txt
```

Main dependencies (see `requirements.txt`): librosa + madmom (audio analysis),
fastapi + uvicorn + websockets (backend), pygdtf (GDTF fixtures), pygame (audio
playback), Pillow, sacn, pyserial, python-osc. `demucs` (stem separation) is optional.

## Run

```powershell
python -m server.main
```

Then open **http://localhost:8000** in your browser — the backend serves the
pre-built frontend (`web/dist`). On Windows you can also double-click **`Luces.bat`**
(clean restart + opens the browser).

On startup you'll see something like:

```
[auth] Sin tokens configurados — todos los handlers accesibles sin autenticación
[web] backend listo · stream + control en :8000 · MCP compat en :9876
```

## Create your first clip

1. Go to the **Timeline** tab
2. Pick a pixel effect from the browser (e.g. `rainbow_wave`) and press **D** (Draw)
3. Drag horizontally on a bar to create a clip
4. Press **Space** to play

## Control with Claude (MCP)

If you use Claude Code, the backend exposes the same JSON-RPC on `:9876` (configured
in `.mcp.json`), so Claude can drive the show with `mcp__show-control__*`:

> "Add 10 flashes on bar 3 every 5 seconds" → Claude creates the clips for you.

## Frontend development (optional)

```powershell
cd web
npm install
npm run dev      # http://localhost:5173 (proxies WebSockets to :8000)
npm run build    # recompiles web/dist
```

## Troubleshooting

**Port already in use (`:8000` / `:9876`)** — another instance is running:

```powershell
Get-Process python | Stop-Process -Force
```

**ModuleNotFoundError** — activate the venv: `.\venv311\Scripts\Activate.ps1`

## Next steps

- [Features →](features.md)
- [UI Guide →](usage/ui-guide.md)
- [Installation (detailed) →](installation.md)
- [Architecture →](advanced/architecture.md)
