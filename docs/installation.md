# Installation Guide 📥

Complete step-by-step installation instructions.

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **OS** | Windows 10 | Windows 11 |
| **Python** | 3.11 | 3.12 |
| **RAM** | 4 GB | 8 GB |
| **Disk** | 2 GB (with venv) | 5 GB |

Linux and macOS are supported but not actively tested. **Node 18+** is only needed
to recompile the frontend.

## Step 1: Install Python

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download **Python 3.11** or **3.12**
3. Run the installer and **check "Add Python to PATH"**

Verify:
```powershell
python --version
# Python 3.12.0
```

## Step 2: Install Git

Download from [git-scm.com](https://git-scm.com/) and install with defaults.

```powershell
git --version
```

## Step 3: Clone the repository

```powershell
cd C:\Users\YourName\Documents
git clone https://github.com/guillegar/show_designer.git
cd show_designer
```

## Step 4: Create the virtual environment

```powershell
python -m venv venv311
```

## Step 5: Activate it

### Windows (PowerShell)
```powershell
.\venv311\Scripts\Activate.ps1
```

If PowerShell blocks the script:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Windows (Command Prompt)
```cmd
.\venv311\Scripts\activate.bat
```

### Linux/macOS
```bash
source venv311/bin/activate
```

You should see `(venv311)` at the start of your prompt.

## Step 6: Install dependencies

```powershell
pip install -r requirements.txt
```

This installs (see `requirements.txt`):

- **librosa** + **madmom** — audio analysis
- **fastapi** + **uvicorn** + **websockets** — headless backend
- **pygdtf** — GDTF fixture loader
- **pygame** — audio playback (master clock)
- **Pillow**, **sacn**, **pyserial**, **python-osc** — I/O
- **pytest** — testing

`demucs` (optional stem separation) is not installed by default. Installation
takes ~2–3 minutes.

## Step 7: Verify

```powershell
python -c "import librosa; print('librosa OK')"
python -c "import fastapi; print('fastapi OK')"
python -c "import pytest; print('pytest OK')"
```

All should print "OK".

## Step 8: Run

```powershell
python -m server.main
```

You should see:
```
[auth] Sin tokens configurados — todos los handlers accesibles sin autenticación
[web] backend listo · stream + control en :8000 · MCP compat en :9876
```

## Step 9: Open the app

Open your browser at **http://localhost:8000/** — you'll see the views
(Timeline, Live, Analyzer, Patch, Viewer3D) served by the headless backend.

On Windows you can also use the launchers: `Luces.bat`, `Luces Espana.bat`,
`Luces Barras.bat`, `Luces Red Sun.bat`.

## Troubleshooting

### "Python not found"
Ensure Python is on your PATH (`python --version`). Reinstall and check
"Add Python to PATH" if needed.

### "venv not found"
You're in the wrong directory. `cd` into `show_designer/` (it should contain
`server/`, `web/`, `tests/`, `README.md`).

### "ModuleNotFoundError"
Activate the venv and reinstall:
```powershell
.\venv311\Scripts\Activate.ps1
pip install -r requirements.txt
```

### "Port 8000 / 9876 already in use"
Another instance is running:
```powershell
Get-Process python | Stop-Process -Force
```

### Path has spaces
```powershell
& "C:\Program Files\Python312\python.exe" -m venv venv311
```

## Next steps

- [Quick Start →](quickstart.md)
- [Features →](features.md)
- [UI Guide →](usage/ui-guide.md)

**Still stuck?** Open a [GitHub Issue](https://github.com/guillegar/show_designer/issues).
