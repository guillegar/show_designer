"""
test_groups_collapse.py — Tests I3: get_group_clips (ROADMAP v4).

Cubre:
  test_get_group_clips_basic      — devuelve clips de las barras del grupo
  test_get_group_clips_unknown    — grupo inexistente → error
  test_get_group_clips_empty      — grupo sin clips → lista vacía
  test_get_group_clips_filters_fx — clips de fixtures no se incluyen (scope≠per_bar)
  test_get_group_clips_partial    — solo las barras del grupo, no todas
"""
from unittest.mock import MagicMock

import pytest

from server.dispatcher import _h_get_group_clips
from src.core.timeline_model import BarGroup, Clip, Timeline

# ── Fake session ──────────────────────────────────────────────────────────────

class _FakeSession:
    def __init__(self):
        self.timeline = Timeline()

    def snapshot(self):
        pass

    def invalidate_caches(self):
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _add_clip(tl: Timeline, clip_id: str, track: int, start_ms: int = 0, end_ms: int = 1000,
              category: str = "pixel") -> None:
    c = Clip(
        track=track,
        start_ms=start_ms,
        end_ms=end_ms,
        effect_id=1,
        scope="per_bar",
        label="Test",
        color="#ff0000",
        layer=0,
        category=category,
        uid=clip_id,
    )
    tl.clips.append(c)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_get_group_clips_basic():
    """get_group_clips retorna los clips de las barras del grupo."""
    session = _FakeSession()
    session.timeline.groups = [BarGroup(name="IZQ", bars=[0, 1, 2, 3, 4], color="#ff0000")]
    _add_clip(session.timeline, "c0", track=0)
    _add_clip(session.timeline, "c2", track=2)
    _add_clip(session.timeline, "c7", track=7)  # fuera del grupo

    r = _h_get_group_clips(session, {"group_name": "IZQ"})
    assert r["ok"] is True
    ids = {c["id"] for c in r["clips"]}
    assert "c0" in ids
    assert "c2" in ids
    assert "c7" not in ids


def test_get_group_clips_unknown():
    """Grupo inexistente → error."""
    session = _FakeSession()
    r = _h_get_group_clips(session, {"group_name": "NOPE"})
    assert r["ok"] is False
    assert "NOPE" in r["error"]


def test_get_group_clips_empty():
    """Grupo sin clips → lista vacía, ok True."""
    session = _FakeSession()
    session.timeline.groups = [BarGroup(name="DER", bars=[5, 6, 7, 8, 9], color="#0000ff")]
    r = _h_get_group_clips(session, {"group_name": "DER"})
    assert r["ok"] is True
    assert r["clips"] == []


def test_get_group_clips_partial():
    """Solo las barras del grupo se incluyen, no las externas."""
    session = _FakeSession()
    session.timeline.groups = [BarGroup(name="PARES", bars=[0, 2, 4, 6, 8], color="#00ff00")]
    for i in range(10):
        _add_clip(session.timeline, f"c{i}", track=i)

    r = _h_get_group_clips(session, {"group_name": "PARES"})
    assert r["ok"] is True
    tracks = {c["track"] for c in r["clips"]}
    assert tracks == {0, 2, 4, 6, 8}


def test_get_group_clips_filters_fx():
    """Clips de fixtures (category='fixture') no se incluyen."""
    session = _FakeSession()
    session.timeline.groups = [BarGroup(name="IZQ", bars=[0, 1], color="#ff0000")]
    _add_clip(session.timeline, "c0", track=0, category="pixel")
    _add_clip(session.timeline, "cfx", track=0, category="fixture")

    r = _h_get_group_clips(session, {"group_name": "IZQ"})
    assert r["ok"] is True
    ids = {c["id"] for c in r["clips"]}
    assert "c0" in ids
    assert "cfx" not in ids
