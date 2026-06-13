"""
theater_chase.py — Grupos alternos de LEDs que avanzan (marquesina de teatro).

ID: 1012 · scope: PER_BAR · shape: (1, 93, 3)
"""
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import Effect, EffectScope, LEDS_PER_BAR


class TheaterChaseEffect(Effect):
    """Grupos de LEDs encendidos/apagados que se desplazan."""
    name        = "theater_chase"
    family      = "chase"
    duration_ms = 2000
    scope       = EffectScope.PER_BAR
    description = "Grupos alternos de LEDs que avanzan (marquesina)"
    PARAM_SCHEMA = {}

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        t = elapsed_time / 1000.0

        r          = max(0, min(255, int(params.get('r', 255))))
        g          = max(0, min(255, int(params.get('g', 255))))
        b          = max(0, min(255, int(params.get('b', 255))))
        group_size = max(1, int(params.get('group_size', 4)))
        gap_size   = max(1, int(params.get('gap_size', 4)))
        speed      = float(params.get('speed', 2.0))  # grupos/s

        frame_n = int(t * speed)
        period  = group_size + gap_size

        idx = np.arange(LEDS_PER_BAR)
        phase = (idx + frame_n * group_size) % period
        mask = (phase < group_size).astype(np.uint8)

        out = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        out[0, :, 0] = r * mask
        out[0, :, 1] = g * mask
        out[0, :, 2] = b * mask
        return out


PLUGIN_EFFECTS = {
    1012: TheaterChaseEffect(),
}
