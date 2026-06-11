# Show Designer Pro 🎨

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![Tests: 434/434](https://img.shields.io/badge/tests-434%2F434-brightgreen)](#tests)
[![Coverage: 92.6%](https://img.shields.io/badge/coverage-92.6%25-green)](#testing)
[![License: PPL 3.0](https://img.shields.io/badge/license-PPL%203.0-blue)](LICENSE)
[![Docs: GitHub Pages](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://guillegar.github.io/show_designer/)

> **Professional lighting control software**: Design light coreographies for LED strips + DMX fixtures in a visual timeline editor (Adobe/FL Studio style), or control via **Claude** with 50+ MCP tools.

**Version**: v1.10 (web) | **Status**: Stable (434 tests passing) | **License**: Prosperity Public License 3.0.0

---

## 🚀 Quick Links

| | |
|---|---|
| **📖 [Full Documentation](https://guillegar.github.io/show_designer/)** | Complete guide (20+ pages) |
| **⚡ [Quick Start (5 min)](https://guillegar.github.io/show_designer/quickstart/)** | Get running now |
| **✨ [Features](https://guillegar.github.io/show_designer/features/)** | 51 effects + capabilities |
| **🤖 [Claude Control](https://guillegar.github.io/show_designer/advanced/mcp/)** | AI-powered show design |
| **🔧 [Installation](https://guillegar.github.io/show_designer/installation/)** | Step-by-step setup |

---

## ✨ What You Can Do

| Feature | Details |
|---------|---------|
| **🎬 Timeline Editor** | Multi-track, drag-drop clips, snap to beats, undo/redo, layers |
| **💡 51 LED Effects** | Flash, wave, rainbow, strobe, gradient, pattern, spectral, + plugins |
| **🎯 24 DMX Effects** | Position, color, intensity, optical, strobe for movers/wash/beam |
| **🎵 Audio Analysis** | Auto-detect beats, drops, sections, stems (librosa + madmom + demucs) |
| **📺 3D Viewer** | Real-time visualization (Three.js) with 10 WLED bars + 4 movers |
| **🤖 Claude Control** | 50+ JSON-RPC tools—ask Claude to generate light shows naturally |
| **💾 Export** | QLC+ XML, CSV clips, frame-by-frame DMX |
| **🔌 Multi-Project** | Organize shows by project with separate rigs & timelines |

---

## 📋 Key Info

- **Requires**: Python 3.11+, Windows 10+ (Linux/macOS experimental)
- **Hardware**: Optional WLED bars (Art-Net) + DMX fixtures
- **License**: **PPL 3.0** — Free for personal/educational, requires license for commercial use
- **Tests**: 434/434 passing, 92.6% coverage

---

## 🎯 Getting Started (2 Steps)

### 1. Install
```powershell
git clone https://github.com/guillegar/show_designer.git
cd show_designer
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Run
```powershell
python src/ui/dual_app.py
# Then open http://localhost:8080 in your browser
```

**Full guide**: [Installation →](https://guillegar.github.io/show_designer/installation/)

---

## 🖥️ The UI (4 Tabs)

1. **🎨 Timeline Editor** — Design your show with drag-drop effects
2. **📊 Feedback + WLED** — Live preview of what hardware will display
3. **🎯 Patch** — 2D top-down rig editor for fixtures
4. **🎵 Analyzer** — Audio analysis with beats, drops, sections

**Learn more**: [UI Guide →](https://guillegar.github.io/show_designer/usage/ui-guide/)

---

## 🔌 Hardware Support

| Hardware | Status | Notes |
|----------|--------|-------|
| **10 WLED Bars** | ✅ Ready | 93 LEDs each, Art-Net universes 1-10 |
| **4 Moving Heads** | ✅ Ready | 16 channels each, universe 11 |
| **DMX Fixtures** | ✅ Ready | Art-Net to RS485 converter needed |

**Setup guide**: [Hardware →](https://guillegar.github.io/show_designer/hardware/)

---

## 🧪 Quality Assurance

- **434 tests** — All passing ✅
- **92.6% coverage** — Well-tested code
- **GitHub Actions CI** — Automated testing on every push
- **Stable v1.10 (web)** — Production-ready

**Testing guide**: [Development →](https://guillegar.github.io/show_designer/development/testing/)

---

## 🤖 Claude Integration

Show Designer Pro integrates seamlessly with Claude Code:

```
You: "Add a 30-second drop effect every 4 bars"
Claude: [calls mcp__show-control__generate_section]
Result: Clips created automatically ✅
```

50+ MCP tools available for:
- Timeline control (play, pause, seek)
- Clip creation & editing
- Audio analysis & features
- Fixture management
- Show generation

**Learn more**: [Claude Control →](https://guillegar.github.io/show_designer/advanced/mcp/)

---

## 📦 Project Structure

```
show_designer/
├── src/core/              # Timeline, effects, show engine
├── src/ui/                # PyQt5 UI (4 tabs)
├── src/analysis/          # Audio analysis
├── src/mcp/               # Claude control
├── src/viewer3d/          # 3D viewer
├── tests/                 # 434 pytest tests
├── docs/                  # 20+ documentation pages
├── plugins/effects/       # Custom effect plugins
├── profiles/              # Fixture definitions
└── projects/              # Your shows
```

**Full architecture**: [Architecture Guide →](https://guillegar.github.io/show_designer/advanced/architecture/)

---

## 🛠️ Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) or the [Contributing Guide](https://guillegar.github.io/show_designer/development/contributing/) for:

- How to report bugs
- How to submit features
- Development setup
- Testing requirements
- Code style guidelines

**Good first issue?** Look for [`good first issue`](https://github.com/guillegar/show_designer/issues) labels.

---

## 📚 Documentation

**Full documentation available**: [guillegar.github.io/show_designer](https://guillegar.github.io/show_designer/)

- [Quick Start](https://guillegar.github.io/show_designer/quickstart/) — 5 minutes
- [Installation](https://guillegar.github.io/show_designer/installation/) — Detailed setup
- [Features](https://guillegar.github.io/show_designer/features/) — What you can do
- [UI Guide](https://guillegar.github.io/show_designer/usage/ui-guide/) — The 4 tabs
- [Keyboard Shortcuts](https://guillegar.github.io/show_designer/usage/shortcuts/) — Speed up your workflow
- [Plugins](https://guillegar.github.io/show_designer/advanced/plugins/) — Create custom effects
- [FAQ](https://guillegar.github.io/show_designer/faq/) — Common questions
- [Architecture](https://guillegar.github.io/show_designer/advanced/architecture/) — Deep dive
- And more...

---

## 💬 Support

- **Issues**: [GitHub Issues](https://github.com/guillegar/show_designer/issues)
- **Discussions**: [GitHub Discussions](https://github.com/guillegar/show_designer/discussions)
- **Email**: guille@example.com
- **Docs**: [Complete guide](https://guillegar.github.io/show_designer/)

---

---

## 📚 Documentación

- **[CLAUDE.md](CLAUDE.md)** — Arquitectura profunda, decisiones de diseño, estado actual (v1.10+)
- **[STRUCTURE.md](STRUCTURE.md)** — Organización de directorios y archivos
- **[SETUP.md](SETUP.md)** — Instalación paso a paso
- **Checkpoints**: historial de `git` (un commit por fase/feature; sin carpeta `versions/`)

---

## 🖥️ Requisitos del sistema

- **Python**: 3.11 o superior
- **OS**: Windows 10+ (probado en Windows 11), compatible con Linux/macOS (sin garantía)
- **Hardware WLED (opcional)**: 10 barras WLED en red local (Art-Net compatible)
- **Hardware DMX (opcional)**: nodo Art-Net→DMX + fixtures convencionales

**Dependencias principales** (ver `requirements.txt`):
- PyQt5 (UI desktop)
- librosa + madmom (análisis de audio)
- demucs (separación de stems)
- pygdtf (soporte GDTF para fixtures)
- websockets + fastapi (backend headless v1.10+)

---

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Ver [CONTRIBUTING.md](CONTRIBUTING.md) para:
- Cómo reportar bugs
- Cómo hacer pull requests
- Estándares de código
- Proceso de testing

---

## 📄 Licencia

**Prosperity Public License 3.0.0 (PPL)**

| Uso | Permitido | Nota |
|-----|-----------|------|
| Personal / Educativo | ✅ Libre | Siempre |
| Open Source / Comunidad | ✅ Libre | Mantener crédito |
| Comercial (prueba) | ✅ 30 días | Período de evaluación |
| Comercial (producción) | ❌ Requiere licencia | Contacta a guille@example.com |

Ver [LICENSE](LICENSE) para términos completos.

**Atribuciones**: `src/viewer3d/CREDITS.md`
