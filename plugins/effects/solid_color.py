"""
solid_color.py — Efecto de color sólido ESTABLE

Devuelve un color constante (sin fade, sin pulso) durante TODA la duración del
clip. Pensado para clips por-barra: con scope="per_bar" y layer=0, compute_frame
hace frame[clip.track] = r[0], pintando esa barra de un color fijo.

Forma de salida: (1, LEDS_PER_BAR, 3) → el motor la asigna a la barra del clip.

Params:
    r, g, b : componentes 0-255 (por defecto blanco)

ID asignado: 1004 (SolidColorEffect)
"""
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import (
    Effect, EffectScope, EffectGeometry, EffectSymmetry,
    LEDS_PER_BAR,
)


class SolidColorEffect(Effect):
    """Color sólido constante. No depende de elapsed_time → nunca se apaga."""
    name        = "solid_color"
    family      = "bandera"
    duration_ms = 1000          # irrelevante: la salida es constante
    scope       = EffectScope.PER_BAR
    geometry    = EffectGeometry.GEOMETRY_3D
    symmetry    = EffectSymmetry.SYMMETRIC
    description = "Color sólido fijo por barra (params r,g,b)"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        r = int(params.get('r', 255))
        g = int(params.get('g', 255))
        b = int(params.get('b', 255))
        # Clamp 0-255
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))

        out = np.empty((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        out[0, :, 0] = r
        out[0, :, 1] = g
        out[0, :, 2] = b
        return out


# IDs en rango 1000+ para no colisionar con efectos base (0-999)
PLUGIN_EFFECTS = {
    1004: SolidColorEffect(),
}
