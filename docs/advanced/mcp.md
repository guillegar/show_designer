# Claude Control via MCP 🤖

Show Designer Pro exposes 50+ tools via the Model Context Protocol (MCP), allowing Claude to control your light show with natural language.

## Getting Started

### In Claude Code

When you open Claude Code in the show_designer directory, MCP tools automatically appear:

```python
# Claude recognizes these tools automatically:
mcp__show-control__list_clips
mcp__show-control__add_clip
mcp__show-control__play
mcp__show-control__analyzer_find_drops
# ... and 46 more
```

### Using in Chat

Ask Claude naturally:

```
"Add 10 flashes on bar 3, each lasting 500ms, spaced 2 seconds apart"

Claude will:
1. Call mcp__show-control__add_clip() 10 times
2. Create clips at the right times
3. Report success or errors
```

## Available Tools

### Transport

- `play` — Start playback
- `pause` — Pause
- `stop` — Stop and reset to start
- `seek(time_ms)` — Jump to time
- `blackout()` — All lights off
- `get_state()` — Current state (playing, time, etc.)

### Clips

- `list_clips()` — Get all clips (filter by bar, group, time range)
- `add_clip(start_ms, duration_ms, effect_id, ...)` — Create clip
- `move_clip(clip_id, new_start_ms)` — Reposition
- `delete_clip(clip_id)` — Remove
- `set_clip_params(clip_id, params)` — Modify effect parameters
- `set_clip_color(clip_id, color_hex)` — Change color
- `duplicate_clip(clip_id)` — Copy

### Channel Clips (DMX)

- `add_channel_clip(fixture_id, effect_id, ...)` — DMX clip
- `set_channel_clip_params(clip_id, params)` — Modify

### Generation (AI-powered)

- `generate_section(start_ms, duration_ms, style)` — Claude generates a section
  - Styles: `energetic`, `subtle`, `synchronized`, `random`, `audio_reactive`
- `mirror_clips_lr(clip_ids)` — Mirror clips left/right
- `apply_palette_to_range(clip_ids, color_palette)` — Change colors

### Groups

- `list_groups()` — Get bar groups
- `add_group(bars, label)` — Create group
- `delete_group(group_id)` — Remove

### Cues

- `list_cue_points()` — Get all cues (10 slots: 0-9)
- `set_cue(slot, time_ms, name)` — Set cue
- `trigger_cue(slot)` — Jump to cue
- `clear_cue(slot)` — Remove cue

### Fixtures (Rig)

- `list_fixtures()` — All fixtures (bars, movers, etc.)
- `add_fixture(fixture_id, profile_id, universe, dmx_start, ...)` — Add fixture
- `delete_fixture(fixture_id)` — Remove
- `move_fixture(fixture_id, position)` — Change 3D position
- `set_fixture_property(fixture_id, key, value)` — Modify property
- `save_rig()` — Persist fixtures

### Audio Analysis (Music Brain)

- `analyzer_summary()` — Overall analysis (BPM, duration, sections)
- `analyzer_list_sections(with_curated=True)` — All sections (intro, verse, chorus, drop, etc.)
- `analyzer_list_beats(start_sec, end_sec)` — Beat times
- `analyzer_list_downbeats(start_sec, end_sec)` — Measure boundaries
- `analyzer_list_events(kind, start_sec, end_sec)` — kicks, snares, hats, onsets
- `analyzer_find_drops()` — Automatic drop detection
- `analyzer_find_breakdowns()` — Breakdown sections
- `analyzer_get_features_at(time_sec, names)` — Energy, chroma, MFCC at a point
- `analyzer_get_features_range(start, end, downsample, names)` — Features over range

### Curation

- `analyzer_set_section_label(idx, name, type)` — Rename/retype section
- `analyzer_add_manual_event(time_sec, kind, name)` — Add event
- `analyzer_disable_event(time_sec, kind, tolerance)` — Hide event
- `analyzer_set_event_threshold(kind, value)` — Adjust sensitivity

### Persistence

- `save_show()` — Save current show
- `load_show(show_id)` — Load saved show
- `list_saved_shows()` — Get available shows

### Viewer

- `open_3d_viewer()` — Launch 3D viewer in browser

---

## Example Workflows

### "Lights that react to drops"

```
"Find the biggest drop in the song and add an energetic 
effect sequence starting 2 beats before the drop."

Claude will:
1. Call analyzer_find_drops() → get drop times
2. Get the largest one
3. Calculate 2 beats before
4. Call generate_section() with style='energetic'
5. Add clips at the right time
```

### "Mirror a section left/right"

```
"The light pattern on bars 1-5 looks good. 
Mirror it onto bars 6-10 but offset by half a beat."

Claude will:
1. Call list_clips() to find clips on bars 1-5
2. Call duplicate_clip() for each
3. Call move_clip() to offset timing
4. Move to bars 6-10
```

### "Build a show from scratch"

```
"Create a 5-minute light show that follows the song structure.
Use drops for impacts, verses for subtle effects, and synch 
everything to the beat."

Claude will:
1. Call analyzer_summary() → get structure
2. Call analyzer_list_sections() → get all sections
3. For each section, call generate_section() with appropriate style
4. Call save_show() when done
```

---

## Parameters

Most tools accept optional filters:

### add_clip()

```python
mcp__show-control__add_clip(
    start_ms=10000,           # When
    duration_ms=5000,         # How long
    effect_id=51,             # Which effect (0-999 builtin, 1000+ plugin)
    track=3,                  # Which bar/group
    layer=0,                  # Z-order
    params={'color': '#FF0000', 'speed': 0.8},  # Effect-specific
)
```

### list_clips()

```python
mcp__show-control__list_clips(
    bar=3,                    # Filter by bar
    group='group_1',          # Filter by group
    section='verse',          # Filter by section
    time_range=(0, 60000),    # Time range in ms
)
```

### generate_section()

```python
mcp__show-control__generate_section(
    start_ms=0,
    duration_ms=30000,
    style='energetic',        # 'energetic', 'subtle', 'synchronized', 'random', 'audio_reactive'
)
```

---

## Error Handling

Claude receives detailed errors:

```
✗ Effect not found: effect_id=9999
✓ Clip added: clip_id=clip_42
✗ Fixture not found: fixture_id=mover_10
```

Claude learns from these and adjusts subsequent calls.

---

## Advanced: Custom Tools

Want to add your own MCP tool? See [Architecture Guide](architecture.md#extensibility).

---

## Troubleshooting

**Q: Tools don't appear in Claude**
A: Make sure:
1. Show Designer is running (`python -m server.main`)
2. `.mcp.json` is in the repo root
3. Claude Code was started after Show Designer

**Q: "Connection refused" error**
A: Show Designer crashed or port 9876 is occupied. Restart both.

**Q: Claude creates clips but they don't show up**
A: Refresh the UI or check the console for errors.

---

## See Also

- [Quick Start](../quickstart.md) — Getting running
- [Features](../features.md) — What's possible
- [Architecture Guide](architecture.md) — How it works

---

**Ready to let Claude create your light show?** Start with [Quick Start →](../quickstart.md)
