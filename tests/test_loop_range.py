"""
test_loop_range.py — Tests Timeline v2 Fase D: loop de región A/B.

Cubre:
  test_set_loop_range          — define la región y la devuelve
  test_set_loop_range_clear    — clear=True (o sin args) la quita
  test_set_loop_range_invalid  — start >= end o negativo → error
  test_set_loop_range_clamped  — end_ms se recorta a la duración de la canción
  test_set_loop_range_too_short — región < 100 ms → error
"""
from unittest.mock import MagicMock

from server.dispatcher import _h_set_loop_range


def _session(duration_s: float = 273.3) -> MagicMock:
    s = MagicMock()
    s.duration = duration_s
    s.loop_range = None
    return s


def test_set_loop_range():
    s = _session()
    r = _h_set_loop_range(s, {"start_ms": 10_000, "end_ms": 20_000})
    assert r["ok"] is True
    assert r["loop_range"] == [10_000, 20_000]
    assert s.loop_range == (10_000, 20_000)


def test_set_loop_range_clear():
    s = _session()
    s.loop_range = (0, 5000)
    r = _h_set_loop_range(s, {"clear": True})
    assert r["ok"] is True and r["loop_range"] is None
    assert s.loop_range is None
    # Sin argumentos también limpia
    s.loop_range = (0, 5000)
    r2 = _h_set_loop_range(s, {})
    assert r2["ok"] is True and s.loop_range is None


def test_set_loop_range_invalid():
    s = _session()
    assert _h_set_loop_range(s, {"start_ms": 5000, "end_ms": 5000})["ok"] is False
    assert _h_set_loop_range(s, {"start_ms": -100, "end_ms": 5000})["ok"] is False
    assert _h_set_loop_range(s, {"start_ms": "x", "end_ms": 5000})["ok"] is False
    assert s.loop_range is None


def test_set_loop_range_clamped():
    s = _session(duration_s=100.0)
    r = _h_set_loop_range(s, {"start_ms": 90_000, "end_ms": 500_000})
    assert r["ok"] is True
    assert r["loop_range"] == [90_000, 100_000]
    # Región entera fuera de la canción → error
    r2 = _h_set_loop_range(s, {"start_ms": 200_000, "end_ms": 300_000})
    assert r2["ok"] is False


def test_set_loop_range_too_short():
    s = _session()
    r = _h_set_loop_range(s, {"start_ms": 1000, "end_ms": 1050})
    assert r["ok"] is False
    assert s.loop_range is None
