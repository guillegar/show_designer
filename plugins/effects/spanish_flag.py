"""
spanish_flag.py — Efecto de bandera española ondeante

Renderiza los colores de la bandera española (rojo-amarillo-rojo) con una
animación ondeante que simula el ondeo de la bandera al viento.

IDs asignados: 1002 (SpanishFlagWave)
"""
import math
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import (
    Effect, EffectScope, EffectGeometry, EffectSymmetry,
    NUM_BARS, LEDS_PER_BAR,
)


class SpanishFlagWaveEffect(Effect):
    """
    Bandera española ondeante.

    3 secciones horizontales (rojo-amarillo-rojo) con animación sinusoidal
    que simula el ondeo de la bandera.
    """
    name        = "spanish_flag_wave"
    family      = "bandera"
    duration_ms = 2000
    scope       = EffectScope.ALL_BARS
    geometry    = EffectGeometry.GEOMETRY_3D
    symmetry    = EffectSymmetry.SYMMETRIC
    description = "Bandera española ondeante con animación sinusoidal"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        n_bars = bars_state.shape[0]
        n_leds = bars_state.shape[1]
        out    = np.zeros_like(bars_state)
        t      = elapsed_time / 1000.0  # segundos

        # Parámetros configurables
        wave_speed = float(params.get('wave_speed', 2.0))  # ciclos por segundo
        wave_amplitude = float(params.get('wave_amplitude', 0.15))  # amplitud relativa

        # Colores de la bandera española
        # Rojo: #C60B1E (RGB: 198, 11, 30)
        # Amarillo: #FFC400 (RGB: 255, 196, 0)
        RED = (198, 11, 30)
        YELLOW = (255, 196, 0)

        # Dimensiones de las secciones de la bandera
        # La sección amarilla es el doble de las rojas
        section_height = n_leds / 4  # cada sección ocupa n_leds/4

        for b in range(n_bars):
            for led in range(n_leds):
                # Determinar qué sección está este LED (rojo-amarillo-rojo)
                # 0..n_leds/4 = Rojo (superior)
                # n_leds/4..3*n_leds/4 = Amarillo (central, doble)
                # 3*n_leds/4..n_leds = Rojo (inferior)

                if led < section_height:
                    # Sección roja superior
                    base_color = RED
                elif led < 3 * section_height:
                    # Sección amarilla (central)
                    base_color = YELLOW
                else:
                    # Sección roja inferior
                    base_color = RED

                # Calcular la onda: modula la intensidad según la posición en el tiempo
                # La onda recorre de izquierda a derecha (barra 0 a barra n_bars-1)
                # Cada LED también contribuye a la onda (posición vertical)

                wave_phase = 2 * math.pi * wave_speed * t
                bar_offset = (b / max(1, n_bars - 1)) * 2 * math.pi if n_bars > 1 else 0
                led_offset = (led / n_leds) * 2 * math.pi

                # Onda sinusoidal que recorre horizontalmente y verticalmente
                wave_value = math.sin(wave_phase + bar_offset + led_offset)

                # Convertir la onda a rango [0, 1]
                # wave_value oscila entre -1 y 1, lo mapeamos a [1-amplitude, 1]
                brightness = 1.0 - wave_amplitude + (1.0 + wave_value) * (wave_amplitude / 2.0)
                brightness = max(0.0, min(1.0, brightness))

                # Aplicar el color con la modulación de amplitud
                out[b, led, 0] = int(base_color[0] * brightness)
                out[b, led, 1] = int(base_color[1] * brightness)
                out[b, led, 2] = int(base_color[2] * brightness)

        return out


class SpanishFlagStaticEffect(Effect):
    """
    Bandera española estática (sin onda).

    3 secciones horizontales (rojo-amarillo-rojo) fijas, para comparación
    o cuando no se quiere animación.
    """
    name        = "spanish_flag_static"
    family      = "bandera"
    duration_ms = 2000
    scope       = EffectScope.ALL_BARS
    geometry    = EffectGeometry.GEOMETRY_3D
    symmetry    = EffectSymmetry.SYMMETRIC
    description = "Bandera española estática"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        n_bars = bars_state.shape[0]
        n_leds = bars_state.shape[1]
        out    = np.zeros_like(bars_state)

        # Colores de la bandera española
        RED = (198, 11, 30)      # Rojo bandera
        YELLOW = (255, 196, 0)   # Amarillo bandera

        # Dimensiones de las secciones
        section_height = n_leds / 4

        for b in range(n_bars):
            for led in range(n_leds):
                if led < section_height:
                    color = RED
                elif led < 3 * section_height:
                    color = YELLOW
                else:
                    color = RED

                out[b, led, 0] = color[0]
                out[b, led, 1] = color[1]
                out[b, led, 2] = color[2]

        return out


# ─────────────────────────────────────────────────────────────────────────────
# Registro de efectos del plugin
# IDs en rango 1000+ para no colisionar con efectos base (0-999)
# ─────────────────────────────────────────────────────────────────────────────

PLUGIN_EFFECTS = {
    1002: SpanishFlagWaveEffect(),
    1003: SpanishFlagStaticEffect(),
}
