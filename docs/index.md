# Show Designer Pro 🎨

> **Professional lighting control software**: Design light shows for LED strips and DMX fixtures with a visual timeline editor, then control them with Claude via MCP.

## What is Show Designer Pro?

Show Designer Pro is a comprehensive lighting design and control platform that lets you:

- 🎬 **Design in a timeline** — Adobe/FL Studio-style editor with drag-and-drop clips, effects, and real-time preview
- 💡 **Drive WLED bars** — e.g. 10 bars of 93 LEDs each via Art-Net, with a library of built-in pixel effects plus auto-discovered plugins (flash, waves, gradients, fire, scanner, pixel-mapping…)
- 🎯 **DMX fixtures** — channel effects for movers, wash, beam and strobe (pan-tilt, color, dimmer) with GDTF/JSON profiles
- 🎵 **Audio analysis** — beat/downbeat/section detection, BPM and key via librosa + madmom, plus live audio input
- 📊 **3D visualization** — real-time Three.js viewer with bloom, fog, and DMX-responsive fixtures
- 🤖 **Claude Control** — 150+ JSON-RPC commands over MCP to generate, edit and run your light show in natural language
- 📤 **Output & export** — Art-Net, sACN (E1.31), ENTTEC Open DMX USB; export patch to PDF, DMX to CSV, video preview (GIF/MP4) and backup/restore bundles

## Quick Links

- **[Quick Start](quickstart.md)** — Get running in 5 minutes
- **[Features](features.md)** — What can you do?
- **[Installation](installation.md)** — Step-by-step setup
- **[GitHub](https://github.com/guillegar/show_designer)** — Source code

## Key Stats

| Metric | Value |
|--------|-------|
| **Tests** | 1043 Python + 36 Vitest passing ✅ |
| **Version** | v2.0 (stable) |
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

✨ **Pixel effects** — built-in library + auto-discovered plugins (flash, wave, rainbow, strobe, gradient, fire, scanner, pixel-map…)

🎪 **Channel effects** — moving heads (pan-tilt circle/fig8), color, dimmer/strobe, with GDTF profiles

🎵 **Smart audio** — beats, downbeats, sections, BPM, key, kicks/snares/hats, plus live input

🔌 **Plugin system** — add custom effects in `plugins/effects/my_effect.py`

📁 **Multi-project** — organize shows by project with separate rigs and timelines

🤖 **Claude integration** — control everything via natural language over MCP

💾 **Persistence** — save/load shows, autosave, git checkpoints, backup/restore bundles

---

## License

**Prosperity Public License 3.0.0**

| Use Case | Status | Note |
|----------|--------|------|
| Personal / Educational | ✅ Free | Always allowed |
| Open Source / Community | ✅ Free | Keep attribution |
| Commercial (trial) | ✅ Free | 30 days evaluation |
| Commercial (production) | ❌ Requires License | Contact via [GitHub](https://github.com/guillegar/show_designer) |

[Full License Details](license.md)

---

**Ready to design?** → [Quick Start →](quickstart.md)

Questions? Check [FAQ](faq.md) or [GitHub Issues](https://github.com/guillegar/show_designer/issues)
