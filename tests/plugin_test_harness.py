"""
plugin_test_harness.py — Harness reutilizable para plugins de efectos (H1).

Uso:
    from tests.plugin_test_harness import assert_valid_plugin_effect
    assert_valid_plugin_effect(MyEffect())

También puede usarse como script:
    python tests/plugin_test_harness.py plugins/effects/mi_efecto.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from typing import Optional

import numpy as np

from src.core.effects_engine import (
    LEDS_PER_BAR,
    NUM_BARS,
    Effect,
    EffectScope,
)

_EMPTY_CTX = {
    "rms": 0.0, "energy": 0.0, "bpm": 120.0,
    "norm": {"rms": 0.0, "energy": 0.0},
}
_BARS_STATE = np.zeros((NUM_BARS, LEDS_PER_BAR, 3), dtype=np.uint8)


def assert_valid_plugin_effect(
    effect: Effect,
    params: dict | None = None,
    *,
    check_schema: bool = True,
) -> None:
    """Comprueba que el efecto cumple el contrato del SDK.

    Valida:
    - Devuelve ndarray uint8 en la shape correcta (según scope).
    - Valores en [0, 255].
    - No muta bars_state.
    - PARAM_SCHEMA tiene entradas coherentes (si check_schema=True).
    - Renderiza sin excepción en t=0, 500, 1000 ms.

    Lanza AssertionError con mensaje descriptivo si algo falla.
    """
    if params is None:
        params = _default_params(effect)

    # Verificar shape esperada
    expected = effect.expected_output_shape
    assert expected[1] == LEDS_PER_BAR, (
        f"{type(effect).__name__}: expected_output_shape[1] debe ser "
        f"LEDS_PER_BAR={LEDS_PER_BAR}, got {expected[1]}"
    )
    assert expected[2] == 3, (
        f"{type(effect).__name__}: expected_output_shape[2] debe ser 3 (RGB), got {expected[2]}"
    )

    # Renderizar en 3 instantes
    for t_ms in (0.0, 500.0, 1000.0):
        bars_copy = _BARS_STATE.copy()
        result = effect.render(t_ms, bars_copy, _EMPTY_CTX, **params)

        assert isinstance(result, np.ndarray), (
            f"{type(effect).__name__}.render(t={t_ms}) debe devolver np.ndarray, "
            f"got {type(result).__name__}"
        )
        assert result.dtype == np.uint8, (
            f"{type(effect).__name__}.render(t={t_ms}) debe devolver dtype=uint8, "
            f"got {result.dtype}"
        )
        assert result.shape == expected, (
            f"{type(effect).__name__}.render(t={t_ms}) shape incorrecta: "
            f"esperada {expected}, recibida {result.shape}"
        )
        assert (result >= 0).all() and (result <= 255).all(), (
            f"{type(effect).__name__}.render(t={t_ms}) tiene valores fuera de [0,255]"
        )
        assert np.array_equal(bars_copy, _BARS_STATE), (
            f"{type(effect).__name__}.render(t={t_ms}) mutó bars_state (invariante de pureza)"
        )

    # Verificar PARAM_SCHEMA coherente
    if check_schema and effect.PARAM_SCHEMA:
        _assert_valid_param_schema(type(effect).__name__, effect.PARAM_SCHEMA)


def _default_params(effect: Effect) -> dict:
    """Extrae los valores por defecto del PARAM_SCHEMA del efecto."""
    return {
        key: spec.get("default", 0)
        for key, spec in effect.PARAM_SCHEMA.items()
    }


def _assert_valid_param_schema(name: str, schema: dict) -> None:
    """Verifica que cada entrada de PARAM_SCHEMA tiene campos requeridos coherentes."""
    valid_types = {"float", "int", "bool", "enum", "color"}
    for key, spec in schema.items():
        ptype = spec.get("type")
        assert ptype in valid_types, (
            f"{name}.PARAM_SCHEMA['{key}']: type='{ptype}' no válido. "
            f"Debe ser uno de: {sorted(valid_types)}"
        )
        if ptype in ("float", "int"):
            mn = spec.get("min")
            mx = spec.get("max")
            df = spec.get("default")
            if mn is not None and mx is not None:
                assert mn <= mx, (
                    f"{name}.PARAM_SCHEMA['{key}']: min={mn} > max={mx}"
                )
            if df is not None and mn is not None and mx is not None:
                assert mn <= df <= mx, (
                    f"{name}.PARAM_SCHEMA['{key}']: default={df} fuera de [{mn},{mx}]"
                )
            if ptype == "int" and df is not None:
                assert isinstance(df, int), (
                    f"{name}.PARAM_SCHEMA['{key}']: type='int' pero default={df!r} no es int"
                )
        elif ptype == "enum":
            opts = spec.get("options")
            assert isinstance(opts, list) and len(opts) > 0, (
                f"{name}.PARAM_SCHEMA['{key}']: type='enum' requiere 'options' no vacío"
            )
            df = spec.get("default")
            if df is not None:
                assert df in opts, (
                    f"{name}.PARAM_SCHEMA['{key}']: default={df!r} no está en options={opts}"
                )
