"""
twinkle.py — Destellos aleatorios de LEDs con fase reproducible.

ID: 1013 · scope: PER_BAR · shape: (1, 93, 3)
"""
from typing import Any

import numpy as np

from src.core.effects_engine import LEDS_PER_BAR, Effect, EffectScope


class TwinkleEffect(Effect):
    """LEDs que brillan aleatoriamente con fase determinista por instancia."""
    name        = "twinkle"
    family      = "ambient"
    duration_ms = 2000
    scope       = EffectScope.PER_BAR
    description = "Destellos aleatorios reproducibles"
    PARAM_SCHEMA = {
        "r":              {"type": "int",   "min": 0,   "max": 255, "step": 1,    "default": 255, "label": "Rojo"},
        "g":              {"type": "int",   "min": 0,   "max": 255, "step": 1,    "default": 255, "label": "Verde"},
        "b":              {"type": "int",   "min": 0,   "max": 255, "step": 1,    "default": 255, "label": "Azul"},
        "density":        {"type": "float", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.3, "label": "Densidad"},
        "speed":          {"type": "float", "min": 0.1, "max": 20.0, "step": 0.1, "default": 3.0, "label": "Velocidad"},
        "min_brightness": {"type": "float", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.0, "label": "Brillo mínimo"},
    }

    def __init__(self):
        super().__init__()
        rng = np.random.default_rng(42)
        self._phases = rng.uniform(0, 2 * np.pi, LEDS_PER_BAR).astype(np.float32)

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: dict[str, Any], **params) -> np.ndarray:
        t = elapsed_time / 1000.0

        r              = max(0, min(255, int(params.get('r', 255))))
        g              = max(0, min(255, int(params.get('g', 255))))
        b              = max(0, min(255, int(params.get('b', 255))))
        density        = float(params.get('density', 0.3))
        speed          = float(params.get('speed', 3.0))
        min_brightness = float(params.get('min_brightness', 0.0))

        vals = np.sin(t * speed + self._phases)  # -1..1

        # Active mask: density fraction of LEDs can twinkle
        active = (self._phases % (2 * np.pi)) < (density * 2 * np.pi)
        brightness = np.where(active, np.maximum(min_brightness, vals), 0.0)
        brightness = np.maximum(0.0, brightness)

        out = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        out[0, :, 0] = np.clip(r * brightness, 0, 255).astype(np.uint8)
        out[0, :, 1] = np.clip(g * brightness, 0, 255).astype(np.uint8)
        out[0, :, 2] = np.clip(b * brightness, 0, 255).astype(np.uint8)
        return out


PLUGIN_EFFECTS = {
    1013: TwinkleEffect(),
}
