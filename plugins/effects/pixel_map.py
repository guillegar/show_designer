"""
pixel_map.py — Efecto PixelMapEffect (K2)

Mapea una región de una imagen PNG/JPG o vídeo MP4 a los LEDs de la barra.
Cada clip puede apuntar a un archivo diferente y a una región configurable.

PARAM_SCHEMA es compatible con la UI auto-generada de F2 (get_effect_schema).
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np

from src.core.effects_engine import Effect, EffectScope, LEDS_PER_BAR
from src.core.pixel_map import sample_image_region


class PixelMapEffect(Effect):
    name        = "pixel_map"
    family      = "mapping"
    duration_ms = 4000
    scope       = EffectScope.PER_BAR
    description = "Mapea región de imagen/vídeo a los LEDs de la barra"
    PARAM_SCHEMA = {
        "source_path": {
            "type": "str", "default": "",
            "label": "Archivo fuente (PNG/JPG/MP4)",
        },
        "x": {
            "type": "int", "min": 0, "max": 9999, "default": 0,
            "label": "X origen",
        },
        "y": {
            "type": "int", "min": 0, "max": 9999, "default": 0,
            "label": "Y origen",
        },
        "width": {
            "type": "int", "min": 1, "max": 9999, "default": 100,
            "label": "Ancho región",
        },
        "height": {
            "type": "int", "min": 1, "max": 9999, "default": 100,
            "label": "Alto región",
        },
        "fit_mode": {
            "type": "enum", "options": ["stretch", "crop", "tile"],
            "default": "stretch", "label": "Ajuste",
        },
        "speed": {
            "type": "float", "min": 0.1, "max": 4.0, "default": 1.0,
            "label": "Velocidad (vídeo)", "unit": "x",
        },
    }

    def render(
        self,
        elapsed_time: float,
        bars_state: np.ndarray,
        audio_context: Dict[str, Any],
        **params,
    ) -> np.ndarray:
        source_path: str = params.get("source_path", "") or ""
        x      = int(params.get("x", 0))
        y      = int(params.get("y", 0))
        width  = max(1, int(params.get("width", 100)))
        height = max(1, int(params.get("height", 100)))
        fit_mode = str(params.get("fit_mode", "stretch"))
        speed  = float(params.get("speed", 1.0))

        # Para vídeo: calcular índice de frame desde elapsed_time
        # fps se estima en 25 (valor razonable si no hay metadata)
        _FPS = 25.0
        frame_idx = int((elapsed_time / 1000.0) * speed * _FPS)

        return sample_image_region(
            image_path=source_path,
            x=x, y=y,
            width=width, height=height,
            output_shape=(1, LEDS_PER_BAR, 3),
            fit_mode=fit_mode,
            frame_idx=frame_idx,
        )


PLUGIN_EFFECTS = {
    1010: PixelMapEffect(),
}
