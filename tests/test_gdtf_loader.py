"""
Tests del loader GDTF (loaders/gdtf_profile.py).

Cubre:
  - Carga de un .gdtf real (test_wash_4ch.gdtf generado en tests/fixtures/)
  - Mapeo correcto de atributos GDTF a nombres canónicos
  - Offset 1-based GDTF → 0-based interno
  - Detección automática del kind según canales presentes
  - Listado de modos
  - Modo inexistente devuelve error claro

Lanzar:
    pytest tests/test_gdtf_loader.py -v
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.io.loaders.gdtf_profile import (    # noqa: E402
    load_gdtf_profile, list_gdtf_modes, _canonical_name, _guess_kind,
    GDTF_ATTR_TO_CANONICAL,
)
from src.core.fixtures import FixtureProfile, load_profile     # noqa: E402


GDTF_TEST = ROOT / "tests" / "fixtures" / "test_wash_4ch.gdtf"


# ────────────────────────────────────────────────────────────────
# Helpers puros (no necesitan archivo)
# ────────────────────────────────────────────────────────────────

def test_canonical_mapping_known():
    assert _canonical_name("Pan") == "pan"
    assert _canonical_name("Tilt") == "tilt"
    assert _canonical_name("Dimmer") == "dim"
    assert _canonical_name("ColorAdd_R") == "r"
    assert _canonical_name("ColorAdd_W") == "w"
    assert _canonical_name("Gobo1") == "gobo_wheel"
    assert _canonical_name("Prism1Pos") == "prism_rot"
    assert _canonical_name("StrobeFrequency") == "strobe_freq"


def test_canonical_mapping_fallback():
    """Atributos no estándar caen a lowercase del nombre GDTF."""
    assert _canonical_name("FoobarCustom") == "foobarcustom"
    assert _canonical_name("") == ""


def test_guess_kind_beam():
    chs = {"pan": 0, "tilt": 1, "dim": 2, "r": 3, "g": 4, "b": 5,
           "gobo_wheel": 6, "prism": 7}
    assert _guess_kind(chs) == "beam"


def test_guess_kind_wash():
    chs = {"pan": 0, "tilt": 1, "dim": 2, "r": 3, "g": 4, "b": 5, "w": 6}
    assert _guess_kind(chs) == "wash"


def test_guess_kind_dimmer():
    assert _guess_kind({"dim": 0}) == "dimmer"


def test_guess_kind_strobe():
    assert _guess_kind({"strobe_freq": 0}) == "strobe"
    assert _guess_kind({"strobe": 0, "dim": 1}) == "strobe"


def test_guess_kind_moving_head_no_color():
    chs = {"pan": 0, "tilt": 1, "dim": 2}
    assert _guess_kind(chs) == "moving_head"


# ────────────────────────────────────────────────────────────────
# Carga del .gdtf real
# ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_gdtf():
    if not GDTF_TEST.is_file():
        pytest.skip(f"Archivo de test no existe: {GDTF_TEST}")
    return GDTF_TEST


def test_load_gdtf_basic(test_gdtf):
    profile = load_gdtf_profile(test_gdtf)
    assert isinstance(profile, FixtureProfile)
    assert profile.profile_id == "test_wash_4ch"
    assert profile.num_channels == 4
    assert profile.led_count == 0


def test_load_gdtf_channel_map(test_gdtf):
    profile = load_gdtf_profile(test_gdtf)
    cm = profile.channel_map
    # Atributos canónicos esperados
    assert cm["pan"] == 0      # GDTF offset 1 → interno 0
    assert cm["tilt"] == 1
    assert cm["dim"] == 2
    assert cm["r"] == 3


def test_load_gdtf_metadata(test_gdtf):
    profile = load_gdtf_profile(test_gdtf)
    md = profile.metadata
    assert md["_source"] == "gdtf"
    assert md["_gdtf_fixture_name"] == "TestWash4"
    assert md["_gdtf_manufacturer"] == "TestCo"
    assert md.get("max_pan_deg") == 540
    assert md.get("max_tilt_deg") == 270


def test_load_gdtf_kind_detected(test_gdtf):
    profile = load_gdtf_profile(test_gdtf)
    # Tiene pan+tilt pero solo R (no RGB completo) → kind 'moving_head'
    assert profile.kind in ("moving_head", "wash", "beam")


def test_load_gdtf_custom_profile_id(test_gdtf):
    profile = load_gdtf_profile(test_gdtf, profile_id="custom_id_xyz")
    assert profile.profile_id == "custom_id_xyz"


def test_list_gdtf_modes(test_gdtf):
    modes = list_gdtf_modes(test_gdtf)
    assert modes == ["Mode 1"]


def test_load_gdtf_invalid_mode_raises(test_gdtf):
    with pytest.raises(ValueError, match="no existe"):
        load_gdtf_profile(test_gdtf, mode_name="ModeQueNoExiste")


def test_load_gdtf_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_gdtf_profile(tmp_path / "no_existe.gdtf")


# ────────────────────────────────────────────────────────────────
# Integración con fixtures.load_profile (descubre .gdtf en profiles/)
# ────────────────────────────────────────────────────────────────

def test_fixtures_load_profile_falls_back_to_gdtf(tmp_path, monkeypatch):
    """Si profile_id.json no existe pero profile_id.gdtf sí, lo carga."""
    import core.fixtures as fixtures
    # Aislar PROFILES_DIR al tmp
    monkeypatch.setattr(fixtures, "PROFILES_DIR", tmp_path)
    # Copiar el .gdtf de test al directorio temporal
    import shutil
    if not GDTF_TEST.is_file():
        pytest.skip("Test GDTF no disponible")
    target = tmp_path / "my_gdtf_fixture.gdtf"
    shutil.copy(GDTF_TEST, target)
    # Cargar via load_profile (sin extensión)
    profile = fixtures.load_profile("my_gdtf_fixture")
    assert profile is not None
    assert profile.profile_id == "my_gdtf_fixture"
    assert profile.num_channels == 4


def test_fixtures_get_profile_source(tmp_path, monkeypatch):
    """get_profile_source devuelve el formato correcto."""
    import core.fixtures as fixtures
    monkeypatch.setattr(fixtures, "PROFILES_DIR", tmp_path)
    # JSON existe
    (tmp_path / "json_fixture.json").write_text(
        '{"profile_id": "json_fixture", "name": "x", "kind": "dimmer", '
        '"num_channels": 1, "channel_map": {"dim": 0}}', encoding="utf-8"
    )
    assert fixtures.get_profile_source("json_fixture") == "json"
    # No existe
    assert fixtures.get_profile_source("missing") is None
