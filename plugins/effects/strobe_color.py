"""
strobe_color.py — Estrobo con color configurable y duty cycle.

ID: 1015 · scope: PER_BAR · shape: (1, 93, 3)
"""
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import Effect, EffectScope, LEDS_PER_BAR


class StrobeColorEffect(Effect):
    """Estrobo por barra con color, frecuencia y duty cycle configurables."""
    name        = "strobe_color"
    family      = "strobe"
    duration_ms = 1000
    scope       = EffectScope.PER_BAR
    description = "Estrobo de color por barra con duty cycle"
    PARAM_SCHEMA = {}

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        t = elapsed_time / 1000.0

        r          = max(0, min(255, int(params.get('r', 255))))
        g          = max(0, min(255, int(params.get('g', 255))))
        b          = max(0, min(255, int(params.get('b', 255))))
        rate_hz    = max(0.5, float(params.get('rate_hz', 8.0)))
        duty_cycle = max(0.1, min(0.9, float(params.get('duty_cycle', 0.5))))

        period_s = 1.0 / rate_hz
        phase = t % period_s

        out = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        if phase < duty_cycle * period_s:
            out[0, :, 0] = r
            out[0, :, 1] = g
            out[0, :, 2] = b
        return out


PLUGIN_EFFECTS = {
    1015: StrobeColorEffect(),
}
