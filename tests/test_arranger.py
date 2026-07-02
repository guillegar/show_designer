"""
test_arranger.py — Tests I4: Vista Arranger (duplicate_range + delete_range).

Cubre:
  test_delete_range_basic          — borra clips en el rango especificado
  test_delete_range_partial_overlap — clips que se solapan parcialmente también se borran
  test_delete_range_empty          — rango sin clips → deleted=0
  test_delete_range_invalid        — start >= end → error
  test_delete_range_preserves_outside — clips fuera del rango no se tocan (invariante I2)
  test_duplicate_then_delete       — reordenar sección: duplicate+delete da resultado correcto
  test_undo_delete_range           — undo restaura clips eliminados (invariante I1)
"""
from unittest.mock import MagicMock

import pytest

from server.dispatcher import _h_delete_range, _h_duplicate_range
from src.core.timeline_model import Clip, Timeline

# ── Fake session ──────────────────────────────────────────────────────────────

class _FakeSession:
    def __init__(self):
        self.timeline = Timeline()
        self._snapshots: list = []

    def snapshot(self):
        self._snapshots.append([c.to_dict() for c in self.timeline.clips])

    def _undo(self):
        if self._snapshots:
            raw = self._snapshots.pop()
            from src.core.timeline_model import Clip
            self.timeline.clips = [
                Clip(track=d["track"], start_ms=d["start_ms"], end_ms=d["end_ms"],
                     effect_id=d["effect_id"], scope=d["scope"], uid=d["uid"])
                for d in raw
            ]

    def invalidate_caches(self):
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _add(tl: Timeline, uid: str, track: int, start_ms: int, end_ms: int) -> Clip:
    c = Clip(track=track, start_ms=start_ms, end_ms=end_ms, effect_id=1,
             scope="per_bar", uid=uid)
    tl.clips.append(c)
    return c


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_delete_range_basic():
    """delete_range borra los clips dentro del rango."""
    session = _FakeSession()
    _add(session.timeline, "a", 0, 1000, 3000)
    _add(session.timeline, "b", 1, 5000, 8000)

    r = _h_delete_range(session, {"start_ms": 0, "end_ms": 4000})
    assert r["ok"] is True
    assert r["deleted"] == 1
    ids = {c.uid for c in session.timeline.clips}
    assert "a" not in ids
    assert "b" in ids


def test_delete_range_partial_overlap():
    """Clip que empieza antes del rango pero termina dentro también se borra."""
    session = _FakeSession()
    _add(session.timeline, "a", 0, 0, 5000)       # empieza antes, termina dentro → borrado
    _add(session.timeline, "b", 0, 12000, 15000)  # totalmente después del rango → conservado

    r = _h_delete_range(session, {"start_ms": 3000, "end_ms": 10000})
    assert r["ok"] is True
    assert r["deleted"] == 1
    assert session.timeline.clips[0].uid == "b"


def test_delete_range_empty():
    """Rango sin clips → deleted=0, ok=True."""
    session = _FakeSession()
    _add(session.timeline, "a", 0, 10000, 12000)

    r = _h_delete_range(session, {"start_ms": 0, "end_ms": 5000})
    assert r["ok"] is True
    assert r["deleted"] == 0
    assert len(session.timeline.clips) == 1


def test_delete_range_invalid():
    """start_ms >= end_ms → error."""
    session = _FakeSession()
    r = _h_delete_range(session, {"start_ms": 5000, "end_ms": 5000})
    assert r["ok"] is False
    assert "start_ms" in r["error"]


def test_delete_range_preserves_outside():
    """Clips fuera del rango no se tocan (invariante I2 — no deja huérfanos)."""
    session = _FakeSession()
    _add(session.timeline, "before", 0, 0, 1000)
    _add(session.timeline, "inside", 1, 2000, 4000)
    _add(session.timeline, "after", 2, 8000, 10000)

    r = _h_delete_range(session, {"start_ms": 1500, "end_ms": 5000})
    assert r["ok"] is True
    assert r["deleted"] == 1
    ids = {c.uid for c in session.timeline.clips}
    assert "before" in ids
    assert "inside" not in ids
    assert "after" in ids


def test_duplicate_then_delete():
    """Reordenar una sección: duplicate_range + delete_range mueve los clips."""
    session = _FakeSession()
    _add(session.timeline, "c1", 0, 0, 5000)
    _add(session.timeline, "c2", 1, 1000, 4000)
    _add(session.timeline, "other", 0, 10000, 12000)

    # Mover sección [0..5000) a offset 20000
    _h_duplicate_range(session, {"t0_ms": 0, "t1_ms": 5000, "dest_ms": 20000})
    _h_delete_range(session, {"start_ms": 0, "end_ms": 5000})

    starts = {c.start_ms for c in session.timeline.clips}
    assert 20000 in starts  # c1 movido
    assert 21000 in starts  # c2 movido (offset +20000)
    assert 0 not in starts  # original borrado
    assert 1000 not in starts
    assert 10000 in starts   # other intacto


def test_undo_delete_range():
    """Undo tras delete_range restaura los clips eliminados (invariante I1)."""
    session = _FakeSession()
    _add(session.timeline, "a", 0, 0, 5000)

    _h_delete_range(session, {"start_ms": 0, "end_ms": 6000})
    assert len(session.timeline.clips) == 0

    session._undo()
    assert len(session.timeline.clips) == 1
    assert session.timeline.clips[0].uid == "a"
