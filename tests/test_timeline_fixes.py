"""
test_timeline_fixes.py — arreglos del timeline/patch (jun 2026).

Cubre:
- move_clip con new_track / new_layer (arrastre vertical entre bars y capas).
- set_clip_preset (pintar un preset sobre un clip existente).
- rig-sync: los mutadores de fixtures regeneran rig_layout.json del visor 3D.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.session import ShowSession  # noqa: E402
from server.dispatcher import Dispatcher  # noqa: E402


@pytest.fixture(scope="module")
def disp():
    return Dispatcher(ShowSession())


def _add(disp, **kw):
    base = {"track": 0, "start_ms": 1000, "end_ms": 2000, "effect_id": 0}
    base.update(kw)
    return disp.call("add_clip", base)["clip"]["id"]


# ── move_clip: track + layer ────────────────────────────────────────────────
def test_move_clip_new_track(disp):
    cid = _add(disp, track=0)
    mv = disp.call("move_clip", {"clip_id": cid, "new_track": 5})
    assert mv["ok"] is True and mv["clip"]["track"] == 5
    disp.call("delete_clip", {"clip_id": cid})


def test_move_clip_new_layer(disp):
    cid = _add(disp, layer=0)
    mv = disp.call("move_clip", {"clip_id": cid, "new_layer": 2})
    assert mv["ok"] is True and mv["clip"]["layer"] == 2
    disp.call("delete_clip", {"clip_id": cid})


def test_move_clip_track_and_layer_and_time(disp):
    cid = _add(disp, track=1, layer=0)
    mv = disp.call("move_clip", {"clip_id": cid, "new_track": 7,
                                 "new_layer": 1, "new_start_ms": 3000})
    c = mv["clip"]
    assert c["track"] == 7 and c["layer"] == 1 and c["start_ms"] == 3000
    disp.call("delete_clip", {"clip_id": cid})


# ── set_clip_preset ─────────────────────────────────────────────────────────
def test_set_clip_preset_pixel(disp):
    eff = next(e for e in disp.call("list_effects")["effects"] if e["name"] == "color_flash")
    pid = disp.call("create_preset", {"name": "TP Azul", "base_effect_id": eff["id"],
                                      "params": {"hue": 200}, "color": "#0000ff",
                                      "scope": "project"})["preset"]["preset_id"]
    cid = _add(disp, effect_id=0)
    r = disp.call("set_clip_preset", {"clip_id": cid, "preset_id": pid})
    assert r["ok"] is True
    c = r["clip"]
    assert c["preset_id"] == pid
    assert c["effect_id"] == eff["id"]   # adopta el efecto base del preset
    assert c["color"] == "#0000ff"
    assert c["params"]["hue"] == 200
    disp.call("delete_clip", {"clip_id": cid})
    disp.call("delete_preset", {"preset_id": pid})


def test_set_clip_preset_missing(disp):
    cid = _add(disp)
    r = disp.call("set_clip_preset", {"clip_id": cid, "preset_id": "no-existe"})
    assert r["ok"] is False
    disp.call("delete_clip", {"clip_id": cid})


# ── rig-sync (_RIG_MUTATORS) ────────────────────────────────────────────────
def test_move_fixture_triggers_rig_sync(disp, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(disp.session, "sync_rig_layout",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    fx = disp.call("list_fixtures")["fixtures"][0]
    r = disp.call("move_fixture", {"fixture_id": fx["fixture_id"],
                                   "position": [1.0, 2.0, 3.0]})
    assert r["ok"] is True
    assert calls["n"] >= 1
