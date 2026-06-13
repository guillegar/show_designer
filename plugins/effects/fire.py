"""
fire.py — Simulación de llama (algoritmo Fire2012).

ID: 1014 · scope: PER_BAR · shape: (1, 93, 3)

Estado por instancia: self._heat persiste entre frames para continuidad visual.
Trade-off documentado: el calor es causal (no reproducible desde elapsed_time
aislado), pero produce una llama convincente en tiempo real.
"""
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import Effect, EffectScope, LEDS_PER_BAR


_HEAT_MAX = 255.0


class FireEffect(Effect):
    """Simulación de llama con paleta negro-rojo-amarillo-blanco."""
    name        = "fire"
    family      = "ambient"
    duration_ms = 2000
    scope       = EffectScope.PER_BAR
    description = "Simulación de llama (Fire2012)"
    PARAM_SCHEMA = {
        "intensity": {"type": "float", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.6, "label": "Intensidad"},
        "cooling":   {"type": "float", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.5, "label": "Enfriamiento"},
        "sparking":  {"type": "float", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.5, "label": "Chispas"},
    }

    def __init__(self):
        super().__init__()
        self._heat = np.zeros(LEDS_PER_BAR, dtype=np.float32)

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        intensity = float(params.get('intensity', 0.6))
        cooling   = float(params.get('cooling', 0.5))
        sparking  = float(params.get('sparking', 0.5))

        heat = self._heat

        # Step 1: Cool down each cell slightly
        cool = np.random.uniform(0, 1, LEDS_PER_BAR) * cooling * 3.0
        heat = np.maximum(0.0, heat - cool)

        # Step 2: Heat drifts upward (toward higher indices)
        heat[2:] = (heat[1:-1] + heat[:-2] + heat[:-2]) / 3.0
        heat[1] = (heat[0] + heat[0] + heat[0]) / 3.0

        # Step 3: Random sparking at the base
        if np.random.random() < sparking * intensity:
            y = np.random.randint(0, min(7, LEDS_PER_BAR))
            heat[y] = min(_HEAT_MAX, heat[y] + np.random.uniform(160, 255) * intensity)

        self._heat = heat

        # Map heat to fire palette: black → red → yellow → white
        h = np.clip(heat, 0.0, _HEAT_MAX)
        r = np.zeros(LEDS_PER_BAR, dtype=np.uint8)
        g = np.zeros(LEDS_PER_BAR, dtype=np.uint8)
        b = np.zeros(LEDS_PER_BAR, dtype=np.uint8)

        zone1 = h <= 85.0
        zone2 = (h > 85.0) & (h <= 170.0)
        zone3 = h > 170.0

        # Zone 1: black → red
        r[zone1] = np.clip(h[zone1] * 3.0, 0, 255).astype(np.uint8)

        # Zone 2: red → yellow
        r[zone2] = 255
        g[zone2] = np.clip((h[zone2] - 85.0) * 3.0, 0, 255).astype(np.uint8)

        # Zone 3: yellow → white
        r[zone3] = 255
        g[zone3] = 255
        b[zone3] = np.clip((h[zone3] - 170.0) * 3.0, 0, 255).astype(np.uint8)

        out = np.stack([r, g, b], axis=-1).reshape(1, LEDS_PER_BAR, 3)
        return out


PLUGIN_EFFECTS = {
    1014: FireEffect(),
}
