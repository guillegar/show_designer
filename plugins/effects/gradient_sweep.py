"""
gradient_sweep.py — Gradiente de color que barre de izquierda a derecha.

ID: 1010 · scope: PER_BAR · shape: (1, 93, 3)
"""
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import Effect, EffectScope, LEDS_PER_BAR


class GradientSweepEffect(Effect):
    """Gradiente lineal entre dos colores que avanza con el tiempo."""
    name        = "gradient_sweep"
    family      = "color"
    duration_ms = 2000
    scope       = EffectScope.PER_BAR
    description = "Gradiente de color que barre con el tiempo"
    PARAM_SCHEMA = {
        "color1_r": {"type": "int",   "min": 0,   "max": 255, "step": 1,   "default": 255, "label": "Color1 R"},
        "color1_g": {"type": "int",   "min": 0,   "max": 255, "step": 1,   "default": 0,   "label": "Color1 G"},
        "color1_b": {"type": "int",   "min": 0,   "max": 255, "step": 1,   "default": 0,   "label": "Color1 B"},
        "color2_r": {"type": "int",   "min": 0,   "max": 255, "step": 1,   "default": 0,   "label": "Color2 R"},
        "color2_g": {"type": "int",   "min": 0,   "max": 255, "step": 1,   "default": 0,   "label": "Color2 G"},
        "color2_b": {"type": "int",   "min": 0,   "max": 255, "step": 1,   "default": 255, "label": "Color2 B"},
        "speed":    {"type": "float", "min": 0.1, "max": 10.0, "step": 0.1, "default": 1.0, "label": "Velocidad", "unit": "ciclos/s"},
        "offset":   {"type": "float", "min": 0.0, "max": 1.0,  "step": 0.01, "default": 0.0, "label": "Offset"},
    }

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        t = elapsed_time / 1000.0

        r1 = max(0, min(255, int(params.get('color1_r', 255))))
        g1 = max(0, min(255, int(params.get('color1_g', 0))))
        b1 = max(0, min(255, int(params.get('color1_b', 0))))
        r2 = max(0, min(255, int(params.get('color2_r', 0))))
        g2 = max(0, min(255, int(params.get('color2_g', 0))))
        b2 = max(0, min(255, int(params.get('color2_b', 255))))
        speed  = float(params.get('speed', 1.0))
        offset = float(params.get('offset', 0.0)) % 1.0

        t_offset = (t * speed + offset) % 1.0

        i = np.arange(LEDS_PER_BAR, dtype=np.float32)
        lerp_val = (i / 92.0 + t_offset) % 1.0  # (93,)

        out = np.empty((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        out[0, :, 0] = np.clip(r1 + (r2 - r1) * lerp_val, 0, 255).astype(np.uint8)
        out[0, :, 1] = np.clip(g1 + (g2 - g1) * lerp_val, 0, 255).astype(np.uint8)
        out[0, :, 2] = np.clip(b1 + (b2 - b1) * lerp_val, 0, 255).astype(np.uint8)
        return out


PLUGIN_EFFECTS = {
    1010: GradientSweepEffect(),
}
