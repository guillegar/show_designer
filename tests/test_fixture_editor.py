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
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.dispatcher import (
    _h_get_fixture_detail,
    _h_list_fixture_types,
    _h_update_fixture,
)
from src.core.fixtures import Fixture, FixtureRig, build_default_wled_rig

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
    # (ADR-005: el handler vive en server.handlers.patch — parchear SU módulo)
    with patch("server.handlers.patch._get_artnet_ip_for_universe", return_value="192.168.1.201") as mock_ip:
        res = _h_get_fixture_detail(session, {"fixture_id": "bar_0"})
    assert res["ok"] is True
    assert res["fixture"]["artnet_ip"] == "192.168.1.201"
    mock_ip.assert_called_once_with(1)


def test_update_fixture_target_ip(tmp_path):
    """update_fixture cambia target_ip; vacío → None."""
    session = _make_session(tmp_path)
    # Asignar IP
    res = _h_update_fixture(session, {"fixture_id": "bar_0", "target_ip": "192.168.10.100"})
    assert res["ok"] is True
    assert session.fixture_rig.by_id("bar_0").target_ip == "192.168.10.100"
    # Vaciar IP
    res = _h_update_fixture(session, {"fixture_id": "bar_0", "target_ip": ""})
    assert res["ok"] is True
    assert session.fixture_rig.by_id("bar_0").target_ip is None


def test_update_fixture_rotation_y(tmp_path):
    """update_fixture cambia rotation[1] y preserva rx/rz."""
    session = _make_session(tmp_path)
    fx = session.fixture_rig.by_id("bar_0")
    assert fx.rotation == (0.0, 0.0, 0.0)
    # Cambiar rotation_y a 45°
    res = _h_update_fixture(session, {"fixture_id": "bar_0", "rotation_y": 45.0})
    assert res["ok"] is True
    assert session.fixture_rig.by_id("bar_0").rotation == (0.0, 45.0, 0.0)


# ── Phase B — Bulk Editing ────────────────────────────────────────────────────

def test_bulk_repatch(tmp_path):
    """bulk_repatch asigna direcciones consecutivas a múltiples fixtures."""
    from server.handlers.patch import _h_bulk_repatch
    session = _make_session(tmp_path)
    # bar_0..bar_2 están en universos 1..3; vamos a reparcharlos juntos
    # wled_strip_93 tiene 279 canales (93 LEDs × 3 RGB)
    res = _h_bulk_repatch(session, {
        "fixture_ids": ["bar_0", "bar_1", "bar_2"],
        "universe": 2,
        "start_address": 1,
    })
    assert res["ok"] is True
    assert len(res["fixtures"]) == 3
    # bar_0 (279 ch) → U2:1-279, bar_1 → U2:280-558, bar_2 → U2:559-837 (overflow pero ok)
    b0 = session.fixture_rig.by_id("bar_0")
    b1 = session.fixture_rig.by_id("bar_1")
    b2 = session.fixture_rig.by_id("bar_2")
    assert b0.universe == 2 and b0.dmx_start == 1
    assert b1.universe == 2 and b1.dmx_start == 280
    assert b2.universe == 2 and b2.dmx_start == 559


def test_bulk_repatch_conflict_dry_run(tmp_path):
    """bulk_repatch dry_run=True detecta conflicto sin persistir."""
    from server.handlers.patch import _h_bulk_repatch
    session = _make_session(tmp_path)
    extra = Fixture(
        fixture_id="extra_bar", profile_id="wled_strip_93",
        universe=2, dmx_start=100,
    )
    session.fixture_rig.fixtures.append(extra)

    res = _h_bulk_repatch(session, {
        "fixture_ids": ["bar_0"],
        "universe": 2,
        "start_address": 1,
        "dry_run": True,
    })
    assert res["ok"] is True
    # bar_0 (279 ch) en 2:1-279 conflictúa con extra_bar en 2:100
    assert len(res["conflicts"]) > 0
    # NO se persistió
    assert session.fixture_rig.by_id("bar_0").universe == 1


def test_bulk_repatch_conflict_not_persisted(tmp_path):
    """bulk_repatch sin dry_run bloquea si hay conflicto."""
    from server.handlers.patch import _h_bulk_repatch
    session = _make_session(tmp_path)
    extra = Fixture(
        fixture_id="extra_bar", profile_id="wled_strip_93",
        universe=2, dmx_start=100,
    )
    session.fixture_rig.fixtures.append(extra)

    res = _h_bulk_repatch(session, {
        "fixture_ids": ["bar_0"],
        "universe": 2,
        "start_address": 1,
    })
    assert res["ok"] is False
    assert "conflicto" in res.get("error", "").lower()
    assert len(res.get("conflicts", [])) > 0
    assert session.fixture_rig.by_id("bar_0").universe == 1


def test_bulk_move(tmp_path):
    """bulk_move actualiza patch_x/patch_y para múltiples fixtures."""
    from server.handlers.patch import _h_bulk_move
    session = _make_session(tmp_path)
    res = _h_bulk_move(session, {
        "moves": [
            {"fixture_id": "bar_0", "x": 0.1, "y": 0.2},
            {"fixture_id": "bar_1", "x": 0.3, "y": 0.4},
        ]
    })
    assert res["ok"] is True
    assert len(res["fixtures"]) == 2
    assert session.fixture_rig.by_id("bar_0").patch_x == pytest.approx(0.1)
    assert session.fixture_rig.by_id("bar_0").patch_y == pytest.approx(0.2)
    assert session.fixture_rig.by_id("bar_1").patch_x == pytest.approx(0.3)
    assert session.fixture_rig.by_id("bar_1").patch_y == pytest.approx(0.4)


def test_bulk_rename(tmp_path):
    """bulk_rename aplica patrón con {n}."""
    from server.handlers.patch import _h_bulk_rename
    session = _make_session(tmp_path)
    res = _h_bulk_rename(session, {
        "fixture_ids": ["bar_0", "bar_1", "bar_2"],
        "pattern": "Barra {n}",
        "start_num": 1,
    })
    assert res["ok"] is True
    assert len(res["fixtures"]) == 3
    assert session.fixture_rig.by_id("bar_0").label == "Barra 1"
    assert session.fixture_rig.by_id("bar_1").label == "Barra 2"
    assert session.fixture_rig.by_id("bar_2").label == "Barra 3"


def test_bulk_copy_properties(tmp_path):
    """bulk_copy_properties copia height_m, notes, kind_override."""
    from server.handlers.patch import _h_bulk_copy_properties
    session = _make_session(tmp_path)
    # Configurar source
    src = session.fixture_rig.by_id("bar_0")
    src.height_m = 2.5
    src.notes = "Fuente"
    src.kind_override = "custom"

    res = _h_bulk_copy_properties(session, {
        "from_fixture_id": "bar_0",
        "to_fixture_ids": ["bar_1", "bar_2"],
        "properties": ["height_m", "notes", "kind_override"],
    })
    assert res["ok"] is True
    assert len(res["fixtures"]) == 2
    for fid in ["bar_1", "bar_2"]:
        fx = session.fixture_rig.by_id(fid)
        assert fx.height_m == pytest.approx(2.5)
        assert fx.notes == "Fuente"
        assert fx.kind_override == "custom"
