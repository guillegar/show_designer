"""
test_switch_project.py — Tests de multi-show quick-switch (H3).

Cubre:
  - switch_project carga el show.json del nuevo slug.
  - Los clips del proyecto anterior NO aparecen después del switch.
  - El live engine queda limpio (sin slots armados) tras el switch.
  - project_changed se emite al stream (hub.broadcast llamado).
  - Switch a slug inexistente → ValueError, sesión no queda en estado parcial.
  - list_projects devuelve la lista de proyectos con el current marcado.
  - switch_project handler devuelve ok y lanza la tarea async.
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_project(tmp_path: Path, slug: str, clip_count: int = 3):
    """Crea un proyecto mínimo en tmp_path/projects/<slug>/.

    Devuelve un MagicMock que simula la interfaz de Project pero usa tmp_path
    (no PROJECTS_DIR real) para los archivos, evitando colisiones con proyectos reales.
    """
    folder = tmp_path / "projects" / slug
    folder.mkdir(parents=True, exist_ok=True)

    # Timeline mínima con clip_count clips (formato schema v4 completo)
    clips = [
        {
            "uid": f"clip_{i}", "track": 0, "bar": 0, "layer": 0,
            "start_ms": i * 1000, "end_ms": i * 1000 + 500, "duration_ms": 500,
            "effect_id": "1", "params": {}, "color": "#ff0000",
            "channel_effect_id": None, "channel_effect_params": {},
            "channel_effects": [], "events": [], "automation_lanes": [],
            "param_links": [],
        }
        for i in range(clip_count)
    ]
    show_data = {
        "schema_version": 4,
        "duration_ms": 10000,
        "clips": clips,
        "groups": [],
        "patterns": [],
        "pattern_instances": [],
        "markers": [],
        "mixer": {},
        "cue_list": {"cues": []},
    }
    show_file = folder / "show.json"
    rig_file = folder / "rig.json"
    show_file.write_text(json.dumps(show_data), encoding="utf-8")
    rig_file.write_text(json.dumps({"fixtures": []}), encoding="utf-8")

    p = MagicMock()
    p.slug = slug
    p.name = slug.replace("_", " ").title()
    p.folder = folder
    p.audio_path = str(folder / "audio.mp3")
    p.show_file = show_file
    p.rig_file = rig_file
    p.analysis_slug = None
    return p


def _make_minimal_session(tmp_path: Path, slug: str, clip_count: int = 3):
    """Construye una ShowSession mínima sin audio ni analysis reales."""
    from server.live_engine import LiveEngine
    from server.session import ShowSession
    from server.tempo_sync import TempoSyncService
    from server.undo_manager import UndoManager
    from src.core.autovj import AutoVJEngine
    from src.core.effects_engine import EffectLibrary
    from src.core.timeline_model import Timeline, make_default_groups

    p = _make_project(tmp_path, slug, clip_count)

    # Mock del project_manager
    pm = MagicMock()
    pm.current = p
    pm.list_projects.return_value = [p]
    pm.open_project.side_effect = lambda s: p if s == slug else None

    s = object.__new__(ShowSession)
    s.project = p
    s._project = p
    s.pm = pm
    s._pm = pm
    s.on_change = None
    s._rev = 0
    s._last_saved_rev = 0
    s._autosave_banner_shown = False

    # Timeline del proyecto inicial
    tl = Timeline.load(p.show_file)
    tl.groups = make_default_groups()
    s.timeline = tl

    s.library = EffectLibrary()
    s.channel_lib = None
    s.presets = MagicMock()
    s.analysis = MagicMock()
    s.analysis.summary = {"bpm": 120.0, "duration_s": 60.0}
    s.bpm = 120.0

    s.show_engine = MagicMock()
    s.show_engine.rig = None
    s.show_engine.router = None

    s.audio = MagicMock()
    s.audio.stop = MagicMock()
    s.audio.load = MagicMock()
    s.audio.duration = 60.0

    s.live_engine = LiveEngine()
    s.autovj_engine = AutoVJEngine()
    s.tempo_sync = TempoSyncService()
    s.hub = None

    s.tl_view = MagicMock()
    s.props = MagicMock()

    s.baked_frames = None
    s.baked_hash = None
    s.render_in_progress = False
    s.render_pct = 0.0
    s.blackout_override = False
    s._identify = {}
    s._test_universes = {}
    s._cue_fade_start_ms = None
    s._cue_fade_duration_ms = 0.0
    s._cue_fade_from_master = 1.0
    s._cue_last_fade_pct = 1.0
    s._cue_auto_follow_task = None
    s.loop = False
    s.rec = False
    s.muted_tracks = set()
    s.solo_tracks = set()
    s._clip_bucket_index = {}
    s._clip_bucket_index_n = -1
    s._pattern_rev = 0
    s._pattern_expanded = []
    s._pattern_expanded_rev = -1
    s.macros = {}
    s.live_input = None
    s._live_mode = False

    s.undo_manager = UndoManager(
        get_clips=lambda: s.timeline.clips,
        restore_clips=lambda clips: None,
    )
    s._qt_call_impl = lambda fn, *a, **kw: fn(*a, **kw)
    s._qt_call_dual_impl = lambda fn, *a, **kw: fn(*a, **kw)
    s._cached_actx = {}

    return s, p


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_switch_project_loads_new_timeline(tmp_path):
    """switch_project carga el show.json del nuevo slug."""
    s, p1 = _make_minimal_session(tmp_path, "proyecto_a", clip_count=3)

    p2 = _make_project(tmp_path, "proyecto_b", clip_count=7)
    s.pm.open_project.side_effect = lambda slug: {
        "proyecto_a": p1, "proyecto_b": p2
    }.get(slug)

    asyncio.new_event_loop().run_until_complete(s.switch_project("proyecto_b"))

    assert s.project.slug == "proyecto_b"
    assert len(s.timeline.clips) == 7


def test_switch_project_old_clips_gone(tmp_path):
    """Los clips del proyecto anterior NO aparecen después del switch."""
    s, p1 = _make_minimal_session(tmp_path, "proyecto_a", clip_count=5)

    p2 = _make_project(tmp_path, "proyecto_b", clip_count=2)
    s.pm.open_project.side_effect = lambda slug: {
        "proyecto_a": p1, "proyecto_b": p2
    }.get(slug)

    # Verifica que antes hay 5 clips
    assert len(s.timeline.clips) == 5

    asyncio.new_event_loop().run_until_complete(s.switch_project("proyecto_b"))

    assert len(s.timeline.clips) == 2, (
        "Después del switch NO deben quedar clips del proyecto anterior"
    )


def test_switch_project_live_engine_clean(tmp_path):
    """El live engine queda limpio (sin activos) tras el switch."""
    s, p1 = _make_minimal_session(tmp_path, "proyecto_a")
    p2 = _make_project(tmp_path, "proyecto_b")
    s.pm.open_project.side_effect = lambda slug: {
        "proyecto_a": p1, "proyecto_b": p2
    }.get(slug)

    # Simular un slot activo inyectando directamente en _active
    from server.live_engine import ActiveSlot
    s.live_engine._active["slot_fake"] = ActiveSlot(
        slot_uid="slot_fake", pattern_uid="pat_x",
        started_at_ms=0.0, mode="loop",
    )
    assert len(s.live_engine._active) == 1

    asyncio.new_event_loop().run_until_complete(s.switch_project("proyecto_b"))

    assert len(s.live_engine._active) == 0, "Live engine debe quedar limpio tras el switch"


def test_switch_project_emits_project_changed(tmp_path):
    """project_changed se emite al stream (hub.broadcast llamado)."""
    s, p1 = _make_minimal_session(tmp_path, "proyecto_a")
    p2 = _make_project(tmp_path, "proyecto_b")
    s.pm.open_project.side_effect = lambda slug: {
        "proyecto_a": p1, "proyecto_b": p2
    }.get(slug)

    hub = MagicMock()
    hub.broadcast = AsyncMock()
    s.hub = hub

    asyncio.new_event_loop().run_until_complete(s.switch_project("proyecto_b"))

    hub.broadcast.assert_called_once()
    call_args = hub.broadcast.call_args[0][0]
    assert call_args["type"] == "project_changed"
    assert call_args["slug"] == "proyecto_b"


def test_switch_project_invalid_slug_raises(tmp_path):
    """Switch a slug inexistente → ValueError, sesión no queda en estado parcial."""
    s, p1 = _make_minimal_session(tmp_path, "proyecto_a", clip_count=4)
    s.pm.open_project.return_value = None

    import pytest
    with pytest.raises(ValueError, match="no encontrado"):
        asyncio.new_event_loop().run_until_complete(s.switch_project("slug_que_no_existe"))

    # El proyecto no cambió
    assert s.project.slug == "proyecto_a"
    assert len(s.timeline.clips) == 4


def test_list_projects_handler(tmp_path):
    """list_projects devuelve la lista de proyectos con el current marcado."""
    from server.dispatcher import Dispatcher
    s, p1 = _make_minimal_session(tmp_path, "proyecto_a")
    p2 = _make_project(tmp_path, "proyecto_b")
    s.pm.list_projects.return_value = [p1, p2]

    disp = Dispatcher(s)
    resp = disp.handle({"method": "list_projects", "params": {}})
    result = resp.get("result", resp)

    assert result["ok"] is True
    slugs = [p["slug"] for p in result["projects"]]
    assert "proyecto_a" in slugs
    assert "proyecto_b" in slugs
    assert result["current"] == "proyecto_a"


def test_switch_project_handler_returns_ok(tmp_path):
    """switch_project handler devuelve ok=True y lanza la tarea."""
    from server.dispatcher import Dispatcher
    s, p1 = _make_minimal_session(tmp_path, "proyecto_a")
    p2 = _make_project(tmp_path, "proyecto_b")
    s.pm.open_project.side_effect = lambda slug: {
        "proyecto_a": p1, "proyecto_b": p2
    }.get(slug)

    disp = Dispatcher(s)

    with patch("asyncio.create_task") as mock_task:
        resp = disp.handle({"method": "switch_project", "params": {"slug": "proyecto_b"}})
        result = resp.get("result", resp)

    assert result["ok"] is True
    assert result["slug"] == "proyecto_b"
    mock_task.assert_called_once()


def test_switch_project_handler_unknown_slug(tmp_path):
    """switch_project handler con slug inválido → ok=False."""
    from server.dispatcher import Dispatcher
    s, p1 = _make_minimal_session(tmp_path, "proyecto_a")
    s.pm.open_project.return_value = None

    disp = Dispatcher(s)
    resp = disp.handle({"method": "switch_project", "params": {"slug": "fantasma"}})
    result = resp.get("result", resp)

    assert result["ok"] is False
