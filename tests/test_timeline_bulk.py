"""
test_timeline_bulk.py — Tests Timeline v2 Fase B: mutaciones de clips en lote.

Cubre:
  test_bulk_move_clips            — mueve N clips (start/track/layer) en una llamada
  test_bulk_move_preserves_duration — solo new_start_ms conserva la duración
  test_bulk_move_unknown_id       — clip_id inexistente → error sin mutar nada
  test_bulk_move_skips_locked     — los bloqueados se saltan y reportan
  test_bulk_delete_clips          — borra N clips; ids inexistentes se ignoran
  test_bulk_delete_skips_locked   — los bloqueados no se borran
  test_bulk_add_clips             — crea N clips con uids nuevos
  test_bulk_add_validates_all     — un item inválido → error y NO se crea ninguno
  test_move_range_atomic          — mueve la sección (copias + borrado) en un paso
  test_move_range_parity_with_combo — mismo resultado que duplicate_range+delete_range
"""
from src.core.timeline_model import Clip, Timeline

from server.handlers.clips_bulk import (
    _h_bulk_add_clips,
    _h_bulk_delete_clips,
    _h_bulk_move_clips,
    _h_move_range,
)
from server.handlers.clips_edit import _h_delete_range, _h_duplicate_range


class _FakeSession:
    def __init__(self):
        self.timeline = Timeline()
        self._snapshots: list = []

    def snapshot(self):
        self._snapshots.append([c.to_dict() for c in self.timeline.clips])

    def invalidate_caches(self):
        pass

    def find_clip_by_id(self, clip_id):
        return next((c for c in self.timeline.clips if c.uid == str(clip_id)), None)


def _add(tl: Timeline, uid: str, track: int, start_ms: int, end_ms: int,
         locked: bool = False) -> Clip:
    c = Clip(track=track, start_ms=start_ms, end_ms=end_ms, effect_id=1,
             scope="per_bar", uid=uid)
    c.locked = locked
    tl.clips.append(c)
    return c


# ── bulk_move_clips ───────────────────────────────────────────────────────────

def test_bulk_move_clips():
    s = _FakeSession()
    _add(s.timeline, "a", 0, 1000, 2000)
    _add(s.timeline, "b", 1, 3000, 4000)
    r = _h_bulk_move_clips(s, {"moves": [
        {"clip_id": "a", "new_start_ms": 5000, "new_track": 2, "new_layer": 1},
        {"clip_id": "b", "new_start_ms": 8000},
    ]})
    assert r["ok"] is True and r["moved"] == 2
    a = s.find_clip_by_id("a")
    assert (a.start_ms, a.end_ms, a.track, a.layer) == (5000, 6000, 2, 1)
    b = s.find_clip_by_id("b")
    assert (b.start_ms, b.end_ms) == (8000, 9000)


def test_bulk_move_preserves_duration():
    s = _FakeSession()
    _add(s.timeline, "a", 0, 1000, 3500)
    r = _h_bulk_move_clips(s, {"moves": [{"clip_id": "a", "new_start_ms": 0}]})
    assert r["ok"] is True
    a = s.find_clip_by_id("a")
    assert a.end_ms - a.start_ms == 2500


def test_bulk_move_unknown_id():
    s = _FakeSession()
    _add(s.timeline, "a", 0, 1000, 2000)
    r = _h_bulk_move_clips(s, {"moves": [
        {"clip_id": "a", "new_start_ms": 5000},
        {"clip_id": "nope", "new_start_ms": 0},
    ]})
    assert r["ok"] is False
    # validación previa: NADA se movió
    assert s.find_clip_by_id("a").start_ms == 1000


def test_bulk_move_skips_locked():
    s = _FakeSession()
    _add(s.timeline, "a", 0, 1000, 2000, locked=True)
    _add(s.timeline, "b", 0, 3000, 4000)
    r = _h_bulk_move_clips(s, {"moves": [
        {"clip_id": "a", "new_start_ms": 0},
        {"clip_id": "b", "new_start_ms": 0},
    ]})
    assert r["ok"] is True and r["moved"] == 1
    assert r["skipped_locked"] == ["a"]
    assert s.find_clip_by_id("a").start_ms == 1000
    assert s.find_clip_by_id("b").start_ms == 0


# ── bulk_delete_clips ─────────────────────────────────────────────────────────

def test_bulk_delete_clips():
    s = _FakeSession()
    _add(s.timeline, "a", 0, 0, 1000)
    _add(s.timeline, "b", 1, 0, 1000)
    _add(s.timeline, "c", 2, 0, 1000)
    r = _h_bulk_delete_clips(s, {"clip_ids": ["a", "c", "no_existe"]})
    assert r["ok"] is True and r["deleted"] == 2
    assert [c.uid for c in s.timeline.clips] == ["b"]


def test_bulk_delete_skips_locked():
    s = _FakeSession()
    _add(s.timeline, "a", 0, 0, 1000, locked=True)
    _add(s.timeline, "b", 1, 0, 1000)
    r = _h_bulk_delete_clips(s, {"clip_ids": ["a", "b"]})
    assert r["ok"] is True and r["deleted"] == 1
    assert r["skipped_locked"] == ["a"]
    assert s.find_clip_by_id("a") is not None


# ── bulk_add_clips ────────────────────────────────────────────────────────────

def test_bulk_add_clips():
    s = _FakeSession()
    r = _h_bulk_add_clips(s, {"clips": [
        {"track": 0, "start_ms": 0, "end_ms": 500, "effect_id": 1, "label": "x"},
        {"track": 3, "start_ms": 1000, "end_ms": 2000, "effect_id": 2, "layer": 1},
    ]})
    assert r["ok"] is True and len(r["clips"]) == 2
    assert len(s.timeline.clips) == 2
    uids = {c["id"] for c in r["clips"]}
    assert len(uids) == 2  # uids nuevos y únicos
    assert s.timeline.clips[1].layer == 1


def test_bulk_add_validates_all():
    s = _FakeSession()
    r = _h_bulk_add_clips(s, {"clips": [
        {"track": 0, "start_ms": 0, "end_ms": 500, "effect_id": 1},
        {"track": 1, "start_ms": 2000, "end_ms": 1000, "effect_id": 1},  # inválido
    ]})
    assert r["ok"] is False
    assert len(s.timeline.clips) == 0  # no se creó NINGUNO


# ── move_range ────────────────────────────────────────────────────────────────

def test_move_range_atomic():
    s = _FakeSession()
    _add(s.timeline, "a", 0, 1000, 2000)
    _add(s.timeline, "b", 1, 1500, 2500)
    _add(s.timeline, "fuera", 2, 9000, 9500)
    r = _h_move_range(s, {"t0_ms": 1000, "t1_ms": 3000, "dest_ms": 5000})
    assert r["ok"] is True and r["moved"] == 2 and r["deleted"] == 2
    starts = sorted(c.start_ms for c in s.timeline.clips if c.uid != "fuera")
    assert starts == [5000, 5500]
    assert s.find_clip_by_id("fuera").start_ms == 9000


def test_move_range_parity_with_combo():
    """move_range == duplicate_range + delete_range (misma semántica de solape)."""
    def build():
        s = _FakeSession()
        _add(s.timeline, "in1", 0, 1000, 2000)
        _add(s.timeline, "cruza", 1, 500, 1500)   # solapa el rango, start fuera
        _add(s.timeline, "fuera", 2, 9000, 9500)
        return s

    s1 = build()
    _h_move_range(s1, {"t0_ms": 1000, "t1_ms": 3000, "dest_ms": 5000})

    s2 = build()
    _h_duplicate_range(s2, {"t0_ms": 1000, "t1_ms": 3000, "dest_ms": 5000})
    _h_delete_range(s2, {"start_ms": 1000, "end_ms": 3000})

    key = lambda s: sorted((c.track, c.start_ms, c.end_ms) for c in s.timeline.clips)
    assert key(s1) == key(s2)
