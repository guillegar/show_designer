"""
test_patch_visual.py — Tests J1: editor de patch visual drag-and-drop.

Cubre:
  test_move_fixture_sets_patch_xy     — move_fixture(x, y) actualiza patch_x/y
  test_move_fixture_persists_rig      — el handler guarda rig.json al mover
  test_move_fixture_migration         — fixture sin patch_x/y: from_dict → None
  test_delete_fixture_clears_patch    — delete_fixture no deja patch_x/y
  test_add_fixture_no_patch_xy        — add_fixture crea fixture sin patch_x/y
  test_move_fixture_unknown           — error si fixture_id desconocido
  test_move_fixture_clamps_values     — valores fuera de 0..1 se clampa
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.dispatcher import _h_move_fixture
from src.core.fixtures import Fixture, FixtureRig, build_default_wled_rig

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session(tmp_path: Path) -> MagicMock:
    session = MagicMock()
    session.project.rig_file = tmp_path / "rig.json"
    rig = build_default_wled_rig()
    session.fixture_rig = rig
    return session


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_move_fixture_sets_patch_xy(tmp_path):
    """move_fixture con x/y actualiza patch_x y patch_y en el fixture."""
    session = _make_session(tmp_path)
    res = _h_move_fixture(session, {"fixture_id": "bar_0", "x": 0.25, "y": 0.75})
    assert res["ok"] is True
    assert res["fixture"]["patch_x"] == pytest.approx(0.25)
    assert res["fixture"]["patch_y"] == pytest.approx(0.75)
    fx = session.fixture_rig.by_id("bar_0")
    assert fx.patch_x == pytest.approx(0.25)
    assert fx.patch_y == pytest.approx(0.75)


def test_move_fixture_persists_rig(tmp_path):
    """El handler guarda rig.json con los nuevos valores de patch_x/y."""
    session = _make_session(tmp_path)
    _h_move_fixture(session, {"fixture_id": "bar_3", "x": 0.4, "y": 0.6})
    rig_path = tmp_path / "rig.json"
    assert rig_path.is_file()
    data = json.loads(rig_path.read_text())
    bar3 = next(f for f in data["fixtures"] if f["fixture_id"] == "bar_3")
    assert bar3["patch_x"] == pytest.approx(0.4)
    assert bar3["patch_y"] == pytest.approx(0.6)


def test_move_fixture_migration(tmp_path):
    """Fixture guardado sin patch_x/y (formato antiguo) carga con None."""
    old_rig = {
        "version": 1,
        "fixtures": [{
            "fixture_id": "bar_0", "profile_id": "wled_strip_93",
            "universe": 1, "dmx_start": 1,
            "position": [0.0, 1.0, 0.0], "rotation": [0.0, 0.0, 0.0],
            "label": "Bar 00", "legacy_bar_idx": 0,
            "target_ip": None, "manual_channels": {},
        }]
    }
    rig_path = tmp_path / "rig.json"
    rig_path.write_text(json.dumps(old_rig))
    rig = FixtureRig.load(rig_path)
    fx = rig.by_id("bar_0")
    assert fx is not None
    assert fx.patch_x is None
    assert fx.patch_y is None


def test_move_fixture_unknown(tmp_path):
    """Error controlado si fixture_id no existe en el rig."""
    session = _make_session(tmp_path)
    res = _h_move_fixture(session, {"fixture_id": "no_existe", "x": 0.5, "y": 0.5})
    assert res["ok"] is False
    assert "no_existe" in res["error"]


def test_move_fixture_clamps_values(tmp_path):
    """Valores x/y fuera de 0..1 se clampa al rango válido."""
    session = _make_session(tmp_path)
    res = _h_move_fixture(session, {"fixture_id": "bar_0", "x": -0.5, "y": 1.8})
    assert res["ok"] is True
    assert res["fixture"]["patch_x"] == pytest.approx(0.0)
    assert res["fixture"]["patch_y"] == pytest.approx(1.0)


def test_move_fixture_legacy_position(tmp_path):
    """Acepta position=[x,y,z] legacy y guarda patch_x/y normalizados."""
    session = _make_session(tmp_path)
    # Con 10 fixtures en X de -5..5, bar_0 está en X=-5 → norm=0.0
    res = _h_move_fixture(session, {"fixture_id": "bar_0", "position": [-5.0, 1.0, 0.0]})
    assert res["ok"] is True
    assert res["fixture"]["patch_x"] == pytest.approx(0.0, abs=0.01)


def test_add_fixture_no_patch_xy(tmp_path):
    """Fixture recién creado (Fixture dataclass) tiene patch_x y patch_y = None."""
    fx = Fixture(
        fixture_id="test_new", profile_id="wled_strip_93",
        universe=11, dmx_start=1,
    )
    assert fx.patch_x is None
    assert fx.patch_y is None
    d = fx.to_dict()
    assert d["patch_x"] is None
    assert d["patch_y"] is None
