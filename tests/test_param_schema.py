"""
tests/test_param_schema.py — Tests de la fase F2: Plugin UI auto-generada.

Cubre:
  - PARAM_SCHEMA definido en la clase base Effect (ClassVar, valor por defecto {})
  - PARAM_SCHEMA completo en SolidColorEffect (r, g, b como int)
  - validate_params_against_schema: rechaza rangos y enum inválidos
  - validate_params_against_schema: schema vacío pasa sin error (backwards-compat)
  - Handler get_effect_schema devuelve schema correcto para effect_id conocido
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.effects_engine import Effect, EffectLibrary
from server.validators import validate_params_against_schema, ValidationError


# ── Helpers ────────────────────────────────────────────────────────────────

def _lib():
    """Instancia la librería de efectos (incluye plugins F1)."""
    return EffectLibrary()


# ── Effect base class ──────────────────────────────────────────────────────

def test_effect_base_has_param_schema():
    """La clase base Effect define PARAM_SCHEMA como ClassVar con valor {}."""
    assert hasattr(Effect, "PARAM_SCHEMA")
    assert Effect.PARAM_SCHEMA == {}


# ── SolidColorEffect ───────────────────────────────────────────────────────

def test_solid_color_param_schema_r_is_int():
    """SolidColorEffect.PARAM_SCHEMA['r']['type'] == 'int'."""
    lib = _lib()
    effect = lib.get_effect(1004)  # SolidColorEffect
    assert effect is not None, "SolidColorEffect no cargado (ID 1004)"
    schema = effect.PARAM_SCHEMA
    assert "r" in schema, "Falta 'r' en PARAM_SCHEMA de SolidColorEffect"
    assert schema["r"]["type"] == "int"
    assert schema["r"]["min"] == 0
    assert schema["r"]["max"] == 255


def test_solid_color_param_schema_g_b_int():
    """g y b también son int con rango 0-255."""
    lib = _lib()
    effect = lib.get_effect(1004)
    schema = effect.PARAM_SCHEMA
    for ch in ("g", "b"):
        assert schema[ch]["type"] == "int"
        assert schema[ch]["min"] == 0
        assert schema[ch]["max"] == 255


# ── validate_params_against_schema ────────────────────────────────────────

def test_validate_rejects_r_out_of_range():
    """validate_params_against_schema rechaza r=300 (fuera de max=255)."""
    lib = _lib()
    effect = lib.get_effect(1004)  # SolidColorEffect
    schema = effect.PARAM_SCHEMA
    with pytest.raises(ValidationError, match="fuera de rango"):
        validate_params_against_schema({"r": 300, "g": 0, "b": 0}, schema)


def test_validate_rejects_negative_channel():
    """validate_params_against_schema rechaza b=-1 (fuera de min=0)."""
    lib = _lib()
    effect = lib.get_effect(1004)
    schema = effect.PARAM_SCHEMA
    with pytest.raises(ValidationError, match="fuera de rango"):
        validate_params_against_schema({"r": 0, "g": 0, "b": -1}, schema)


def test_validate_rejects_invalid_enum():
    """validate_params_against_schema rechaza mode='diagonal' si options=['sin','bounce']."""
    schema_scanner = _lib().get_effect(1018).PARAM_SCHEMA  # ScannerEffect
    with pytest.raises(ValidationError, match="no es válido"):
        validate_params_against_schema({"mode": "diagonal"}, schema_scanner)


def test_validate_accepts_valid_enum():
    """Valores de enum válidos pasan sin error."""
    schema_scanner = _lib().get_effect(1018).PARAM_SCHEMA
    # No debe lanzar
    validate_params_against_schema({"mode": "sin"}, schema_scanner)
    validate_params_against_schema({"mode": "bounce"}, schema_scanner)


def test_validate_empty_schema_passes():
    """Schema vacío → pasa sin error (backwards-compat para efectos legacy)."""
    validate_params_against_schema({"cualquier_cosa": 42}, {})
    validate_params_against_schema({}, {})


def test_validate_missing_key_is_ok():
    """Params que no están en el schema no se validan (no error)."""
    lib = _lib()
    schema = lib.get_effect(1004).PARAM_SCHEMA  # tiene r, g, b
    # Solo pasamos 'r'; g y b ausentes → ok
    validate_params_against_schema({"r": 100}, schema)


def test_validate_float_out_of_range():
    """validate_params_against_schema rechaza speed fuera de rango en ScannerEffect."""
    schema = _lib().get_effect(1018).PARAM_SCHEMA  # speed min=0.1, max=10.0
    with pytest.raises(ValidationError, match="fuera de rango"):
        validate_params_against_schema({"speed": 999.0}, schema)


# ── get_effect_schema handler ──────────────────────────────────────────────

def test_get_effect_schema_handler_returns_schema():
    """get_effect_schema devuelve schema correcto para effect_id conocido."""
    from server.session import ShowSession
    from server.dispatcher import Dispatcher

    disp = Dispatcher(ShowSession())
    res = disp.call("get_effect_schema", {"effect_id": 1004})
    assert res["ok"] is True
    schema = res["schema"]
    assert "r" in schema
    assert schema["r"]["type"] == "int"


def test_get_effect_schema_unknown_id():
    """get_effect_schema devuelve error para effect_id desconocido."""
    from server.session import ShowSession
    from server.dispatcher import Dispatcher

    disp = Dispatcher(ShowSession())
    res = disp.call("get_effect_schema", {"effect_id": 9999})
    assert res["ok"] is False


# ── Todos los efectos F1 tienen PARAM_SCHEMA no vacío ─────────────────────

@pytest.mark.parametrize("effect_id", range(1010, 1020))
def test_f1_effects_have_param_schema(effect_id):
    """Los 10 efectos F1 (IDs 1010-1019) tienen PARAM_SCHEMA definido."""
    lib = _lib()
    effect = lib.get_effect(effect_id)
    assert effect is not None, f"Efecto {effect_id} no cargado"
    schema = getattr(effect, "PARAM_SCHEMA", None)
    assert schema is not None, f"Efecto {effect_id} no tiene PARAM_SCHEMA"
    assert len(schema) > 0, f"Efecto {effect_id} tiene PARAM_SCHEMA vacío"
