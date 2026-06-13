"""
vu_meter.py — Barra de nivel reactiva al audio (RMS).

ID: 1016 · scope: PER_BAR · shape: (1, 93, 3) · AUDIO REACTIVO
"""
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import Effect, EffectScope, LEDS_PER_BAR


class VuMeterEffect(Effect):
    """Barra de nivel que sube con el RMS. Gradiente low→high color."""
    name        = "vu_meter"
    family      = "audio"
    duration_ms = 1000
    scope       = EffectScope.PER_BAR
    description = "VU meter reactivo al RMS con peak hold"
    PARAM_SCHEMA = {
        "r_low":        {"type": "int",   "min": 0,   "max": 255,    "step": 1,    "default": 0,    "label": "R bajo"},
        "g_low":        {"type": "int",   "min": 0,   "max": 255,    "step": 1,    "default": 255,  "label": "G bajo"},
        "b_low":        {"type": "int",   "min": 0,   "max": 255,    "step": 1,    "default": 0,    "label": "B bajo"},
        "r_high":       {"type": "int",   "min": 0,   "max": 255,    "step": 1,    "default": 255,  "label": "R alto"},
        "g_high":       {"type": "int",   "min": 0,   "max": 255,    "step": 1,    "default": 0,    "label": "G alto"},
        "b_high":       {"type": "int",   "min": 0,   "max": 255,    "step": 1,    "default": 0,    "label": "B alto"},
        "smoothing":    {"type": "float", "min": 0.0, "max": 0.95,   "step": 0.05, "default": 0.7,  "label": "Suavizado"},
        "peak_hold_ms": {"type": "float", "min": 0.0, "max": 2000.0, "step": 50.0, "default": 500.0, "label": "Peak hold", "unit": "ms"},
    }

    def __init__(self):
        super().__init__()
        self._smooth_level = 0.0
        self._peak_level   = 0.0
        self._peak_time    = 0.0

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        t = elapsed_time / 1000.0

        r_low  = max(0, min(255, int(params.get('r_low',  0))))
        g_low  = max(0, min(255, int(params.get('g_low',  255))))
        b_low  = max(0, min(255, int(params.get('b_low',  0))))
        r_high = max(0, min(255, int(params.get('r_high', 255))))
        g_high = max(0, min(255, int(params.get('g_high', 0))))
        b_high = max(0, min(255, int(params.get('b_high', 0))))
        smoothing    = max(0.0, min(0.95, float(params.get('smoothing', 0.7))))
        peak_hold_ms = max(0.0, float(params.get('peak_hold_ms', 500.0)))

        norm     = audio_context.get('norm', {}) if audio_context else {}
        rms_norm = float(norm.get('rms', 0.5))

        # EMA smoothing
        self._smooth_level = self._smooth_level * smoothing + rms_norm * (1.0 - smoothing)
        level = self._smooth_level

        # Peak hold
        if level >= self._peak_level:
            self._peak_level = level
            self._peak_time  = t
        elif (t - self._peak_time) > peak_hold_ms / 1000.0:
            self._peak_level = max(0.0, self._peak_level - 0.005)

        n_lit = round(level * (LEDS_PER_BAR - 1))

        idx = np.arange(LEDS_PER_BAR, dtype=np.float32)
        lerp = idx / 92.0

        out = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        lit_mask = idx <= n_lit

        out[0, lit_mask, 0] = np.clip(r_low + (r_high - r_low) * lerp[lit_mask], 0, 255).astype(np.uint8)
        out[0, lit_mask, 1] = np.clip(g_low + (g_high - g_low) * lerp[lit_mask], 0, 255).astype(np.uint8)
        out[0, lit_mask, 2] = np.clip(b_low + (b_high - b_low) * lerp[lit_mask], 0, 255).astype(np.uint8)

        # Peak indicator
        peak_idx = min(92, round(self._peak_level * 92))
        if peak_idx >= 0:
            out[0, peak_idx, :] = 255

        return out


PLUGIN_EFFECTS = {
    1016: VuMeterEffect(),
}
