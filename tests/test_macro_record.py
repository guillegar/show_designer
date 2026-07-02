"""
test_macro_record.py — Tests I1: Grabación en vivo de macros (ROADMAP v4).

Cubre:
  test_start_record_clears_previous   — grabar, parar, volver a grabar → sin mezcla
  test_points_captured_during_move    — _recording=True + macro activa → puntos capturados
  test_throttle_50ms                  — 10 frames en 30ms → máx 1 punto (throttle)
  test_stop_creates_lanes             — stop_record → timeline.automation tiene lane nueva
  test_lane_target_correct            — lane creada tiene target "master:brightness_mul"
  test_values_normalized              — brightness_mul=1.0 (default) → no se graba punto
  test_undo_covers_lanes              — stop_record → undo → automation vacía
  test_stop_record_idempotent         — stop_record sin start previo → {ok, lanes_created:0}
"""
from unittest.mock import MagicMock

import pytest

from server.dispatcher import _h_get_record_state, _h_start_record, _h_stop_record

# ── Fake session ──────────────────────────────────────────────────────────────

class _FakeTimeline:
    def __init__(self):
        self.automation = []


class _FakeSession:
    """Sesión mínima para tests de grabación."""

    def __init__(self):
        self._recording = False
        self._record_start_ms = 0.0
        self._recorded_lanes: dict = {}
        self._record_last_ms: dict = {}
        self._current_t_ms = 0
        self.timeline = _FakeTimeline()
        self._snapshot_calls = []
        self._invalidate_calls = 0
        self.macros = {
            "brightness_mul": 1.0,
            "speed_mul": 1.0,
            "hue_shift": 0.0,
            "strobe_rate": 0.0,
        }

    def snapshot(self):
        self._snapshot_calls.append(dict(
            automation=list(self.timeline.automation)
        ))

    def invalidate_caches(self):
        self._invalidate_calls += 1

    def _maybe_record_macros(self, t_ms: int) -> None:
        """Replica la lógica de ShowSession._maybe_record_macros para tests."""
        if not self._recording:
            return
        _DEFAULTS = {
            "brightness_mul": 1.0,
            "speed_mul": 1.0,
            "hue_shift": 0.0,
            "strobe_rate": 0.0,
        }
        _NORM = {
            "brightness_mul": lambda v: v / 2.0,
            "speed_mul": lambda v: v / 4.0,
            "hue_shift": lambda v: (v + 180.0) / 360.0,
            "strobe_rate": lambda v: v / 30.0,
        }
        for name in ("brightness_mul", "speed_mul", "hue_shift", "strobe_rate"):
            val = self.macros.get(name, _DEFAULTS[name])
            if val == _DEFAULTS[name]:
                continue
            last = self._record_last_ms.get(name, -9999.0)
            if t_ms - last < 50:
                continue
            normalized = _NORM[name](val)
            self._recorded_lanes.setdefault(name, []).append(
                {"t_ms": t_ms, "value": normalized}
            )
            self._record_last_ms[name] = float(t_ms)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_start_record_clears_previous():
    """Grabar, parar (añade puntos), iniciar de nuevo → _recorded_lanes vacío al second start."""
    session = _FakeSession()
    session._current_t_ms = 1000

    # Primera grabación
    _h_start_record(session, {})
    session.macros["brightness_mul"] = 0.5
    session._maybe_record_macros(1000)
    assert "brightness_mul" in session._recorded_lanes

    # Parar y volver a iniciar
    _h_stop_record(session, {})
    session._current_t_ms = 5000
    _h_start_record(session, {})

    # Las lanes anteriores no se mezclan con la nueva grabación
    assert session._recorded_lanes == {}
    assert session._recording is True


def test_points_captured_during_move():
    """_recording=True + brightness_mul=0.5 → _recorded_lanes["brightness_mul"] tiene puntos."""
    session = _FakeSession()
    session._recording = True
    session._record_start_ms = 0.0
    session.macros["brightness_mul"] = 0.5

    session._maybe_record_macros(t_ms=1000)

    assert "brightness_mul" in session._recorded_lanes
    pts = session._recorded_lanes["brightness_mul"]
    assert len(pts) == 1
    assert pts[0]["t_ms"] == 1000
    # Valor normalizado: 0.5 / 2.0 = 0.25
    assert abs(pts[0]["value"] - 0.25) < 1e-9


def test_throttle_50ms():
    """10 frames en 30ms → máx 1 punto por macro (throttle 50ms)."""
    session = _FakeSession()
    session._recording = True
    session.macros["brightness_mul"] = 0.8

    # 10 llamadas a 3ms de separación (30ms total)
    for i in range(10):
        session._maybe_record_macros(t_ms=i * 3)

    pts = session._recorded_lanes.get("brightness_mul", [])
    assert len(pts) == 1, f"Esperado 1 punto, obtenido {len(pts)}"


def test_stop_creates_lanes():
    """stop_record → session.timeline.automation tiene una lane nueva."""
    session = _FakeSession()
    session._current_t_ms = 0
    _h_start_record(session, {})

    session.macros["brightness_mul"] = 0.5
    session._maybe_record_macros(t_ms=0)
    session._maybe_record_macros(t_ms=100)

    result = _h_stop_record(session, {})

    assert result["ok"] is True
    assert result["lanes_created"] == 1
    assert len(session.timeline.automation) == 1


def test_lane_target_correct():
    """La lane creada tiene target 'master:brightness_mul'."""
    session = _FakeSession()
    session._current_t_ms = 0
    _h_start_record(session, {})

    session.macros["brightness_mul"] = 1.5
    session._maybe_record_macros(t_ms=0)

    _h_stop_record(session, {})

    lane = session.timeline.automation[0]
    assert lane["target"] == "master:brightness_mul"


def test_values_normalized():
    """brightness_mul=1.0 (default) → no se graba ningún punto."""
    session = _FakeSession()
    session._recording = True
    # macros en default: brightness_mul=1.0

    session._maybe_record_macros(t_ms=0)
    session._maybe_record_macros(t_ms=100)
    session._maybe_record_macros(t_ms=200)

    assert session._recorded_lanes == {}, "El default no debe generar puntos"


def test_undo_covers_lanes():
    """stop_record → undo → automation vacía (I1)."""
    from uuid import uuid4

    from src.core.automation import AutomationLane, AutomationPoint

    session = _FakeSession()
    session._current_t_ms = 0

    # Enriquecer snapshot con soporte real de undo
    snapshots = []

    def _snapshot():
        snapshots.append(list(session.timeline.automation))

    def _undo():
        if snapshots:
            session.timeline.automation = snapshots.pop()

    session.snapshot = _snapshot

    _h_start_record(session, {})
    session.macros["speed_mul"] = 2.0
    session._maybe_record_macros(t_ms=0)
    session._maybe_record_macros(t_ms=100)

    _h_stop_record(session, {})
    assert len(session.timeline.automation) == 1

    # Undo: restituye el estado previo al stop_record (sin lanes)
    _undo()
    assert session.timeline.automation == [], "Undo debe eliminar las lanes grabadas"


def test_stop_record_idempotent():
    """stop_record sin start previo → {ok, lanes_created: 0, recording: False}."""
    session = _FakeSession()

    result = _h_stop_record(session, {})

    assert result["ok"] is True
    assert result["recording"] is False
    assert result["lanes_created"] == 0
    assert result["lane_uids"] == []
