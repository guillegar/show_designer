# Show Designer Pro 🎨

> **Professional lighting control software**: Design light shows for LED strips and DMX fixtures with a visual timeline editor, then control them with Claude via MCP.

## What is Show Designer Pro?

Show Designer Pro is a comprehensive lighting design and control platform that lets you:

- 🎬 **Design in a timeline** — Adobe/FL Studio-style editor with drag-and-drop clips, effects, and real-time preview
- 💡 **Control 10 WLED bars** — 93 LEDs each via Art-Net, with 51 pixel effects (flash, waves, gradients, patterns, spectral)
- 🎯 **DMX fixtures** — 24 channel effects for movers, wash, beam, strobe (position, color, intensity, optical, strobe)
- 🎵 **Audio analysis** — Automatic beat detection, section detection, stems separation via librosa + madmom + demucs
- 📊 **3D visualization** — Real-time Three.js viewer with bloom, fog, and DMX-responsive fixtures
- 🤖 **Claude Control** — 50+ MCP tools to let Claude generate, edit, and execute your light show via natural language
- 📤 **Export** — QLC+ XML, CSV, frame-by-frame DMX

## Quick Links

- **[Quick Start](quickstart.md)** — Get running in 5 minutes
- **[Features](features.md)** — What can you do?
- **[Installation](installation.md)** — Step-by-step setup
- **[GitHub](https://github.com/guillegar/show_designer)** — Source code

## Key Stats

| Metric | Value |
|--------|-------|
| **Tests** | 363/363 passing ✅ |
| **Coverage** | 92.6% |
| **Version** | v1.9 F2 (stabilization) |
| **License** | [Prosperity Public License 3.0.0](license.md) |
| **Python** | 3.11+ |

## Getting Started

### 1️⃣ Install

```bash
git clone https://github.com/guillegar/show_designer.git
cd show_designer
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
```

### 2️⃣ Run

```bash
python -m server.main
```

### 3️⃣ Open 3D Viewer

Open your browser: **http://localhost:8000/**

## Features at a Glance

✨ **51 Pixel Effects** — flash, wave, rainbow, strobe, spectral, gradient, pattern...

🎪 **24 Channel Effects** — movers circle, color rainbow, intensity pulse, optical gobos...

🎵 **Smart Audio** — beats, downbeats, sections, stems, kicks, snares, hats...

🔌 **Plugin System** — add custom effects in `plugins/effects/my_effect.py`

📁 **Multi-Project** — organize shows by project with separate rigs and timelines

🤖 **Claude Integration** — control everything via natural language with MCP

💾 **Persistence** — save/load shows, auto-backup, version checkpoints

---

## License

**Prosperity Public License 3.0.0**

| Use Case | Status | Note |
|----------|--------|------|
| Personal / Educational | ✅ Free | Always allowed |
| Open Source / Community | ✅ Free | Keep attribution |
| Commercial (trial) | ✅ Free | 30 days evaluation |
| Commercial (production) | ❌ Requires License | Contact: guille@example.com |

[Full License Details](license.md)

---

**Ready to design?** → [Quick Start →](quickstart.md)

Questions? Check [FAQ](faq.md) or [GitHub Issues](https://github.com/guillegar/show_designer/issues)
