"""
rainbow_wave.py — Arcoíris completo que viaja por los LEDs (vectorizado).

ID: 1017 · scope: PER_BAR · shape: (1, 93, 3)
"""
from typing import Any

import numpy as np

from src.core.effects_engine import LEDS_PER_BAR, Effect, EffectScope


class RainbowWaveEffect(Effect):
    """Ola de arcoíris (hue 0→360) que viaja por la barra. Sin bucle Python."""
    name        = "rainbow_wave"
    family      = "color"
    duration_ms = 2000
    scope       = EffectScope.PER_BAR
    description = "Arcoíris animado por la barra (vectorizado)"
    PARAM_SCHEMA = {
        "speed":      {"type": "float", "min": 0.1, "max": 10.0, "step": 0.1,  "default": 1.0, "label": "Velocidad", "unit": "ciclos/s"},
        "saturation": {"type": "float", "min": 0.5, "max": 1.0,  "step": 0.05, "default": 1.0, "label": "Saturación"},
        "value":      {"type": "float", "min": 0.1, "max": 1.0,  "step": 0.05, "default": 1.0, "label": "Brillo"},
        "reverse":    {"type": "bool",                                           "default": False, "label": "Inverso"},
    }

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: dict[str, Any], **params) -> np.ndarray:
        t = elapsed_time / 1000.0

        speed      = float(params.get('speed', 1.0))
        saturation = max(0.5, min(1.0, float(params.get('saturation', 1.0))))
        value      = max(0.1, min(1.0, float(params.get('value', 1.0))))
        reverse    = bool(params.get('reverse', False))

        direction = -1.0 if reverse else 1.0

        idx = np.arange(LEDS_PER_BAR, dtype=np.float32)
        hue_deg = (idx / 92.0 * 360.0 + t * speed * 360.0 * direction) % 360.0

        # Vectorized HSV → RGB (no Python loop)
        h6 = hue_deg / 60.0
        hi = np.floor(h6).astype(np.int32) % 6
        f  = h6 - np.floor(h6)

        p = value * (1.0 - saturation)
        q = value * (1.0 - saturation * f)
        tv = value * (1.0 - saturation * (1.0 - f))

        r = np.select(
            [hi == 0, hi == 1, hi == 2, hi == 3, hi == 4, hi == 5],
            [value,   q,       p,       p,        tv,      value],
        )
        g = np.select(
            [hi == 0, hi == 1, hi == 2, hi == 3, hi == 4, hi == 5],
            [tv,      value,   value,   q,        p,       p],
        )
        b = np.select(
            [hi == 0, hi == 1, hi == 2, hi == 3, hi == 4, hi == 5],
            [p,       p,       tv,      value,    value,   q],
        )

        out = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        out[0, :, 0] = np.clip(r * 255, 0, 255).astype(np.uint8)
        out[0, :, 1] = np.clip(g * 255, 0, 255).astype(np.uint8)
        out[0, :, 2] = np.clip(b * 255, 0, 255).astype(np.uint8)
        return out


PLUGIN_EFFECTS = {
    1017: RainbowWaveEffect(),
}
