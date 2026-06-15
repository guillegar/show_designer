"""
test_fixture_editor.py — Tests ROADMAP v4: editor completo de fixture.

Cubre los 8 casos especificados:
  test_update_fixture_name                  — cambia label y persiste
  test_update_fixture_address_ok            — cambia start_address sin conflicto
  test_update_fixture_address_conflict_dry_run — dry_run=True detecta conflicto sin persistir
  test_update_fixture_conflict_not_persisted   — dry_run=False con conflicto devuelve error
  test_update_fixture_notes_persists        — guarda campo notes
  test_update_fixture_channel_map_custom_mode — guarda channel_map como lista
  test_get_fixture_detail_includes_height   — devuelve height_m del fixture
  test_get_fixture_detail_artnet_ip_from_universe — artnet_ip derivada de output_targets.json
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.fixtures import Fixture, FixtureRig, build_default_wled_rig
from server.dispatcher import (
    _h_update_fixture,
    _h_get_fixture_detail,
    _h_list_fixture_types,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session(tmp_path: Path) -> MagicMock:
    """Sesión mock con rig WLED por defecto y rutas en tmp_path."""
    session = MagicMock()
    session.fixture_rig = build_default_wled_rig()
    session.project.rig_file = tmp_path / "rig.json"
    session.project.rig_layout_file = tmp_path / "rig_layout.json"
    return session


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_update_fixture_name(tmp_path):
    """update_fixture cambia el label y lo persiste en memoria."""
    session = _make_session(tmp_path)
    res = _h_update_fixture(session, {"fixture_id": "bar_0", "name": "Barra Principal"})
    assert res["ok"] is True
    assert res["fixture"]["label"] == "Barra Principal"
    assert session.fixture_rig.by_id("bar_0").label == "Barra Principal"


def test_update_fixture_address_ok(tmp_path):
    """update_fixture cambia start_address cuando no hay conflicto."""
    session = _make_session(tmp_path)
    # bar_0 está en universe=1; bar_1..bar_9 están en universos 2..10
    # → dirección 1 del mismo universo no conflicta con ningún otro
    res = _h_update_fixture(session, {"fixture_id": "bar_0", "start_address": 1})
    assert res["ok"] is True
    assert res["fixture"]["dmx_start"] == 1
    assert res["conflicts"] == []


def test_update_fixture_address_conflict_dry_run(tmp_path):
    """dry_run=True detecta conflicto y devuelve ok=True SIN persistir."""
    session = _make_session(tmp_path)
    # Añadir fixture extra en universe=1, dmx_start=100
    extra = Fixture(
        fixture_id="extra_bar", profile_id="wled_strip_93",
        universe=1, dmx_start=100,
    )
    session.fixture_rig.fixtures.append(extra)

    # Mover bar_0 a dmx_start=100 (mismo universo=1, misma dirección) → conflicto
    res = _h_update_fixture(session, {
        "fixture_id": "bar_0",
        "start_address": 100,
        "dry_run": True,
    })
    assert res["ok"] is True                         # dry_run siempre ok
    assert len(res["conflicts"]) > 0
    assert res["conflicts"][0]["fixture_id"] == "extra_bar"
    # NO persiste: bar_0.dmx_start sigue siendo 1
    assert session.fixture_rig.by_id("bar_0").dmx_start == 1


def test_update_fixture_conflict_not_persisted(tmp_path):
    """dry_run=False con conflicto devuelve ok=False y NO persiste."""
    session = _make_session(tmp_path)
    extra = Fixture(
        fixture_id="extra_bar", profile_id="wled_strip_93",
        universe=1, dmx_start=100,
    )
    session.fixture_rig.fixtures.append(extra)

    res = _h_update_fixture(session, {
        "fixture_id": "bar_0",
        "start_address": 100,
    })
    assert res["ok"] is False
    assert "conflicto" in res.get("error", "").lower()
    assert len(res.get("conflicts", [])) > 0
    # NO se persistió: dmx_start sigue en 1
    assert session.fixture_rig.by_id("bar_0").dmx_start == 1


def test_update_fixture_notes_persists(tmp_path):
    """update_fixture guarda el campo notes en el fixture."""
    session = _make_session(tmp_path)
    res = _h_update_fixture(session, {
        "fixture_id": "bar_0",
        "notes": "Barra izquierda, cuidado con el cable",
    })
    assert res["ok"] is True
    assert session.fixture_rig.by_id("bar_0").notes == "Barra izquierda, cuidado con el cable"


def test_update_fixture_channel_map_custom_mode(tmp_path):
    """update_fixture guarda channel_map como lista de {ch, role}."""
    session = _make_session(tmp_path)
    cm = [{"ch": 1, "role": "red"}, {"ch": 2, "role": "green"}, {"ch": 3, "role": "blue"}]
    res = _h_update_fixture(session, {"fixture_id": "bar_0", "channel_map": cm})
    assert res["ok"] is True
    assert session.fixture_rig.by_id("bar_0").channel_map == cm


def test_get_fixture_detail_includes_height(tmp_path):
    """get_fixture_detail devuelve height_m del campo del fixture."""
    session = _make_session(tmp_path)
    session.fixture_rig.by_id("bar_0").height_m = 3.5
    res = _h_get_fixture_detail(session, {"fixture_id": "bar_0"})
    assert res["ok"] is True
    assert res["fixture"]["height_m"] == pytest.approx(3.5)
    assert "num_channels" in res["fixture"]


def test_get_fixture_detail_artnet_ip_from_universe(tmp_path):
    """get_fixture_detail deriva artnet_ip vía _get_artnet_ip_for_universe."""
    session = _make_session(tmp_path)
    # bar_0 → universe=1; mockear la función de derivación de IP
    with patch("server.dispatcher._get_artnet_ip_for_universe", return_value="192.168.1.201") as mock_ip:
        res = _h_get_fixture_detail(session, {"fixture_id": "bar_0"})
    assert res["ok"] is True
    assert res["fixture"]["artnet_ip"] == "192.168.1.201"
    mock_ip.assert_called_once_with(1)
