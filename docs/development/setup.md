# Development Setup 🛠️

Set up your development environment to contribute to Show Designer Pro.

## Prerequisites

- Python 3.11+
- Git
- Text editor or IDE (VS Code recommended)
- ~2GB free disk space

## Clone & Setup

```powershell
git clone https://github.com/guillegar/show_designer.git
cd show_designer
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Directory Structure

```
show_designer/
├── src/                      # Source code
│   ├── core/                 # Timeline, show engine, fixtures
│   ├── (sin ui/ — la UI PyQt5 se retiró en la Fase 8)
│   ├── analysis/             # Audio analysis
│   ├── io/                   # Loaders, exporters, routing
│   └── mcp/                  # MCP bridge and server
├── server/                   # Headless backend (FastAPI + asyncio @ :8000)
├── web/                      # React frontend (+ web/public/v3d = 3D viewer)
├── tests/                    # 1043 pytest tests
├── docs/                     # Documentation (this folder)
├── profiles/                 # Fixture profiles (JSON + GDTF)
├── plugins/effects/          # Custom effect plugins
└── projects/                 # Shows  (checkpoints = git; no versions/ folder)
```

## Running in Development

### Backend web (main development target)

```powershell
python -m server.main
```

### Web Backend (v1.10+)

```powershell
python -m server.main
```

Then open http://localhost:8000

### Frontend Development (v1.10+)

```powershell
cd web
npm install
npm run dev
```

Then open http://localhost:5173

## IDE Setup

### VS Code (recommended)

1. Install **Python** extension (Microsoft)
2. Select interpreter: `.venv/Scripts/python.exe`
3. Create `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Show Designer",
      "type": "python",
      "request": "launch",
      "module": "server.main",
      "console": "integratedTerminal",
      "justMyCode": false
    },
    {
      "name": "Tests",
      "type": "python",
      "request": "launch",
      "module": "pytest",
      "args": ["tests/"],
      "console": "integratedTerminal"
    }
  ]
}
```

4. Press F5 to run

### PyCharm

1. Open project folder
2. Configure interpreter: Settings → Python → Project Interpreter → Existing Environment
3. Point to `.venv/Scripts/python.exe`
4. Run → Run 'server.main'

## Useful Commands

### Testing

```powershell
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_timeline_model.py -v

# Run specific test
pytest tests/test_timeline_model.py::test_add_clip -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Watch mode (requires pytest-watch)
ptw tests/
```

### Linting (optional)

```powershell
# Check code style
pylint src/core/show_engine.py

# Or use flake8
flake8 src/ --max-line-length=120
```

### Code Formatting (optional)

```powershell
# Format with black
pip install black
black src/

# Or use autopep8
pip install autopep8
autopep8 --in-place --aggressive src/core/show_engine.py
```

## Common Development Tasks

### Adding a New Feature

1. **Create a branch**:
   ```powershell
   git checkout -b feature/my-feature
   ```

2. **Write tests first** (TDD):
   ```powershell
   # In tests/test_my_feature.py
   def test_my_feature():
       ...
   ```

3. **Implement the feature**:
   ```python
   # In src/... appropriate module
   ```

4. **Run tests**:
   ```powershell
   pytest tests/test_my_feature.py -v
   ```

5. **Test in the app**:
   ```powershell
   python -m server.main
   # Try your feature manually
   ```

6. **Commit and push**:
   ```powershell
   git add .
   git commit -m "feat: add my feature"
   git push origin feature/my-feature
   ```

7. **Open PR** on GitHub

### Adding a Custom Effect

See [Plugins Guide](../advanced/plugins.md).

### Modifying the 3D Viewer

The 3D viewer is in `web/public/v3d/` (Vite copies it to `web/dist/v3d/` on each build). To develop:

1. Edit `web/public/v3d/main.js` or `moving_head.js`
2. Bump the cache-bust `?v=N` in `web/public/v3d/index.html` and rebuild (`cd web && npm run build`)
3. Reload the Viewer3D tab; use the browser console for debugging (`F12`)

### Working with Audio Analysis

Audio analysis code is in `src/analysis/`:

```python
from src.analysis.analyzer_service import AnalysisService

service = AnalysisService()
summary = service.get_summary("path/to/song.mp3")
print(summary.bpm)  # Beats per minute
```

---

## Debugging Tips

### Print Debugging

```python
import sys
sys.stdout.reconfigure(encoding='utf-8')  # For emojis
print(f"→ Debug message: {variable}")
```

### Backend logging

The backend uses `src/log.py` (console + optional rotating file), configured via env vars:

```powershell
$env:LUCES_LOG_LEVEL = "DEBUG"       # DEBUG / INFO / WARNING / ERROR
$env:LUCES_LOG_FILE  = "luces.log"   # optional rotating file
python -m server.main
```

In code: `from src.log import get_logger; log = get_logger(__name__)`.

### Check Open Ports

```powershell
# See what's using port 9876
netstat -ano | findstr :9876

# Kill the process
taskkill /PID <PID> /F
```

### View WebSocket Traffic

Use browser DevTools (F12) → Network → WS (WebSocket filter)

---

## Performance Profiling

### CPU Profiling

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# ... code to profile ...

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative').print_stats(20)
```

### Memory Profiling

```powershell
pip install memory-profiler
python -m memory_profiler -m server.main
```

---

## Database/Cache Debugging

Projects are stored as JSON files in `projects/<slug>/`. To inspect:

```powershell
# View show.json
type projects/el_taser/show.json | python -m json.tool

# Edit fixtures
code projects/el_taser/fixtures.json
```

---

## Documentation

Documentation lives in `docs/` and uses MkDocs.

To build locally:

```powershell
pip install mkdocs-material
mkdocs serve
```

Then visit http://localhost:8000/

To deploy to GitHub Pages:

```powershell
mkdocs gh-deploy
```

---

## CI/CD

GitHub Actions runs tests on every push. See `.github/workflows/ci.yml`.

To test locally before pushing:

```powershell
# Run the exact CI pipeline
pytest tests/ -v --cov=src --cov-report=term
```

Must pass with coverage >= 60% (target 92%+).

---

## Getting Help

- 📖 Read [Architecture Guide](../advanced/architecture.md)
- 💬 [GitHub Discussions](https://github.com/guillegar/show_designer/discussions)
- 🐛 [Report Issues](https://github.com/guillegar/show_designer/issues)
- 📧 Email: guillermo.pondal@gmail.com

---

**Ready to code?** Pick a [GitHub Issue](https://github.com/guillegar/show_designer/issues) labeled `good first issue` and start! 🚀
