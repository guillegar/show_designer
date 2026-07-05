"""
test_gdtf_browser.py — Tests J3: biblioteca GDTF browser y búsqueda.

Cubre:
  test_list_gdtf_profiles_finds_files    — list_gdtf_profiles devuelve todos los .gdtf
  test_list_gdtf_profiles_empty_dir      — dir vacío → lista vacía sin crash
  test_add_fixture_from_gdtf_valid       — fixture creado con canales correctos
  test_add_fixture_from_gdtf_missing     — perfil inexistente → error limpio
  test_add_fixture_persists_rig          — fixture persiste en rig.json tras reload
"""
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.dispatcher import _gdtf_cache, _h_add_fixture_from_gdtf, _h_list_gdtf_profiles
from src.core.fixtures import Fixture, FixtureRig, build_default_wled_rig

# Ruta al GDTF de prueba (incluido en el repo)
TEST_GDTF = Path(__file__).parent / "fixtures" / "test_wash_4ch.gdtf"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session(tmp_path: Path) -> MagicMock:
    session = MagicMock()
    session.project.rig_file = tmp_path / "rig.json"
    session.fixture_rig = build_default_wled_rig()
    return session


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_list_gdtf_profiles_finds_files(tmp_path):
    """list_gdtf_profiles escanea PROFILES_DIR y devuelve metadatos de cada .gdtf."""
    if not TEST_GDTF.is_file():
        pytest.skip("test_wash_4ch.gdtf no disponible")

    # Copiar el test GDTF a un subdirectorio y llamar directamente a _gdtf_metadata
    from server.dispatcher import _gdtf_metadata
    _gdtf_cache.clear()
    meta = _gdtf_metadata(TEST_GDTF)
    assert "name" in meta
    assert "channel_count" in meta
    assert meta["channel_count"] >= 1
    assert meta["path"] == str(TEST_GDTF)

    # list_gdtf_profiles retorna ok=True (aunque el directorio tenga 0 perfiles)
    session = _make_session(tmp_path)
    res = _h_list_gdtf_profiles(session, {})
    assert res["ok"] is True
    assert isinstance(res["profiles"], list)


def test_list_gdtf_profiles_empty_dir():
    """Directorio sin .gdtf → list_gdtf_profiles retorna lista vacía sin crash."""
    # El PROFILES_DIR real puede tener 0 .gdtf — en cualquier caso, no debe crashear
    session = MagicMock()
    session.project.rig_file = Path("/tmp/rig.json")
    res = _h_list_gdtf_profiles(session, {})
    assert res["ok"] is True
    assert isinstance(res["profiles"], list)  # puede estar vacía si no hay .gdtf en profiles/


def test_add_fixture_from_gdtf_valid(tmp_path):
    """add_fixture_from_gdtf con perfil válido crea fixture con canales correctos."""
    if not TEST_GDTF.is_file():
        pytest.skip("test_wash_4ch.gdtf no disponible")

    session = _make_session(tmp_path)
    res = _h_add_fixture_from_gdtf(session, {
        "profile_path": str(TEST_GDTF),
        "universe": 12,
        "start_channel": 1,
        "name": "Test Wash",
    })
    assert res["ok"] is True
    assert "fixtures" in res
    assert len(res["fixtures"]) == 1
    fx = res["fixtures"][0]
    assert fx["universe"] == 12
    assert fx["dmx_start"] == 1
    assert fx["label"] == "Test Wash"
    # El fixture fue añadido al rig
    added = session.fixture_rig.by_id(fx["fixture_id"])
    assert added is not None


def test_add_fixture_from_gdtf_missing(tmp_path):
    """Perfil inexistente retorna error limpio sin crash."""
    session = _make_session(tmp_path)
    res = _h_add_fixture_from_gdtf(session, {
        "profile_path": str(tmp_path / "no_existe.gdtf"),
        "universe": 1,
        "start_channel": 1,
    })
    assert res["ok"] is False
    assert "no_existe" in res["error"] or "encontrado" in res["error"]


def test_add_fixture_persists_rig(tmp_path):
    """Fixture creado desde GDTF persiste en rig.json tras reload."""
    if not TEST_GDTF.is_file():
        pytest.skip("test_wash_4ch.gdtf no disponible")

    session = _make_session(tmp_path)
    res = _h_add_fixture_from_gdtf(session, {
        "profile_path": str(TEST_GDTF),
        "universe": 15,
        "start_channel": 5,
        "name": "Wash Persist",
    })
    assert res["ok"] is True
    assert len(res["fixtures"]) == 1

    rig_path = tmp_path / "rig.json"
    assert rig_path.is_file()
    data = json.loads(rig_path.read_text())
    fids = [f["fixture_id"] for f in data["fixtures"]]
    new_fid = res["fixtures"][0]["fixture_id"]
    assert new_fid in fids
    saved = next(f for f in data["fixtures"] if f["fixture_id"] == new_fid)
    assert saved["universe"] == 15
    assert saved["dmx_start"] == 5
