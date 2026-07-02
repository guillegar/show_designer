"""
test_color_async.py — Valida los efectos asimétricos 1034/1035 con el harness H1.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plugins.effects.color_async import (
    PLUGIN_EFFECTS,
    AudioPumpEffect,
    DirectionalCometEffect,
    OffCenterRadialEffect,
)
from tests.plugin_test_harness import assert_valid_plugin_effect

_EMPTY_CTX = {"rms": 0.0, "norm": {"rms": 0.0}}
_BARS_STATE = np.zeros((10, 93, 3), dtype=np.uint8)


def test_plugin_ids_registered():
    assert set(PLUGIN_EFFECTS) == {1034, 1035, 1036}
    assert isinstance(PLUGIN_EFFECTS[1034], DirectionalCometEffect)
    assert isinstance(PLUGIN_EFFECTS[1035], OffCenterRadialEffect)
    assert isinstance(PLUGIN_EFFECTS[1036], AudioPumpEffect)


def test_directional_comet_valid():
    assert_valid_plugin_effect(DirectionalCometEffect())


def test_offcenter_radial_valid():
    assert_valid_plugin_effect(OffCenterRadialEffect())


def test_audio_pump_valid():
    assert_valid_plugin_effect(AudioPumpEffect())


def test_audio_pump_reacts_to_rms():
    """Más rms → más brillo (el rig late con el kick)."""
    eff = AudioPumpEffect()
    params = {"r": 255, "g": 90, "b": 30, "gamma": 2.0, "tilt": 0.0,
              "min_brightness": 0.04, "pump_source": "rms"}
    quiet = eff.render(0.0, _BARS_STATE.copy(), {"norm": {"rms": 0.05}}, **params)
    loud = eff.render(0.0, _BARS_STATE.copy(), {"norm": {"rms": 0.9}}, **params)
    assert int(loud[:, :, 0].mean()) > int(quiet[:, :, 0].mean()) + 30, \
        "el pump no reacciona al rms"


def test_comet_pump_modulates_brightness():
    """Con pump=1, el cometa es más brillante en un instante 'loud' que 'quiet'."""
    eff = DirectionalCometEffect()
    base = {"r": 255, "g": 90, "b": 30, "speed": 1.5, "width": 1.1, "tail": 3.0,
            "direction": "ltr", "min_brightness": 0.0, "pump": 1.0, "pump_source": "rms"}
    quiet = eff.render(500.0, _BARS_STATE.copy(), {"norm": {"rms": 0.05}}, **base)
    loud = eff.render(500.0, _BARS_STATE.copy(), {"norm": {"rms": 0.9}}, **base)
    assert int(loud[:, :, 0].max()) > int(quiet[:, :, 0].max()), "pump no modula el cometa"


@pytest.mark.parametrize("direction", ["ltr", "rtl"])
def test_comet_is_directional(direction):
    """El cometa cruza de un lado a otro: el bar más brillante se DESPLAZA con el tiempo
    en el sentido pedido (no rebota desde el centro)."""
    eff = DirectionalCometEffect()
    params = {"r": 255, "g": 80, "b": 20, "speed": 2.0, "width": 1.0,
              "tail": 2.0, "direction": direction, "min_brightness": 0.0}
    # Muestreamos a lo largo de un cruce completo del cabezal por el array.
    peaks = []
    for t_ms in (1000.0, 3000.0, 5000.0):
        frame = eff.render(t_ms, _BARS_STATE.copy(), _EMPTY_CTX, **params)
        bar_bright = frame[:, 0, 0].astype(int)  # rojo por barra
        peaks.append(int(np.argmax(bar_bright)))
    # Debe moverse (no quedarse clavado en el centro 4/5)
    assert len(set(peaks)) >= 2, f"el cometa no se desplaza: peaks={peaks}"
    # Y el sentido debe ser el pedido: ltr crece, rtl decrece (monótono global).
    if direction == "ltr":
        assert peaks[-1] > peaks[0], f"ltr no avanza a la derecha: {peaks}"
    else:
        assert peaks[-1] < peaks[0], f"rtl no avanza a la izquierda: {peaks}"


def test_offcenter_origin_is_brightest_at_t0():
    """En t≈0 el anillo está en el origen → ese bar (lateral) es el más brillante."""
    eff = OffCenterRadialEffect()
    params = {"r": 255, "g": 80, "b": 20, "speed": 1.0, "width": 0.9,
              "origin": 0, "min_brightness": 0.0}
    frame = eff.render(1.0, _BARS_STATE.copy(), _EMPTY_CTX, **params)
    bar_bright = frame[:, 0, 0].astype(int)
    assert int(np.argmax(bar_bright)) == 0, "el origen lateral no es el más brillante en t0"
