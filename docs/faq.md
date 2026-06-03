# FAQ ❓

## General

**Q: What is Show Designer Pro?**
A: It's professional lighting control software for LED strips and DMX fixtures. Design light shows visually in a timeline, then play them live or control them with Claude.

**Q: Who made this?**
A: Guille Garci. It's an open-source project under the Prosperity Public License.

**Q: What OS does it run on?**
A: Windows 10+ is fully supported. Linux and macOS should work but aren't actively tested.

**Q: Do I need hardware to use it?**
A: No! You can design and preview shows with the 3D simulator. Real hardware (WLED bars) is optional.

---

## Installation & Setup

**Q: I'm getting "ModuleNotFoundError: No module named X"**
A: You didn't activate the virtual environment. Run:
```powershell
.\venv\Scripts\Activate.ps1
```

**Q: Python says "Version 3.11+ required"**
A: Upgrade Python from [python.org](https://www.python.org/downloads/)

**Q: Installation is very slow**
A: The dependencies (librosa, demucs) are large. Be patient, it's normal. Get coffee ☕

**Q: Do I need to install MkDocs or anything extra?**
A: For basic usage, no. For building documentation locally, install mkdocs:
```powershell
pip install mkdocs-material
```

---

## Usage

**Q: How do I create my first clip?**
A: See [Quick Start](quickstart.md) or [UI Guide](usage/ui-guide.md). TL;DR:
1. Select an effect from the left panel
2. Cursor changes to crosshair
3. Drag on a bar in the timeline

**Q: Can I import audio from Spotify/YouTube?**
A: Not directly, but you can:
1. Download the MP3
2. Place it in your project folder
3. Show Designer will analyze it automatically

**Q: How do I export my show?**
A: Click "📤 Export" button:
- QLC+ XML (for QLC+ software)
- CSV (clips or DMX frames)

**Q: Can I use MIDI controllers?**
A: Not yet. MIDI support is planned for v2.0.

**Q: The 3D viewer looks dark**
A: Try:
- Adjusting your monitor brightness
- Closing/reopening the viewer
- Checking if fixtures are responding to clips

---

## Audio & Analysis

**Q: How does audio analysis work?**
A: Show Designer uses:
- **librosa** — beat and feature extraction
- **madmom** — more accurate beat detection
- **demucs** — separating vocals/drums/bass/other

This is all done **offline** (doesn't require internet).

**Q: Can I manually edit the beat grid?**
A: Yes! Go to the Analyzer tab (🎵) and:
- Click on beats to edit them
- Adjust section labels
- Manually add/remove events

**Q: What if the audio analysis is wrong?**
A: You can override it:
1. Go to Analyzer tab
2. Edit beats, sections, events manually
3. Your edits are saved in `curation.json` and never overwritten

**Q: How long does analysis take?**
A: ~30 seconds per 3-minute song. Subsequent runs use the cached analysis.

---

## Hardware & Output

**Q: What WLED hardware do I need?**
A: Any WLED-compatible LED strips. We test with:
- WS2812B (Neopixel) LEDs
- Art-Net compatible ESP32 boards
- 93 LEDs per bar (10 bars total)

**Q: Can I use different LED counts?**
A: Yes! Edit `fixtures.json` and change the LED count per fixture.

**Q: What about DMX fixtures?**
A: Show Designer supports:
- Art-Net protocol (UDP 6454)
- 24 channel effects (position, color, intensity, etc.)
- GDTF profiles (import from [gdtf-share.com](https://gdtf-share.com))

**Q: How many universes can I use?**
A: Currently 11 universes (configurable). Each universe = 512 DMX channels.

**Q: Can I use sACN instead of Art-Net?**
A: Not yet. Art-Net is the current standard. sACN support planned for v2.0.

---

## Claude & MCP

**Q: What is MCP?**
A: Model Context Protocol. It lets Claude control Show Designer via 50+ tools. Say things like:
- "Add a drop effect every 30 seconds"
- "Create a 10-bar rainbow wave on bars 1-5"
- "Find all the kicks in the song"

**Q: Do I need Claude Code?**
A: No, but it's free and recommended. MCP still works if you integrate Show Designer into your own Claude workflow.

**Q: Can Claude generate entire shows?**
A: Yes! Use `mcp__show-control__generate_section` to have Claude design sections based on audio analysis.

**Q: What happens if Claude makes a mistake?**
A: Just undo (Ctrl+Z) and try again. Or manually fix the clips.

---

## Plugins

**Q: How do I create a custom effect?**
A: See [Plugins Guide](advanced/plugins.md). Example:

```python
# plugins/effects/my_effect.py
from src.core.effects_engine import Effect, EffectScope

class MyEffect(Effect):
    name = "my_effect"
    scope = EffectScope.ALL_BARS
    
    def render(self, elapsed_time, bars_state, audio_context, **params):
        return bars_state

PLUGIN_EFFECTS = {1010: MyEffect()}
```

Restart the app and your effect appears in the browser.

**Q: Can I share plugins with others?**
A: Absolutely! Open a PR to add them to the official library.

---

## Performance & Troubleshooting

**Q: The app is laggy**
A: Try:
1. Close the 3D viewer tab (it's GPU-intensive)
2. Reduce the number of active clips
3. Upgrade your graphics driver
4. Restart the app

**Q: "Port 9876 already in use"**
A: Another instance is running. Kill it:
```powershell
Get-Process python | Stop-Process -Force
```

**Q: The app crashed. How do I recover?**
A: Your show was auto-saved. Just restart and it loads automatically.

**Q: Can I get the crash logs?**
A: Check the console output. If you're running from PowerShell, scroll up.

**Q: The WLED bars aren't lighting up**
A: Check:
1. Are the LEDs powered?
2. Is the ESP32 on the same network?
3. Is Art-Net output enabled? (check OutputRouter logs)
4. Try pinging the device: `ping 192.168.1.201`

---

## License & Commercial

**Q: Can I use this commercially?**
A: Not without a license. See [License](license.md) for details.

**Q: How much does a commercial license cost?**
A: Contact guille@example.com for pricing. It depends on your use case.

**Q: Can I modify the source code for commercial use?**
A: Yes, but only under a commercial license.

**Q: What if my company is small?**
A: We're happy to work out reasonable terms. Reach out!

---

## Contributing

**Q: How can I contribute?**
A: See [Contributing Guide](development/contributing.md). You can:
- Report bugs
- Suggest features
- Submit code fixes
- Improve documentation

**Q: Do I need to sign a CLA?**
A: No. Just follow the [Contributing Guide](development/contributing.md).

**Q: What's the test coverage requirement?**
A: Minimum 60%, but we aim for 92%+. Run:
```powershell
pytest tests/ --cov --cov-report=html
```

---

## Still Have Questions?

- 📖 Check the [Architecture Guide](advanced/architecture.md)
- 💬 Open a [GitHub Discussion](https://github.com/guillegar/show_designer/discussions)
- 🐛 Report a [GitHub Issue](https://github.com/guillegar/show_designer/issues)
- 📧 Email: guille@example.com
