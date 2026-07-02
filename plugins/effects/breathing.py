"""
breathing.py — Fade suave in/out senoidal, opcionalmente reactivo al audio.

ID: 1019 · scope: PER_BAR · shape: (1, 93, 3)
"""
from typing import Any

import numpy as np

from src.core.effects_engine import LEDS_PER_BAR, Effect, EffectScope

_TWO_PI = 2.0 * np.pi


class BreathingEffect(Effect):
    """Brillo que respira (seno) o sigue el audio en tiempo real."""
    name        = "breathing"
    family      = "ambient"
    duration_ms = 2000
    scope       = EffectScope.PER_BAR
    description = "Fade senoidal in/out, opcionalmente reactivo al audio"
    PARAM_SCHEMA = {
        "r":              {"type": "int",   "min": 0,   "max": 255,  "step": 1,   "default": 255,   "label": "Rojo"},
        "g":              {"type": "int",   "min": 0,   "max": 255,  "step": 1,   "default": 255,   "label": "Verde"},
        "b":              {"type": "int",   "min": 0,   "max": 255,  "step": 1,   "default": 255,   "label": "Azul"},
        "rate_hz":        {"type": "float", "min": 0.1, "max": 5.0,  "step": 0.1, "default": 0.5,   "label": "Velocidad", "unit": "ciclos/s"},
        "min_brightness": {"type": "float", "min": 0.0, "max": 0.5,  "step": 0.05, "default": 0.0,  "label": "Brillo mínimo"},
        "audio_reactive": {"type": "bool",                                          "default": False, "label": "Reactivo al audio"},
        "audio_source":   {"type": "enum",  "options": ["rms", "flux"],             "default": "rms", "label": "Fuente audio"},
    }

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: dict[str, Any], **params) -> np.ndarray:
        t = elapsed_time / 1000.0

        r              = max(0, min(255, int(params.get('r', 255))))
        g              = max(0, min(255, int(params.get('g', 255))))
        b              = max(0, min(255, int(params.get('b', 255))))
        rate_hz        = max(0.1, float(params.get('rate_hz', 0.5)))
        min_brightness = max(0.0, min(0.5, float(params.get('min_brightness', 0.0))))
        audio_reactive = bool(params.get('audio_reactive', False))
        audio_source   = str(params.get('audio_source', 'rms'))

        if audio_reactive:
            norm = audio_context.get('norm', {}) if audio_context else {}
            key  = audio_source if audio_source in ('rms', 'flux') else 'rms'
            sig  = float(norm.get(key, 0.5))
            brightness = min_brightness + (1.0 - min_brightness) * sig
        else:
            brightness = min_brightness + (1.0 - min_brightness) * (
                0.5 + 0.5 * np.sin(t * rate_hz * _TWO_PI)
            )

        brightness = max(0.0, min(1.0, float(brightness)))

        out = np.empty((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        out[0, :, 0] = int(r * brightness)
        out[0, :, 1] = int(g * brightness)
        out[0, :, 2] = int(b * brightness)
        return out


PLUGIN_EFFECTS = {
    1019: BreathingEffect(),
}
