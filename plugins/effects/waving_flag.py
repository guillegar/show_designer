"""
waving_flag.py — Color por barra con ONDA (bandera ondeante)

Mantiene un color base fijo por barra (params r,g,b) pero modula el brillo con
una onda sinusoidal que viaja horizontalmente (según el índice de barra) y
ondula a lo largo de los LEDs → ilusión de bandera ondeando al viento.

Pensado para clips por-barra: scope="per_bar", layer=0, un clip por barra, con
params {"r","g","b","bar_index"}. Devuelve forma (1, LEDS, 3).

ID asignado: 1005 (WavingColorEffect)
"""
import math
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import (
    Effect, EffectScope, EffectGeometry, EffectSymmetry,
    LEDS_PER_BAR,
)


class WavingColorEffect(Effect):
    """Color base por barra con brillo ondulante que viaja por el escenario."""
    name        = "waving_color"
    family      = "bandera"
    duration_ms = 2000          # irrelevante: la onda es continua (usa t real)
    scope       = EffectScope.PER_BAR
    geometry    = EffectGeometry.GEOMETRY_3D
    symmetry    = EffectSymmetry.SYMMETRIC
    description = "Color sólido por barra con onda de brillo (bandera ondeante)"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        r = max(0, min(255, int(params.get('r', 255))))
        g = max(0, min(255, int(params.get('g', 255))))
        b = max(0, min(255, int(params.get('b', 255))))
        bar_index = float(params.get('bar_index', 0))

        speed   = float(params.get('speed', 1.0))     # ciclos/seg de la onda
        amp     = float(params.get('amplitude', 0.55))  # profundidad del ondeo
        bar_k   = float(params.get('bar_k', 2.2))     # desfase entre barras
        led_k   = float(params.get('led_k', 1.6))     # nº de ondas a lo largo del LED

        t = elapsed_time / 1000.0
        w = 2.0 * math.pi * speed
        lo = max(0.0, min(1.0, 1.0 - amp))   # brillo mínimo (color nunca se apaga)

        leds = np.arange(LEDS_PER_BAR, dtype=np.float32) / LEDS_PER_BAR
        # Fase: la onda VIAJA en +barra y +led (signo negativo = avanza)
        phase = w * t - bar_index * bar_k - leds * (2.0 * math.pi * led_k)
        bright = lo + (1.0 - lo) * 0.5 * (1.0 + np.sin(phase))  # (LEDS,)

        out = np.empty((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        out[0, :, 0] = np.clip(r * bright, 0, 255).astype(np.uint8)
        out[0, :, 1] = np.clip(g * bright, 0, 255).astype(np.uint8)
        out[0, :, 2] = np.clip(b * bright, 0, 255).astype(np.uint8)
        return out


PLUGIN_EFFECTS = {
    1005: WavingColorEffect(),
}
