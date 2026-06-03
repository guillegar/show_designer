# Multi-Project Guide 📁

Organize your light shows into separate projects.

## Project Structure

Each project lives in `projects/<slug>/`:

```
projects/el_taser/
├── project.json      # Metadata (name, BPM, duration)
├── show.json         # Timeline + clips
├── rig.json          # Fixtures
├── presets.json      # Saved effect presets
└── feedback.json     # UI state
```

## Creating a Project

1. **Toolbar** → Project dropdown (📁 button)
2. Click **"🆕 New Project…"**
3. Enter:
   - **Project slug** — Folder name (lowercase, no spaces): `my_event`
   - **Project name** — Display name: `My Awesome Event`
4. Click Create

The app creates `projects/my_event/` with default files.

## Switching Projects

1. **Toolbar** → Project dropdown (📁 button)
2. Select a project from the list
3. App saves current show → loads new project
4. No restart needed

## Importing Audio

For each project, you can analyze audio automatically:

1. Place `.mp3` file in project folder
2. App detects it and auto-analyzes (takes ~30s)
3. Analysis cached as `analizadas/<song>/`

## Exporting a Project

1. **Toolbar** → Export button (📤)
2. Choose format:
   - **QLC+ XML** — Import into QLC+ software
   - **CSV** — Clips or DMX frames
3. Saved to `projects/<slug>/exports/`

## Backing Up

Projects are just JSON files. Back them up:

```powershell
# Copy to external drive
xcopy projects\ E:\backup\shows\ /Y /I /E
```

## Advanced: Editing project.json

You can manually edit `projects/<slug>/project.json`:

```json
{
  "slug": "el_taser",
  "name": "El Taser de Mamá Remix",
  "bpm": 119.68,
  "duration_ms": 273300,
  "audio_file": "El Taser de Mama Remix.mp3",
  "created_at": "2026-05-29T12:34:56Z",
  "modified_at": "2026-06-03T18:42:00Z"
}
```

Save and restart to load changes.

---

**Next**: Check [Hardware Guide](../hardware.md) to connect physical lights to your project.
