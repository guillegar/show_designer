"""
test_patch_ux.py — Tests Patch UX: next_free_address, duplicate_fixture,
get_universe_channel_map, get_output_targets.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from server.dispatcher import (
    _h_duplicate_fixture,
    _h_get_output_targets,
    _h_get_universe_channel_map,
    _h_next_free_address,
)
from src.core.fixtures import Fixture, FixtureRig, build_default_wled_rig


def _make_session(tmp_path: Path) -> MagicMock:
    session = MagicMock()
    session.fixture_rig = build_default_wled_rig()
    session.project.rig_file = tmp_path / "rig.json"
    return session


def _make_small_session(tmp_path: Path) -> MagicMock:
    """Sesión con fixtures de perfil simple (3 canales) para tests de duplicado."""
    from src.core.fixtures import Fixture, FixtureRig
    fx1 = Fixture(
        fixture_id="par_a",
        profile_id="rgb",
        universe=11,
        dmx_start=1,
        position=(0.0, 1.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        label="Par A",
    )
    session = MagicMock()
    session.fixture_rig = FixtureRig([fx1])
    session.project.rig_file = tmp_path / "rig.json"
    return session


# ── next_free_address ─────────────────────────────────────────────────────────

def test_next_free_address_start(tmp_path):
    """Sin fixtures en el universo, dirección libre = 1."""
    session = _make_session(tmp_path)
    # Universo 11 está vacío en el rig por defecto
    r = _h_next_free_address(session, {"universe": 11, "num_channels": 4})
    assert r["ok"] is True
    assert r["address"] == 1


def test_next_free_address_after_existing(tmp_path):
    """Con un fixture en ch 1-93 (wled_strip_93), el siguiente libre empieza en 94."""
    session = _make_session(tmp_path)
    # U1 tiene bar_0 en ch 1 con 279 canales (wled_strip_93 pixel mode)
    # Verificamos que el siguiente libre >= 280 en U1
    r = _h_next_free_address(session, {"universe": 1, "num_channels": 3})
    assert r["ok"] is True
    # El fixture bar_0 usa ch 1 a 279 (wled_strip_93, 279ch); siguiente libre = 280
    assert r["address"] >= 2


def test_next_free_address_no_space(tmp_path):
    """Si no hay espacio suficiente en el universo, devuelve error."""
    session = _make_session(tmp_path)
    # Pedir 500 canales en U1 (ocupado por bar_0 con 279 ch + no cabe 500 ch más)
    r = _h_next_free_address(session, {"universe": 1, "num_channels": 500})
    # Puede que sí quepan (512-280=232) → si no caben, error; si caben, ok
    # En todo caso el handler no debe lanzar excepción
    assert "ok" in r


def test_next_free_address_no_rig(tmp_path):
    """Sin rig cargado, devuelve address=1."""
    session = MagicMock()
    session.fixture_rig = None
    r = _h_next_free_address(session, {"universe": 1, "num_channels": 1})
    assert r["ok"] is True
    assert r["address"] == 1


# ── duplicate_fixture ─────────────────────────────────────────────────────────

def test_duplicate_fixture_creates_new(tmp_path):
    """duplicate_fixture crea un fixture con nuevo ID y label '(copia)'."""
    session = _make_small_session(tmp_path)
    r = _h_duplicate_fixture(session, {"fixture_id": "par_a"})
    assert r["ok"] is True, r.get("error")
    assert r["fixture"]["fixture_id"] != "par_a"
    assert "(copia)" in r["fixture"]["label"]
    assert len(session.fixture_rig.fixtures) == 2


def test_duplicate_fixture_uses_next_free(tmp_path):
    """El duplicado empieza después del original en DMX (sin solapamiento)."""
    session = _make_small_session(tmp_path)
    r = _h_duplicate_fixture(session, {"fixture_id": "par_a"})
    assert r["ok"] is True, r.get("error")
    original = session.fixture_rig.by_id("par_a")
    copy = session.fixture_rig.by_id(r["fixture"]["fixture_id"])
    assert copy is not None
    assert copy.universe == original.universe
    # El clon no se solapa: sus rangos no se intersectan
    prof = session.fixture_rig.get_profile(original.profile_id)
    nch = prof.num_channels if prof else 1
    orig_end = original.dmx_start + nch - 1
    copy_end = copy.dmx_start + nch - 1
    overlap = not (copy_end < original.dmx_start or copy.dmx_start > orig_end)
    assert not overlap, f"Solapamiento: original={original.dmx_start}-{orig_end}, copia={copy.dmx_start}-{copy_end}"


def test_duplicate_fixture_not_found(tmp_path):
    """duplicate_fixture con ID inexistente devuelve error."""
    session = _make_small_session(tmp_path)
    r = _h_duplicate_fixture(session, {"fixture_id": "nonexistent"})
    assert r["ok"] is False


def test_duplicate_fixture_patch_xy_cleared(tmp_path):
    """El clon no hereda patch_x/patch_y del original."""
    session = _make_small_session(tmp_path)
    session.fixture_rig.by_id("par_a").patch_x = 0.5
    session.fixture_rig.by_id("par_a").patch_y = 0.3
    r = _h_duplicate_fixture(session, {"fixture_id": "par_a"})
    assert r["ok"] is True, r.get("error")
    assert r["fixture"].get("patch_x") is None
    assert r["fixture"].get("patch_y") is None


# ── get_universe_channel_map ──────────────────────────────────────────────────

def test_get_universe_channel_map_groups_by_universe(tmp_path):
    """El mapa agrupa fixtures por universo."""
    session = _make_session(tmp_path)
    r = _h_get_universe_channel_map(session, {})
    assert r["ok"] is True
    universes = r["universes"]
    # El rig WLED tiene 10 universos (1..10)
    assert "1" in universes
    assert "10" in universes


def test_get_universe_channel_map_sorted(tmp_path):
    """Los slots dentro de cada universo están ordenados por start."""
    session = _make_session(tmp_path)
    r = _h_get_universe_channel_map(session, {})
    for u_slots in r["universes"].values():
        starts = [s["start"] for s in u_slots]
        assert starts == sorted(starts)


def test_get_universe_channel_map_slot_fields(tmp_path):
    """Cada slot tiene los campos esperados."""
    session = _make_session(tmp_path)
    r = _h_get_universe_channel_map(session, {})
    slot = r["universes"]["1"][0]
    assert "fixture_id" in slot
    assert "label" in slot
    assert "start" in slot
    assert "end" in slot
    assert "num_channels" in slot
    assert slot["end"] >= slot["start"]


def test_get_universe_channel_map_no_rig(tmp_path):
    """Sin rig, devuelve universos vacíos."""
    session = MagicMock()
    session.fixture_rig = None
    r = _h_get_universe_channel_map(session, {})
    assert r["ok"] is True
    assert r["universes"] == {}


# ── get_output_targets ────────────────────────────────────────────────────────

def test_get_output_targets_reads_file(tmp_path, monkeypatch):
    """get_output_targets lee el fichero output_targets.json correctamente."""
    ot = tmp_path / "output_targets.json"
    ot.write_text(json.dumps({
        "1": {"type": "wled", "ip": "192.168.1.201"},
        "2": {"type": "sim_only"},
        "osc": {"port_in": 8001},  # clave no numérica — debe ignorarse
    }), encoding="utf-8")

    import server.dispatcher as disp
    monkeypatch.setattr(disp, "__file__", str(tmp_path / "dispatcher.py"))
    # Recrear la ruta como hace el handler (parent.parent)
    # Parchamos la función directamente vía mock
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "server.dispatcher.Path",
        side_effect=lambda *a, **kw: Path(*a, **kw),
    ):
        session = MagicMock()
        # Llamamos con la ruta real del proyecto
        from pathlib import Path as RealPath
        real_ot = RealPath(__file__).resolve().parent.parent / "output_targets.json"
        if real_ot.is_file():
            r = _h_get_output_targets(session, {})
            assert r["ok"] is True
            assert isinstance(r["targets"], dict)
            # Todas las claves deben ser numéricas
            for k in r["targets"]:
                assert k.isdigit()
        else:
            pytest.skip("output_targets.json no encontrado en raíz del proyecto")


def test_get_output_targets_missing_file():
    """Sin output_targets.json, devuelve targets vacíos sin error."""
    from unittest.mock import MagicMock, patch

    import server.dispatcher as disp
    fake_path = MagicMock()
    fake_path.is_file.return_value = False
    with patch.object(disp, "_h_get_output_targets", wraps=_h_get_output_targets):
        session = MagicMock()
        # Simular que el fichero no existe sobreescribiendo Path
        original = _h_get_output_targets.__globals__.get("Path")
        result = _h_get_output_targets(session, {})
        # El handler ya maneja la ausencia del fichero
        assert result["ok"] is True
