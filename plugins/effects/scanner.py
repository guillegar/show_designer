"""
scanner.py — Spot luminoso que oscila de punta a punta (vectorizado).

ID: 1018 · scope: PER_BAR · shape: (1, 93, 3)
"""
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import Effect, EffectScope, LEDS_PER_BAR

_TWO_PI = 2.0 * np.pi


class ScannerEffect(Effect):
    """Spot gaussiano que oscila (sin o bounce), opcionalmente reactivo al RMS."""
    name        = "scanner"
    family      = "chase"
    duration_ms = 2000
    scope       = EffectScope.PER_BAR
    description = "Spot oscilante tipo scanner (vectorizado)"
    PARAM_SCHEMA = {}

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        t = elapsed_time / 1000.0

        r    = max(0, min(255, int(params.get('r', 255))))
        g    = max(0, min(255, int(params.get('g', 255))))
        b    = max(0, min(255, int(params.get('b', 255))))
        speed          = float(params.get('speed', 1.0))
        width          = max(1.0, float(params.get('width', 8.0)))
        mode           = str(params.get('mode', 'sin'))
        brightness_env = bool(params.get('brightness_env', False))

        if mode == 'sin':
            pos = 46.0 + 46.0 * np.sin(t * speed * _TWO_PI)
        else:  # bounce (linear)
            period = 2.0 / max(speed, 1e-6)
            t_mod  = t % period
            half   = period / 2.0
            if t_mod < half:
                pos = (t_mod / half) * 92.0
            else:
                pos = 92.0 - ((t_mod - half) / half) * 92.0

        # Gaussian spot (vectorized — no Python loop)
        idx   = np.arange(LEDS_PER_BAR, dtype=np.float32)
        sigma = width / 3.0
        gauss = np.exp(-0.5 * ((idx - pos) / sigma) ** 2)

        if brightness_env:
            norm     = audio_context.get('norm', {}) if audio_context else {}
            rms_norm = float(norm.get('rms', 0.5))
            gauss   *= rms_norm

        out = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        out[0, :, 0] = np.clip(r * gauss, 0, 255).astype(np.uint8)
        out[0, :, 1] = np.clip(g * gauss, 0, 255).astype(np.uint8)
        out[0, :, 2] = np.clip(b * gauss, 0, 255).astype(np.uint8)
        return out


PLUGIN_EFFECTS = {
    1018: ScannerEffect(),
}
