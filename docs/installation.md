# Installation Guide 📥

Complete step-by-step installation instructions.

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **OS** | Windows 10 | Windows 11 |
| **Python** | 3.11 | 3.12 |
| **RAM** | 4 GB | 8 GB |
| **Disk** | 2 GB (with venv) | 5 GB |

Linux and macOS are supported but not actively tested.

## Step 1: Install Python

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download **Python 3.11** or **3.12**
3. Run installer, **check "Add Python to PATH"**
4. Click Install

Verify:
```powershell
python --version
# Python 3.12.0
```

## Step 2: Install Git

1. Go to [git-scm.com](https://git-scm.com/)
2. Download and run installer
3. Use default options

Verify:
```powershell
git --version
# git version 2.42.0
```

## Step 3: Clone the Repository

```powershell
# Navigate to where you want the project
cd C:\Users\YourName\Documents

# Clone
git clone https://github.com/guillegar/show_designer.git
cd show_designer
```

## Step 4: Create Virtual Environment

```powershell
python -m venv venv
```

This creates a `venv/` folder with isolated Python packages.

## Step 5: Activate Virtual Environment

### Windows (PowerShell)
```powershell
.\venv\Scripts\Activate.ps1
```

If you get an error about execution policies:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then try `Activate.ps1` again.

### Windows (Command Prompt)
```cmd
.\venv\Scripts\activate.bat
```

### Linux/macOS
```bash
source venv/bin/activate
```

You should see `(venv)` at the start of your terminal line.

## Step 6: Install Dependencies

```powershell
pip install -r requirements.txt
```

This installs:
- **PyQt5** — UI framework
- **librosa** — audio analysis
- **madmom** — beat tracking
- **demucs** — stem separation
- **pygdtf** — GDTF fixture loader
- **websockets** — WebSocket server
- **fastapi** — Web framework
- **pytest** — Testing

Wait for installation to complete (~2-3 minutes).

## Step 7: Verify Installation

```powershell
python -c "import PyQt5; print('PyQt5 OK')"
python -c "import librosa; print('librosa OK')"
python -c "import pytest; print('pytest OK')"
```

All should print "OK".

## Step 8: Run the Application

```powershell
python src/ui/dual_app.py
```

You should see:
```
[init] Library...
[init] Waveform...
[init] Analysis (via AnalysisService)...
[+] OutputRouter loaded: 11 routed universes
[dual] MCP bridge started on ws://127.0.0.1:9876
[dual] 3D Viewer started: http://localhost:8080/
```

## Step 9: Open 3D Viewer

Open your web browser and go to:
```
http://localhost:8080/
```

You should see the 3D scene with WLED bars and moving head fixtures.

---

## Troubleshooting

### "Python not found"

Make sure Python is in your PATH:

```powershell
python --version
```

If not found, reinstall Python and check "Add Python to PATH".

### "venv not found"

You may be in the wrong directory. Make sure you're in the `show_designer/` folder:

```powershell
cd C:\path\to\show_designer
ls  # Should see: venv, src, tests, README.md, etc.
```

### "ModuleNotFoundError: No module named 'PyQt5'"

You didn't activate the virtual environment. Run:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### "Port 9876 already in use"

Another instance is running. Kill it:

```powershell
Get-Process python | Stop-Process -Force
```

Then restart.

### "Cannot find the file specified" on Windows

Your path might have spaces. Try:

```powershell
"C:\Program Files\Python312\python.exe" -m venv venv
```

### "Permission denied" on Linux/macOS

```bash
chmod +x venv/bin/activate
source venv/bin/activate
```

### App crashes on startup

Check the console for error messages. Common causes:

- **Missing audio driver** — Check audio settings
- **Qt plugin missing** — Reinstall PyQt5: `pip install --force-reinstall PyQt5`
- **Corrupted project file** — Delete `projects/el_taser/` and restart

---

## Optional: Create Desktop Shortcut (Windows)

```powershell
# Run this once to create a shortcut
python -c "import os; os.system('cmd /c \"powershell -Command \\\"$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop) + '\\\\Show Designer Pro.lnk'); $Shortcut.TargetPath = 'powershell.exe'; $Shortcut.Arguments = '-NoExit -Command cd C:\\\\path\\\\to\\\\show_designer; .\\\\venv\\\\Scripts\\\\Activate.ps1; python src\\\\ui\\\\dual_app.py'; $Shortcut.Save()\\\"\"')"
```

Or create it manually:
1. Right-click Desktop → New → Shortcut
2. Location: `powershell.exe -NoExit -Command cd C:\path\to\show_designer; .\venv\Scripts\Activate.ps1; python src\ui\dual_app.py`
3. Name: "Show Designer Pro"
4. Click Finish

---

## Next Steps

- [Quick Start →](quickstart.md)
- [Features →](features.md)
- [UI Guide →](usage/ui-guide.md)

---

**Still stuck?** Open a [GitHub Issue](https://github.com/guillegar/show_designer/issues) and we'll help!
