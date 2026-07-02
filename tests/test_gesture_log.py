"""
test_gesture_log.py — Tests para historial de gestos y replay (M3).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from server.dispatcher import Dispatcher
from server.gesture_log import GestureLog
from src.core.timeline_model import Timeline, make_default_groups

# ─── helpers ─────────────────────────────────────────────────────────────────

def _session_with_timeline():
    """Sesión mínima con timeline real y GestureLog."""
    session = MagicMock()
    session._tokens_config = []
    session.snapshot = MagicMock()
    session.invalidate_caches = MagicMock()
    session._current_t_ms = MagicMock(return_value=5000)
    tl = Timeline()
    tl.groups = make_default_groups()
    session.timeline = tl
    session._gesture_log = GestureLog()
    session._pattern_rev = 0
    session._pattern_expanded = []
    session._pattern_expanded_rev = -1
    return session


# ─── tests de GestureLog ─────────────────────────────────────────────────────

def test_gesture_log_records_on_add_clip():
    """Ejecutar add_clip → list_gesture_history incluye la entrada con handler y params."""
    session = _session_with_timeline()
    disp = Dispatcher(session)

    # Simular add_clip (no necesitamos que tenga éxito, solo que se registre)
    with patch.object(disp, '_maybe_sync_rig'):
        from server.dispatcher import _LOCAL
        orig = _LOCAL.get("add_clip")
        # Reemplazar temporalmente con uno que no falle
        _LOCAL["add_clip"] = lambda s, p: {"ok": True, "clip": {"uid": "x123", "track": 0, "start_ms": 0, "end_ms": 1000, "effect_id": 1004, "scope": "per_bar", "params": {}, "color": "#fff", "label": "", "layer": 0, "locked": False, "muted": False, "category": "pixel", "channel_effect_id": None, "preset_id": None, "param_links": [], "events": [], "channel_effects": []}}
        try:
            resp = disp.handle({"method": "add_clip", "params": {"track": 0, "start_ms": 0, "end_ms": 1000, "effect_id": 1004}})
        finally:
            if orig is not None:
                _LOCAL["add_clip"] = orig
            else:
                _LOCAL.pop("add_clip", None)

    history_resp = disp.handle({"method": "list_gesture_history", "params": {}})
    gestures = history_resp["result"]["gestures"]
    assert len(gestures) >= 1
    handlers = [g["handler"] for g in gestures]
    assert "add_clip" in handlers


def test_gesture_log_skips_list_and_get():
    """Handlers list_* y get_* NO se graban."""
    gl = GestureLog()
    gl.record("list_clips", {}, 0)
    gl.record("get_cue_state", {}, 0)
    gl.record("get_rig_layout", {}, 0)
    assert len(gl.list()) == 0


def test_replay_gesture_re_executes():
    """replay_gesture(idx) re-ejecuta el handler con los mismos params."""
    session = _session_with_timeline()
    gl = session._gesture_log
    called_with = []

    from server.dispatcher import _LOCAL
    original = _LOCAL.get("set_macro")
    _LOCAL["set_macro"] = lambda s, p: (called_with.append(p), {"ok": True})[1]
    try:
        gl.record("set_macro", {"name": "brightness", "value": 0.8}, 1000)
        disp = Dispatcher(session)
        idx = gl.list()[0]["idx"]
        resp = disp.handle({"method": "replay_gesture", "params": {"idx": idx}})
        assert resp["result"].get("ok") is True
        assert called_with == [{"name": "brightness", "value": 0.8}]
    finally:
        if original:
            _LOCAL["set_macro"] = original
        else:
            del _LOCAL["set_macro"]


def test_gesture_log_max_entries():
    """MAX_ENTRIES respetado: tras 501 gestos, el más antiguo se descarta."""
    gl = GestureLog()
    for i in range(gl.MAX_ENTRIES + 1):
        gl.record("set_macro", {"n": i}, i)
    entries = gl.list(last=gl.MAX_ENTRIES + 100)  # pedir más que MAX para obtener todos
    assert len(entries) == gl.MAX_ENTRIES
    # El primer gesto (idx 0) debe haberse descartado
    idxs = [e["idx"] for e in entries]
    assert 0 not in idxs
    assert gl.MAX_ENTRIES in idxs  # el último sí está


def test_clear_gesture_history():
    """clear_gesture_history() → list devuelve lista vacía."""
    session = _session_with_timeline()
    gl = session._gesture_log
    gl.record("set_macro", {}, 0)
    gl.record("blackout", {}, 0)
    assert len(gl.list()) == 2

    disp = Dispatcher(session)
    resp = disp.handle({"method": "clear_gesture_history", "params": {}})
    assert resp["result"]["ok"] is True
    history = disp.handle({"method": "list_gesture_history", "params": {}})
    assert history["result"]["gestures"] == []
