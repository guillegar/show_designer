"""
test_fixture_test_advanced.py — Tests J4: test de fixtures avanzado (chase + color).

Cubre:
  test_identify_with_color        — identify_fixture con color rojo → _identify color
  test_identify_with_duration     — identify_fixture duration_ms=500 expira antes
  test_chase_test_starts          — chase_test(1) registra task y cicla identify
  test_chase_stop_cancels         — chase_stop(1) limpia chases y _identify
  test_chase_test_no_fixtures     — chase_test en universo vacío → error limpio
"""
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.fixtures import Fixture, FixtureRig, build_default_wled_rig
from server.dispatcher import (
    _h_identify_fixture, _h_chase_test, _h_chase_stop,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session() -> MagicMock:
    session = MagicMock()
    session.fixture_rig = build_default_wled_rig()
    session._identify = {}
    session._active_chases = {}
    return session


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_identify_with_color():
    """identify_fixture con color=(255,0,0) guarda color rojo en _identify."""
    session = _make_session()
    res = _h_identify_fixture(session, {
        "fixture_id": "bar_0",
        "color": [255, 0, 0],
        "duration_ms": 2000,
    })
    assert res["ok"] is True
    assert res["color"] == [255, 0, 0]
    entry = session._identify.get("bar_0")
    assert entry is not None
    assert entry["color"] == (255, 0, 0)


def test_identify_with_duration():
    """identify_fixture con duration_ms=500 → entrada expira en ~0.5 s."""
    session = _make_session()
    before = time.monotonic()
    res = _h_identify_fixture(session, {
        "fixture_id": "bar_1",
        "duration_ms": 500,
    })
    assert res["ok"] is True
    entry = session._identify.get("bar_1")
    assert entry is not None
    # t_expires debería estar ~500 ms en el futuro
    t_exp = entry["t_expires"]
    assert t_exp > before + 0.4   # al menos 400 ms en el futuro
    assert t_exp < before + 0.7   # menos de 700 ms


def test_identify_backwards_compatible():
    """Llamada sin color → blanco por defecto (backwards compat)."""
    session = _make_session()
    res = _h_identify_fixture(session, {"fixture_id": "bar_2"})
    assert res["ok"] is True
    entry = session._identify.get("bar_2")
    assert entry["color"] == (255, 255, 255)


def test_chase_test_starts():
    """chase_test(1) registra una task y pone identify en los fixtures del universo."""
    session = _make_session()

    with patch("asyncio.ensure_future") as mock_ef:
        mock_ef.return_value = MagicMock()
        res = _h_chase_test(session, {"universe": 1})

    assert res["ok"] is True
    assert res["universe"] == 1
    assert 1 in session._active_chases


def test_chase_stop_cancels():
    """chase_stop(1) cancela la task y limpia _identify de los fixtures."""
    session = _make_session()

    with patch("asyncio.ensure_future") as mock_ef:
        mock_task = MagicMock()
        mock_ef.return_value = mock_task
        _h_chase_test(session, {"universe": 1})

    # Marcar bar_0 como identificando
    session._identify["bar_0"] = {"t_expires": time.monotonic() + 10, "color": (255, 0, 0)}

    res = _h_chase_stop(session, {"universe": 1})
    assert res["ok"] is True
    mock_task.cancel.assert_called_once()
    assert 1 not in session._active_chases
    # bar_0 está en universe 1 → su identify debe haberse limpiado
    assert "bar_0" not in session._identify


def test_chase_test_no_fixtures():
    """chase_test en universo sin fixtures → error limpio."""
    session = _make_session()
    res = _h_chase_test(session, {"universe": 99})
    assert res["ok"] is False
    assert "99" in res["error"]
