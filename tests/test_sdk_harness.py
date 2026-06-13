"""
test_sdk_harness.py — Tests del harness de plugins SDK (H1).

Cubre:
  - plugin_template.py pasa el harness sin errores.
  - Efecto con shape incorrecta → harness falla con AssertionError descriptivo.
  - Efecto con PARAM_SCHEMA incoherente (default fuera de rango) → harness avisa.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pytest

from src.core.effects_engine import Effect, EffectScope, LEDS_PER_BAR
from tests.plugin_test_harness import assert_valid_plugin_effect


# ── Efecto válido: el template debe pasar ────────────────────────────────────

def test_plugin_template_passes_harness():
    """plugin_template.py satisface todos los contratos del SDK."""
    from plugins.effects.plugin_template import TemplateEffect
    assert_valid_plugin_effect(TemplateEffect())


# ── Efecto con shape incorrecta ───────────────────────────────────────────────

class _BadShapeEffect(Effect):
    """Devuelve (2, LEDS_PER_BAR, 3) cuando scope=PER_BAR exige (1, LEDS_PER_BAR, 3)."""
    name = "_bad_shape"
    scope = EffectScope.PER_BAR

    def render(self, elapsed_time, bars_state, audio_context, **params):
        return np.zeros((2, LEDS_PER_BAR, 3), dtype=np.uint8)


def test_harness_rejects_bad_shape():
    """Efecto con shape incorrecta → harness lanza AssertionError con mensaje claro."""
    with pytest.raises(AssertionError, match="shape"):
        assert_valid_plugin_effect(_BadShapeEffect())


# ── Efecto con PARAM_SCHEMA incoherente ──────────────────────────────────────

class _BadSchemaEffect(Effect):
    """default=3.5 fuera del rango [0, 2] en un parámetro float."""
    name = "_bad_schema"
    scope = EffectScope.PER_BAR
    PARAM_SCHEMA = {
        "speed": {"type": "float", "min": 0.0, "max": 2.0, "default": 3.5, "label": "Vel"},
    }

    def render(self, elapsed_time, bars_state, audio_context, **params):
        return np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)


def test_harness_rejects_bad_schema_default_out_of_range():
    """PARAM_SCHEMA con default fuera de rango → harness lanza AssertionError."""
    with pytest.raises(AssertionError, match="default"):
        assert_valid_plugin_effect(_BadSchemaEffect())


# ── Efecto ALL_BARS válido ────────────────────────────────────────────────────

class _AllBarsEffect(Effect):
    name = "_all_bars_ok"
    scope = EffectScope.ALL_BARS
    PARAM_SCHEMA = {}

    def render(self, elapsed_time, bars_state, audio_context, **params):
        from src.core.effects_engine import NUM_BARS
        return np.full((NUM_BARS, LEDS_PER_BAR, 3), 128, dtype=np.uint8)


def test_harness_accepts_all_bars_effect():
    """Efecto ALL_BARS con shape correcta pasa el harness."""
    assert_valid_plugin_effect(_AllBarsEffect())


# ── Harness detecta mutación de bars_state ────────────────────────────────────

class _MutatingEffect(Effect):
    name = "_mutating"
    scope = EffectScope.PER_BAR

    def render(self, elapsed_time, bars_state, audio_context, **params):
        bars_state[0, 0, 0] = 42  # muta el frame de entrada — violación del contrato
        return np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)


def test_harness_detects_bars_state_mutation():
    """Efecto que muta bars_state → harness lanza AssertionError."""
    with pytest.raises(AssertionError, match="bars_state"):
        assert_valid_plugin_effect(_MutatingEffect())
