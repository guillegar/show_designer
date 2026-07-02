"""
pixel_chase.py — Punto de luz que corre de extremo a extremo con estela.

ID: 1011 · scope: PER_BAR · shape: (1, 93, 3)
"""
from typing import Any

import numpy as np

from src.core.effects_engine import LEDS_PER_BAR, Effect, EffectScope


class PixelChaseEffect(Effect):
    """Punto gaussiano que corre por la barra dejando estela."""
    name        = "pixel_chase"
    family      = "chase"
    duration_ms = 2000
    scope       = EffectScope.PER_BAR
    description = "Punto de luz que corre con estela"
    PARAM_SCHEMA = {
        "r":          {"type": "int",   "min": 0,    "max": 255,  "step": 1,    "default": 255,  "label": "Rojo"},
        "g":          {"type": "int",   "min": 0,    "max": 255,  "step": 1,    "default": 255,  "label": "Verde"},
        "b":          {"type": "int",   "min": 0,    "max": 255,  "step": 1,    "default": 0,    "label": "Azul"},
        "speed":      {"type": "float", "min": 1.0,  "max": 200.0, "step": 1.0, "default": 40.0, "label": "Velocidad", "unit": "LEDs/s"},
        "width":      {"type": "float", "min": 1.0,  "max": 30.0, "step": 0.5,  "default": 5.0,  "label": "Ancho", "unit": "px"},
        "mode":       {"type": "enum",  "options": ["bounce", "cycle"],          "default": "bounce", "label": "Modo"},
        "tail_decay": {"type": "float", "min": 0.0,  "max": 0.99, "step": 0.01, "default": 0.85, "label": "Estela"},
    }

    def __init__(self):
        super().__init__()
        self._last_frame = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.float32)

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: dict[str, Any], **params) -> np.ndarray:
        t = elapsed_time / 1000.0

        r = max(0, min(255, int(params.get('r', 255))))
        g = max(0, min(255, int(params.get('g', 255))))
        b = max(0, min(255, int(params.get('b', 0))))
        speed      = float(params.get('speed', 40.0))       # LEDs/s
        width      = max(1.0, float(params.get('width', 5.0)))  # LEDs (gaussian)
        mode       = str(params.get('mode', 'bounce'))
        tail_decay = float(params.get('tail_decay', 0.85))

        # Compute position
        if mode == 'cycle':
            pos = (t * speed) % LEDS_PER_BAR
        else:  # bounce
            period = 2.0 * LEDS_PER_BAR / max(speed, 0.001)
            t_mod = t % period
            if t_mod < period / 2:
                pos = t_mod / (period / 2) * (LEDS_PER_BAR - 1)
            else:
                pos = (LEDS_PER_BAR - 1) - (t_mod - period / 2) / (period / 2) * (LEDS_PER_BAR - 1)

        # Gaussian spot
        idx = np.arange(LEDS_PER_BAR, dtype=np.float32)
        sigma = width / 3.0
        gauss = np.exp(-0.5 * ((idx - pos) / sigma) ** 2)

        current = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.float32)
        current[0, :, 0] = r * gauss
        current[0, :, 1] = g * gauss
        current[0, :, 2] = b * gauss

        # Trail: blend with decayed previous frame
        blended = np.maximum(current, self._last_frame * tail_decay)
        self._last_frame = blended.copy()

        out = np.clip(blended, 0, 255).astype(np.uint8)
        return out


PLUGIN_EFFECTS = {
    1011: PixelChaseEffect(),
}
