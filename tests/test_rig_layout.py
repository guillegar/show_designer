"""
test_rig_layout.py — Tests K1: posicionamiento 3D de fixtures en el viewer.

Cubre:
  test_set_fixture_3d_saves          — set_fixture_3d escribe en rig_layout.json atómicamente
  test_get_rig_layout_reads          — get_rig_layout devuelve las coordenadas guardadas
  test_get_rig_layout_empty          — archivo inexistente → lista vacía sin crash
  test_set_fixture_3d_unknown        — fixture_id no encontrado → error limpio
  test_set_fixture_3d_roundtrip      — set → get devuelve las mismas coordenadas
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.dispatcher import _h_get_rig_layout, _h_set_fixture_3d
from src.core.fixtures import build_default_wled_rig

# ── Helpers ───────────────────────────────────────────────────────────────────

class _FakeProject:
    def __init__(self, folder: Path):
        self._folder = folder

    @property
    def rig_layout_file(self) -> Path:
        return self._folder / "rig_layout.json"


def _make_session(tmp_dir: Path) -> MagicMock:
    session = MagicMock()
    session.fixture_rig = build_default_wled_rig()
    session.project = _FakeProject(tmp_dir)
    session.sync_rig_layout = MagicMock()
    return session


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_set_fixture_3d_saves():
    """set_fixture_3d escribe rig_layout.json con las coordenadas correctas."""
    with tempfile.TemporaryDirectory() as tmp:
        session = _make_session(Path(tmp))
        res = _h_set_fixture_3d(session, {
            "fixture_id": "bar_0", "x": -3.5, "y": 4.0, "z": 1.0,
            "rx": 0, "ry": 90, "rz": 0,
        })
        assert res["ok"] is True
        layout_file = Path(tmp) / "rig_layout.json"
        assert layout_file.is_file()
        data = json.loads(layout_file.read_text())
        entries = {e["id"]: e for e in data["fixtures"]}
        assert "bar_0" in entries
        assert entries["bar_0"]["x"] == pytest.approx(-3.5)
        assert entries["bar_0"]["y"] == pytest.approx(4.0)
        assert entries["bar_0"]["ry"] == pytest.approx(90.0)


def test_get_rig_layout_reads():
    """get_rig_layout devuelve las coordenadas guardadas por set_fixture_3d."""
    with tempfile.TemporaryDirectory() as tmp:
        session = _make_session(Path(tmp))
        _h_set_fixture_3d(session, {
            "fixture_id": "bar_1", "x": 2.0, "y": 5.0, "z": -1.0,
        })
        res = _h_get_rig_layout(session, {})
        assert res["ok"] is True
        entries = {e["id"]: e for e in res["fixtures"]}
        assert "bar_1" in entries
        assert entries["bar_1"]["x"] == pytest.approx(2.0)
        assert entries["bar_1"]["y"] == pytest.approx(5.0)


def test_get_rig_layout_empty():
    """Archivo rig_layout.json inexistente → get_rig_layout devuelve lista vacía."""
    with tempfile.TemporaryDirectory() as tmp:
        session = _make_session(Path(tmp))
        res = _h_get_rig_layout(session, {})
        assert res["ok"] is True
        assert res["fixtures"] == []


def test_set_fixture_3d_unknown():
    """fixture_id no encontrado en el rig → error limpio."""
    with tempfile.TemporaryDirectory() as tmp:
        session = _make_session(Path(tmp))
        res = _h_set_fixture_3d(session, {
            "fixture_id": "no_existe", "x": 0, "y": 0, "z": 0,
        })
        assert res["ok"] is False
        assert "no_existe" in res["error"]


def test_set_fixture_3d_roundtrip():
    """set_fixture_3d → get_rig_layout → mismas coordenadas."""
    with tempfile.TemporaryDirectory() as tmp:
        session = _make_session(Path(tmp))
        coords = {"x": 1.5, "y": 3.8, "z": -0.5, "rx": 10.0, "ry": 0.0, "rz": 5.0}
        _h_set_fixture_3d(session, {"fixture_id": "bar_2", **coords})
        res = _h_get_rig_layout(session, {})
        entries = {e["id"]: e for e in res["fixtures"]}
        e = entries["bar_2"]
        for k, v in coords.items():
            assert e[k] == pytest.approx(v), f"{k}: {e[k]} != {v}"
