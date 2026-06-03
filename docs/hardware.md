# Hardware Guide 🔌

## Current Setup

Show Designer Pro controls:

- **10 WLED Bars** (93 LEDs each, universes 1-10)
- **4 Moving Head Wash Fixtures** (16 channels each, universe 11)

## WLED Bars

### Specifications

| Component | Value |
|-----------|-------|
| **Per bar** | 93 WS2812B (RGB) LEDs |
| **Total** | 930 LEDs across 10 bars |
| **Controller** | ESP32 or similar with WLED firmware |
| **Protocol** | Art-Net (UDP 6454) |
| **Power** | ~5A per bar (470W total) |
| **Network** | 192.168.1.201 - 192.168.1.210 |

### Setup Instructions

1. **Flash WLED firmware** on each ESP32:
   - Download from [wled.me](https://wled.me)
   - Assign unique IP 192.168.1.20X
   - Set to Art-Net mode, universe 1-10

2. **Connect to network**:
   - All on same WiFi as PC
   - Verify connectivity: `ping 192.168.1.201`

3. **Power supply**:
   - 5V DC, 5A minimum per bar
   - Use separate PSU for stable operation
   - Add capacitor across power rails (100µF recommended)

4. **Configure in Show Designer**:
   - Check `fixtures.json` — should have 10 `led_strip` entries
   - Check `output_targets.json` — should have universes 1-10 mapped to WLED targets

### Troubleshooting WLED

**LEDs not lighting up:**
- Check power (multimeter: should be 5V)
- Check data line (GPIO pin on ESP32)
- Verify Art-Net IP in WLED settings
- Check firewall (allow UDP 6454)

**Colors inverted or flickering:**
- Adjust LED order in WLED settings (RGB vs BGR vs GRB)
- Add termination resistor (330Ω) on data line
- Check cable length (>5m needs level shifter)

**Some LEDs don't respond:**
- One bad LED can break the chain
- Test with single bar first
- Replace defective LED

---

## DMX Fixtures

### Current Hardware

**4 Moving Head Wash Fixtures** (16 channels each):
- PAN (2 channels, 16-bit)
- TILT (2 channels, 16-bit)
- COLOR (RGB, 3 channels)
- INTENSITY (1 channel)
- STROBE (1 channel)
- RESERVED (7 channels)

**Universe 11**, DMX start addresses:
- Fixture 1: Ch 1
- Fixture 2: Ch 17
- Fixture 3: Ch 33
- Fixture 4: Ch 49

### Protocol

**Art-Net**:
- UDP port 6454
- Sent from PC to Art-Net node
- Node converts to DMX512 (RS485)

**Planned**: Art-Net → DMX converter node at 192.168.1.50

### Adding More Fixtures

To add new fixtures:

1. **Get GDTF profile**:
   - Go to [gdtf-share.com](https://gdtf-share.com)
   - Download the fixture's .gdtf file
   - Save to `profiles/`

2. **Create JSON profile** (if GDTF not available):
   ```json
   {
     "name": "generic_beam_18ch",
     "manufacturer": "Generic",
     "mode": "18ch Mode",
     "channel_map": {
       "pan": 0,
       "tilt": 1,
       "pan_16bit": "0,1",
       "tilt_16bit": "2,3",
       "color_r": 4,
       "color_g": 5,
       "color_b": 6,
       "intensity": 7,
       "strobe": 8
     },
     "geometry": {
       "position": [0, 0, 2],
       "has_pan": true,
       "has_tilt": true
     }
   }
   ```

3. **Add to rig** via UI (Patch tab) or MCP:
   ```python
   mcp__show-control__add_fixture(
     fixture_id="beam_1",
     profile_id="generic_beam_18ch",
     universe=11,
     dmx_start=65
   )
   ```

4. **Test** in 3D viewer — fixture should appear and respond

### Channel Effects

Available for any DMX fixture:

| Category | Effects |
|----------|---------|
| **Position** | circle, spiral, figure-8, random, pan_sweep, tilt_sweep |
| **Color** | rainbow, complementary, split_complementary, analogous, hue_shift, random |
| **Intensity** | pulse, flicker, strobe, ramp |
| **Optical** | gobo_select, gobo_rotation, frost, iris, focus |
| **Strobe** | single, double, random |

Example clip:
```
Fixture: "moving_head_1"
Effect: "pos_circle"
Params: {"radius": 0.5, "speed": 0.2}
Duration: 10s
```

---

## Alternative Hardware

### LED Strips

Can use other addressable LED strips:
- APA102 (SPI)
- SK6812 (RGBW variant)
- WS2811 (older)

Requirements:
- WLED-compatible controller
- Art-Net output to 512 channels per universe

### Fixture Types

Besides moving heads, Show Designer supports:
- **Wash fixtures** (broad color wash)
- **Beam fixtures** (narrow, profile lights)
- **Strobe fixtures** (high-speed)
- **Dimmer units** (simple intensity)
- **LED strips** (RGB pixels, like WLED)

Add any via JSON or GDTF profiles.

### Network

**Current:**
- 192.168.1.200-210 — WLED bars
- 192.168.1.50 — (planned) Art-Net→DMX node
- PC on same network segment

**Scale to 64 universes:**
- Add Art-Net splitter/router
- Support up to 512 channels × 64 = 32,768 DMX channels

---

## Configuration Files

### fixtures.json

Defines all fixtures:
```json
{
  "fixtures": [
    {
      "fixture_id": "bar_0",
      "profile_id": "wled_strip_93",
      "universe": 0,
      "dmx_start": 0,
      "label": "Bar 0 (front)",
      "position": [0, 0, 0]
    }
  ]
}
```

### output_targets.json

Maps universes to physical outputs:
```json
{
  "0": {
    "type": "wled",
    "ip": "192.168.1.201",
    "port": 4048
  },
  "10": {
    "type": "artnet_node",
    "ip": "192.168.1.50",
    "port": 6454
  },
  "11": {
    "type": "sim_only"
  }
}
```

Types:
- `wled` — Direct Art-Net to WLED device
- `artnet_node` — Art-Net splitter/converter node
- `sim_only` — Simulation (no physical output)
- `dmx_serial` — (planned) RS485 serial DMX

---

## Maintenance

### Daily

- Check LED power supplies (no unusual heat)
- Verify network connectivity
- Test a few clips before show

### Weekly

- Clean LED fixtures (dust accumulation dims lights)
- Check cables for damage
- Test WLED bars with full white (stressful)

### Monthly

- Check capacitors on power supplies (bulging = failing)
- Update WLED firmware if new versions available
- Backup your projects to external drive

---

## Expansion Ideas

**Phase 2** (planned):

- [ ] Art-Net → DMX physical node (Enttec DMX Proton, etc.)
- [ ] More moving head profiles (beam, spot, etc.)
- [ ] Haze/fog machine control
- [ ] LED wall support (large video LED wall)
- [ ] Laser support (via DMX)

**Phase 3** (future):

- [ ] Network redundancy (backup hardware)
- [ ] Multi-show sync (multiple zones)
- [ ] Live remote control (mobile app via OSC)

---

## Support

**Hardware issues?**
- Check [FAQ Hardware section](faq.md#hardware--output)
- Open a [GitHub Issue](https://github.com/guillegar/show_designer/issues)
- Email: guille@example.com

**WLED Support:**
- Docs: [wled.me/docs](https://wled.me/docs)
- Forum: [github.com/Aircoookie/WLED](https://github.com/Aircoookie/WLED)

**DMX/Art-Net:**
- Specs: [art-net.org.uk](https://art-net.org.uk/)
- Tools: [DMXIS](https://www.dmxis.com) (testing software)
