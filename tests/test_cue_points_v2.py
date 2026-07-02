"""
test_cue_points_v2.py — Tests I2: Marcadores de timeline con nombre, color y
categoría (ROADMAP v4).

Cubre:
  test_marker_roundtrip          — show.json ← save → load preserva name+color+category
  test_filter_by_category        — list_markers(category=X) devuelve solo los de esa cat
  test_migration_defaults        — show sin markers carga con lista vacía (migración)
  test_update_marker_i3          — update_marker devuelve el marcador actualizado (I3)
  test_undo_covers_markers       — add_marker → undo → automation vacía (I1)
  test_add_marker_replaces       — add dos veces en el mismo t_ms → solo 1 marcador
  test_delete_marker             — delete_marker elimina el marcador
  test_invalid_category_defaults — categoría desconocida → "custom"
"""
from unittest.mock import MagicMock

import pytest

from server.dispatcher import (
    _h_add_marker,
    _h_delete_marker,
    _h_list_markers,
    _h_update_marker,
)
from src.core.timeline_model import Marker, Timeline

# ── Fake session ──────────────────────────────────────────────────────────────

class _FakeSession:
    def __init__(self):
        self.timeline = Timeline()
        self._snapshots: list = []

    def snapshot(self):
        self._snapshots.append([m.to_dict() for m in self.timeline.markers])

    def _undo(self):
        if self._snapshots:
            raw = self._snapshots.pop()
            self.timeline.markers = [Marker.from_dict(d) for d in raw]

    def invalidate_caches(self):
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _add(session, t_ms, name, color="#888888", category="custom"):
    return _h_add_marker(session, {"time_ms": t_ms, "name": name, "color": color, "category": category})


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_marker_roundtrip(tmp_path):
    """show.json ← save → load preserva name, color y category."""
    tl = Timeline()
    tl.markers = [
        Marker(t_ms=1000, name="Intro", color="#ff0000", category="intro"),
        Marker(t_ms=5000, name="Estribillo", color="#00ff00", category="estribillo"),
    ]
    path = tmp_path / "show.json"
    tl.save(path)
    loaded = Timeline.load(path)
    assert len(loaded.markers) == 2
    assert loaded.markers[0].name == "Intro"
    assert loaded.markers[0].color == "#ff0000"
    assert loaded.markers[0].category == "intro"
    assert loaded.markers[1].category == "estribillo"


def test_filter_by_category():
    """list_markers(category='intro') devuelve solo los marcadores de esa categoría."""
    session = _FakeSession()
    _add(session, 1000, "Intro", category="intro")
    _add(session, 2000, "Verso", category="verso")
    _add(session, 3000, "Otro Intro", category="intro")

    r = _h_list_markers(session, {"category": "intro"})
    assert r["ok"] is True
    assert len(r["markers"]) == 2
    assert all(m["category"] == "intro" for m in r["markers"])


def test_migration_defaults(tmp_path):
    """Show.json sin campo 'markers' carga con lista vacía (migración tolerante)."""
    import json
    data = {"version": 4, "duration_ms": 165000, "clips": [], "groups": [],
            "cue_points": [], "automation": [], "patterns": [], "pattern_instances": [],
            "mixer": {}, "live_slots": {}, "cue_list": {"entries": []}}
    path = tmp_path / "show_old.json"
    with open(path, "w") as f:
        json.dump(data, f)
    tl = Timeline.load(path)
    assert tl.markers == []


def test_update_marker_i3():
    """update_marker devuelve el marcador actualizado (invariante I3)."""
    session = _FakeSession()
    _add(session, 1000, "Old Name", color="#111111", category="custom")

    r = _h_update_marker(session, {"t_ms": 1000, "name": "New Name", "color": "#ff0000", "category": "intro"})
    assert r["ok"] is True
    marker = r["marker"]
    assert marker["name"] == "New Name"
    assert marker["color"] == "#ff0000"
    assert marker["category"] == "intro"
    # El marcador en el timeline también está actualizado
    assert session.timeline.markers[0].name == "New Name"


def test_undo_covers_markers():
    """add_marker → snapshot → undo → marcadores eliminados (invariante I1)."""
    session = _FakeSession()

    # Simular dispatcher: snapshot ANTES de mutación
    session.snapshot()
    _add(session, 1000, "Test")

    assert len(session.timeline.markers) == 1

    # Undo: restaura al estado anterior (sin marcadores)
    session._undo()
    assert session.timeline.markers == [], "Undo debe eliminar el marcador añadido"


def test_add_marker_replaces():
    """Añadir dos veces en el mismo t_ms → solo queda 1 marcador (el último)."""
    session = _FakeSession()
    _add(session, 1000, "First")
    _add(session, 1000, "Second")

    assert len(session.timeline.markers) == 1
    assert session.timeline.markers[0].name == "Second"


def test_delete_marker():
    """delete_marker elimina el marcador correcto."""
    session = _FakeSession()
    _add(session, 1000, "A")
    _add(session, 2000, "B")

    r = _h_delete_marker(session, {"time_ms": 1000})
    assert r["ok"] is True
    assert r["deleted"] == 1
    assert len(session.timeline.markers) == 1
    assert session.timeline.markers[0].name == "B"


def test_invalid_category_defaults():
    """Categoría desconocida → se almacena como 'custom'."""
    session = _FakeSession()
    r = _h_add_marker(session, {"time_ms": 500, "name": "X", "category": "no_existe"})
    assert r["ok"] is True
    assert r["marker"]["category"] == "custom"

    # También vía update_marker
    r2 = _h_update_marker(session, {"t_ms": 500, "category": "otra_cosa"})
    assert r2["marker"]["category"] == "custom"
