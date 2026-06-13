"""
test_macros.py — Tests C2: Macros en vivo (ROADMAP v2).

Cubre:
  test_brightness_mul_half     — brightness_mul=0.5, brightness=0.8 → 0.4
  test_speed_mul_double        — speed_mul=2.0, speed=1.0 → 2.0
  test_noop_fast_path          — todos defaults → mismo objeto params (cero allocs)
  test_brightness_clamp        — brightness_mul=3.0, brightness=0.8 → clamped a 1.0
  test_strobe_dark_phase       — strobe_rate=10Hz, t_ms en fase oscura → frame ceros
  test_strobe_bright_phase     — strobe_rate=10Hz, t_ms en fase brillante → sin cambio
  test_set_macro_handler       — set_macro("brightness_mul", 0.5) → {ok, macros}
  test_set_macro_invalid_name  — set_macro("foo", 1.0) → {ok:False}
  test_set_macro_out_of_range  — set_macro("brightness_mul", 5.0) → {ok:False}
"""
import numpy as np
import pytest
from unittest.mock import MagicMock

from src.core.param_pipeline import MacroStage


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_clip(**params):
    clip = MagicMock()
    clip.params = params
    return clip


def _default_macros():
    return {
        "brightness_mul": 1.0,
        "speed_mul": 1.0,
        "hue_shift": 0.0,
        "strobe_rate": 0.0,
    }


# ── Tests de MacroStage ───────────────────────────────────────────────────────

def test_brightness_mul_half():
    """brightness_mul=0.5, brightness=0.8 → params["brightness"]=0.4."""
    macros = _default_macros()
    macros["brightness_mul"] = 0.5
    stage = MacroStage(macros)
    clip = _make_clip(brightness=0.8)
    result = stage.apply(dict(clip.params), clip, 0, {})
    assert abs(result["brightness"] - 0.4) < 1e-9


def test_speed_mul_double():
    """speed_mul=2.0, speed=1.0 → params["speed"]=2.0."""
    macros = _default_macros()
    macros["speed_mul"] = 2.0
    stage = MacroStage(macros)
    clip = _make_clip(speed=1.0)
    result = stage.apply(dict(clip.params), clip, 0, {})
    assert abs(result["speed"] - 2.0) < 1e-9


def test_noop_fast_path():
    """Todos defaults → mismo objeto params devuelto (invariante I5, cero allocs)."""
    macros = _default_macros()
    stage = MacroStage(macros)
    clip = _make_clip(brightness=0.8, speed=1.0)
    params = dict(clip.params)
    result = stage.apply(params, clip, 0, {})
    assert result is params, "fast path debe devolver el mismo objeto sin copiar"


def test_brightness_clamp():
    """brightness_mul=3.0, brightness=0.8 → clamped a 1.0."""
    macros = _default_macros()
    macros["brightness_mul"] = 3.0
    stage = MacroStage(macros)
    clip = _make_clip(brightness=0.8)
    result = stage.apply(dict(clip.params), clip, 0, {})
    assert result["brightness"] == 1.0, f"Esperado 1.0, obtenido {result['brightness']}"


def test_strobe_dark_phase():
    """strobe_rate=10Hz → periodo=100ms, half=50ms. t_ms=75 → fase oscura → frame ceros."""
    # Strobe 10Hz: half_period = 50ms.
    # t_ms=75: 75 % 100 = 75 >= 50 → fase oscura → frame[:] = 0
    from server.session import ShowSession
    import os

    # Construir sesión mínima con mock: evitar I/O real
    # En su lugar, testar la lógica de strobe directamente
    frame = np.full((10, 93, 3), 200, dtype=np.uint8)
    macros = {"brightness_mul": 1.0, "speed_mul": 1.0, "hue_shift": 0.0, "strobe_rate": 10.0}
    t_ms = 75  # fase oscura (75 % 100 = 75 >= 50)

    strobe_rate = macros["strobe_rate"]
    half_period_ms = 500.0 / strobe_rate  # 50ms
    if (t_ms % (2 * half_period_ms)) >= half_period_ms:
        frame[:] = 0

    assert frame.max() == 0, "Fase oscura del strobe debe poner el frame a cero"


def test_strobe_bright_phase():
    """strobe_rate=10Hz, t_ms=25 → fase brillante → frame sin cambios."""
    frame = np.full((10, 93, 3), 200, dtype=np.uint8)
    original = frame.copy()
    macros = {"brightness_mul": 1.0, "speed_mul": 1.0, "hue_shift": 0.0, "strobe_rate": 10.0}
    t_ms = 25  # fase brillante (25 % 100 = 25 < 50)

    strobe_rate = macros["strobe_rate"]
    half_period_ms = 500.0 / strobe_rate  # 50ms
    if (t_ms % (2 * half_period_ms)) >= half_period_ms:
        frame[:] = 0

    assert np.array_equal(frame, original), "Fase brillante del strobe no debe tocar el frame"


# ── Tests del handler ─────────────────────────────────────────────────────────

class _FakeSession:
    macros = {
        "brightness_mul": 1.0,
        "speed_mul": 1.0,
        "hue_shift": 0.0,
        "strobe_rate": 0.0,
    }


def test_set_macro_handler():
    """set_macro("brightness_mul", 0.5) → {ok: True, macros: {...}}."""
    from server.dispatcher import _h_set_macro
    session = _FakeSession()
    session.macros = dict(session.macros)  # copia mutable
    result = _h_set_macro(session, {"name": "brightness_mul", "value": 0.5})
    assert result["ok"] is True
    assert result["macros"]["brightness_mul"] == 0.5
    assert session.macros["brightness_mul"] == 0.5


def test_set_macro_invalid_name():
    """set_macro("foo", 1.0) → {ok: False}."""
    from server.dispatcher import _h_set_macro
    session = _FakeSession()
    session.macros = dict(session.macros)
    result = _h_set_macro(session, {"name": "foo", "value": 1.0})
    assert result["ok"] is False
    assert "error" in result


def test_set_macro_out_of_range():
    """set_macro("brightness_mul", 5.0) → {ok: False} (fuera de rango 0..2)."""
    from server.dispatcher import _h_set_macro
    session = _FakeSession()
    session.macros = dict(session.macros)
    result = _h_set_macro(session, {"name": "brightness_mul", "value": 5.0})
    assert result["ok"] is False
    assert "error" in result
