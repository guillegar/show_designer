"""
test_micro_events.py — Tests A4: Micro-eventos (ROADMAP v2).

Cubre:
  - MicroEvent.is_active_at (dentro/fuera/bordes de ventana)
  - MicroEventStage.apply (fast path, merge, sin mutación, múltiples eventos)
  - Clip.events persistencia (to_dict / from_dict / show legacy)
  - Handlers del dispatcher (add / delete / update_micro_event)
  - Undo (invariante I1: events van en el snapshot vía clip.to_dict)
"""
from unittest.mock import MagicMock

import pytest

from src.core.micro_events import MicroEvent, MicroEventStage
from src.core.timeline_model import Clip

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_clip(**kwargs) -> Clip:
    defaults = dict(track=0, start_ms=0, end_ms=4000, effect_id=1, params={"brightness": 0.5})
    defaults.update(kwargs)
    return Clip(**defaults)


def make_session_with_clip(clip: Clip):
    """Session mock mínimo para los handlers del dispatcher."""
    import json
    import os
    import tempfile
    from pathlib import Path

    from server.session import ShowSession

    tmp = tempfile.mkdtemp()
    show_path = Path(tmp) / "show_timeline.json"
    show_path.write_text(json.dumps({
        "version": 3,
        "clips": [clip.to_dict()],
        "groups": [], "cue_points": [],
        "automation": [], "patterns": [], "pattern_instances": [],
        "mixer": {},
    }))
    session = ShowSession.__new__(ShowSession)
    # Inicialización mínima requerida por los handlers
    from src.core.timeline_model import Timeline
    session.timeline = Timeline.__new__(Timeline)
    session.timeline.clips = [clip]
    session.timeline.automation = []
    session.timeline.patterns = []
    session.timeline.pattern_instances = []
    session._snapshot_stack = []
    session._redo_stack = []

    def _snapshot():
        import copy
        session._snapshot_stack.append({
            "clips": [c.to_dict() for c in session.timeline.clips],
            "extra": {},
        })
    session.snapshot = _snapshot

    def _find(clip_id):
        return next((c for c in session.timeline.clips if c.uid == clip_id), None)
    session.find_clip_by_id = _find
    session.invalidate_caches = MagicMock()
    return session


# ── 1. MicroEvent modelo ──────────────────────────────────────────────────────

def test_micro_event_is_active_inside_window():
    ev = MicroEvent(t_ms_rel=500, duration_ms=100)
    assert ev.is_active_at(500)   # borde izquierdo (inclusivo)
    assert ev.is_active_at(550)   # centro
    assert ev.is_active_at(599)   # justo antes del borde derecho


def test_micro_event_is_not_active_at_right_boundary():
    ev = MicroEvent(t_ms_rel=500, duration_ms=100)
    assert not ev.is_active_at(600)   # borde derecho exclusivo


def test_micro_event_is_not_active_before():
    ev = MicroEvent(t_ms_rel=500, duration_ms=100)
    assert not ev.is_active_at(499)
    assert not ev.is_active_at(0)


def test_micro_event_roundtrip():
    ev = MicroEvent(t_ms_rel=1234, duration_ms=75, params_override={"brightness": 1.0, "hue": 200})
    d = ev.to_dict()
    ev2 = MicroEvent.from_dict(d)
    assert ev2.uid == ev.uid
    assert ev2.t_ms_rel == 1234
    assert ev2.duration_ms == 75
    assert ev2.params_override == {"brightness": 1.0, "hue": 200}


def test_micro_event_from_dict_generates_uid_if_missing():
    ev = MicroEvent.from_dict({"t_ms_rel": 0, "duration_ms": 100})
    assert ev.uid and len(ev.uid) == 12


def test_micro_event_default_duration():
    ev = MicroEvent()
    assert ev.duration_ms == 100


# ── 2. MicroEventStage ────────────────────────────────────────────────────────

def test_stage_fast_path_no_events():
    """Sin eventos → devuelve el mismo objeto (cero allocs)."""
    stage = MicroEventStage()
    clip = make_clip()
    params = {"brightness": 0.5}
    result = stage.apply(params, clip, t_ms=1000, audio_context={})
    assert result is params   # identidad, no copia


def test_stage_merges_params_override():
    ev = MicroEvent(t_ms_rel=1000, duration_ms=100, params_override={"brightness": 1.0})
    clip = make_clip(start_ms=0, events=[ev.to_dict()])
    stage = MicroEventStage()
    # t_ms=1050 → clip_elapsed=1050, dentro de la ventana [1000, 1100)
    result = stage.apply({"brightness": 0.2, "hue": 120}, clip, t_ms=1050, audio_context={})
    assert result["brightness"] == 1.0   # override aplicado
    assert result["hue"] == 120           # param no sobreescrito intacto


def test_stage_does_not_activate_outside_window():
    ev = MicroEvent(t_ms_rel=1000, duration_ms=100, params_override={"brightness": 1.0})
    clip = make_clip(start_ms=0, events=[ev.to_dict()])
    stage = MicroEventStage()
    # t_ms=1100 → clip_elapsed=1100, fuera de ventana [1000, 1100)
    params = {"brightness": 0.2}
    result = stage.apply(params, clip, t_ms=1100, audio_context={})
    assert result is params   # fast path, mismo objeto
    assert result["brightness"] == 0.2


def test_stage_does_not_mutate_original_params():
    ev = MicroEvent(t_ms_rel=0, duration_ms=200, params_override={"brightness": 1.0})
    clip = make_clip(start_ms=0, events=[ev.to_dict()])
    stage = MicroEventStage()
    original = {"brightness": 0.3}
    result = stage.apply(original, clip, t_ms=50, audio_context={})
    assert result is not original
    assert original["brightness"] == 0.3   # no mutado


def test_stage_multiple_events_all_active_merged():
    """Dos eventos activos simultáneos: el último en la lista gana (update orden)."""
    ev1 = MicroEvent(t_ms_rel=0, duration_ms=200, params_override={"brightness": 0.7})
    ev2 = MicroEvent(t_ms_rel=0, duration_ms=200, params_override={"brightness": 1.0, "hue": 50})
    clip = make_clip(start_ms=0, events=[ev1.to_dict(), ev2.to_dict()])
    stage = MicroEventStage()
    result = stage.apply({"brightness": 0.1, "hue": 0}, clip, t_ms=100, audio_context={})
    assert result["brightness"] == 1.0   # ev2 gana (aplica después)
    assert result["hue"] == 50


def test_stage_with_clip_start_offset():
    """clip.start_ms no es 0: t_ms_rel se calcula como t_ms - clip.start_ms."""
    ev = MicroEvent(t_ms_rel=500, duration_ms=100, params_override={"brightness": 1.0})
    clip = make_clip(start_ms=2000, events=[ev.to_dict()])
    stage = MicroEventStage()
    # clip_elapsed = 2550 - 2000 = 550, dentro de [500, 600)
    result = stage.apply({"brightness": 0.0}, clip, t_ms=2550, audio_context={})
    assert result["brightness"] == 1.0
    # clip_elapsed = 2600 - 2000 = 600, fuera
    params = {"brightness": 0.0}
    result2 = stage.apply(params, clip, t_ms=2600, audio_context={})
    assert result2 is params


# ── 3. Clip.events persistencia ───────────────────────────────────────────────

def test_clip_events_to_dict_and_from_dict():
    ev = MicroEvent(t_ms_rel=200, duration_ms=50, params_override={"brightness": 0.9})
    clip = make_clip(events=[ev.to_dict()])
    d = clip.to_dict()
    assert "events" in d
    assert len(d["events"]) == 1
    assert d["events"][0]["t_ms_rel"] == 200

    clip2 = Clip.from_dict(d)
    assert len(clip2.events) == 1
    assert clip2.events[0]["t_ms_rel"] == 200


def test_clip_legacy_without_events_field():
    """Un clip serializado sin 'events' (show antiguo) carga con events=[]."""
    d = {
        "track": 0, "start_ms": 0, "end_ms": 1000, "effect_id": 1,
        "scope": "per_bar", "params": {}, "uid": "aabbcc112233",
        # 'events' no presente (show legacy)
    }
    clip = Clip.from_dict(d)
    assert clip.events == []


def test_clip_events_empty_by_default():
    clip = make_clip()
    assert clip.events == []
    d = clip.to_dict()
    assert d["events"] == []


# ── 4. Handlers del dispatcher ────────────────────────────────────────────────

def _dispatch(method, params):
    from server.dispatcher import handle
    session_store = {}
    return handle


def _call_handler(handler_name, session, params):
    import server.dispatcher as disp
    handler = disp._LOCAL[handler_name]
    return handler(session, params)


def test_handler_add_micro_event():
    clip = make_clip()
    session = make_session_with_clip(clip)
    result = _call_handler("add_micro_event", session, {
        "clip_id": clip.uid,
        "t_ms_rel": 1000,
        "duration_ms": 150,
        "params_override": {"brightness": 1.0},
    })
    assert result["ok"] is True
    assert len(result["clip"]["events"]) == 1
    ev = result["clip"]["events"][0]
    assert ev["t_ms_rel"] == 1000
    assert ev["duration_ms"] == 150
    assert ev["params_override"]["brightness"] == 1.0
    assert "uid" in ev


def test_handler_add_micro_event_invalid_clip():
    clip = make_clip()
    session = make_session_with_clip(clip)
    result = _call_handler("add_micro_event", session, {
        "clip_id": "nonexistent",
        "t_ms_rel": 0,
    })
    assert result["ok"] is False


def test_handler_add_micro_event_invalid_duration():
    clip = make_clip()
    session = make_session_with_clip(clip)
    result = _call_handler("add_micro_event", session, {
        "clip_id": clip.uid,
        "t_ms_rel": 0,
        "duration_ms": 0,
    })
    assert result["ok"] is False


def test_handler_delete_micro_event():
    ev = MicroEvent(t_ms_rel=500, duration_ms=100, params_override={"brightness": 1.0})
    clip = make_clip(events=[ev.to_dict()])
    session = make_session_with_clip(clip)
    result = _call_handler("delete_micro_event", session, {
        "clip_id": clip.uid,
        "event_uid": ev.uid,
    })
    assert result["ok"] is True
    assert result["clip"]["events"] == []


def test_handler_delete_micro_event_nonexistent_uid():
    ev = MicroEvent(t_ms_rel=500, duration_ms=100)
    clip = make_clip(events=[ev.to_dict()])
    session = make_session_with_clip(clip)
    result = _call_handler("delete_micro_event", session, {
        "clip_id": clip.uid,
        "event_uid": "nonexistent_uid",
    })
    assert result["ok"] is False


def test_handler_update_micro_event_partial():
    ev = MicroEvent(t_ms_rel=500, duration_ms=100, params_override={"brightness": 0.5})
    clip = make_clip(events=[ev.to_dict()])
    session = make_session_with_clip(clip)
    result = _call_handler("update_micro_event", session, {
        "clip_id": clip.uid,
        "event_uid": ev.uid,
        "t_ms_rel": 800,
        # duration_ms y params_override NO enviados → se conservan
    })
    assert result["ok"] is True
    updated = result["clip"]["events"][0]
    assert updated["t_ms_rel"] == 800
    assert updated["duration_ms"] == 100       # conservado
    assert updated["params_override"] == {"brightness": 0.5}  # conservado


def test_handler_update_micro_event_params_override():
    ev = MicroEvent(t_ms_rel=0, duration_ms=50, params_override={"brightness": 0.1})
    clip = make_clip(events=[ev.to_dict()])
    session = make_session_with_clip(clip)
    result = _call_handler("update_micro_event", session, {
        "clip_id": clip.uid,
        "event_uid": ev.uid,
        "params_override": {"brightness": 1.0, "hue": 240},
    })
    assert result["ok"] is True
    updated = result["clip"]["events"][0]
    assert updated["params_override"] == {"brightness": 1.0, "hue": 240}


# ── 5. Undo (invariante I1) ───────────────────────────────────────────────────

def test_undo_restores_events():
    """Añadir un micro-evento, deshacer → events vacíos de nuevo.

    UndoManager.snapshot() se llama ANTES de cada mutación (guarda el estado previo).
    undo() restaura el último snapshot guardado.
    """
    from src.core.undo import UndoManager

    clip = make_clip()
    clips_store = [clip]

    def get_clips():
        return clips_store

    def restore_clips(snap_list):
        clips_store[0] = Clip.from_dict(snap_list[0])

    undo = UndoManager(get_clips=get_clips, restore_clips=restore_clips)

    # Paso 1: snapshot ANTES de la mutación (guarda events=[])
    undo.snapshot()

    # Paso 2: mutar
    ev = MicroEvent(t_ms_rel=100, duration_ms=50, params_override={"brightness": 1.0})
    clips_store[0].events = [ev.to_dict()]
    assert len(clips_store[0].events) == 1

    # Paso 3: undo restaura el snapshot previo (events=[])
    undo.undo()
    assert clips_store[0].events == []
