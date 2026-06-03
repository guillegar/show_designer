"""
example_plugin.py — Plugin de ejemplo para Show Designer Pro

Demuestra como crear efectos pixel custom sin tocar effects_engine.py.
Basta con subclasear Effect y definir render(). El sistema los carga
automaticamente al arrancar si este archivo esta en plugins/effects/.

Para activar: simplemente guarda este archivo. La app lo detecta en
el proximo arranque (o tras reiniciar el ShowEngine).

IDs asignados en PLUGIN_EFFECTS (si se define); si no, el loader
los asigna automaticamente empezando desde 1000.
"""
import math
import numpy as np
from typing import Dict, Any

# Importar base y helpers desde effects_engine
from src.core.effects_engine import (
    Effect, EffectScope, EffectGeometry, EffectSymmetry,
    NUM_BARS, LEDS_PER_BAR,
)


# ─────────────────────────────────────────────────────────────────────────────
# Efecto 1: Meteoros (lluvia de puntos luminosos que caen por las barras)
# ─────────────────────────────────────────────────────────────────────────────

class MeteorShowerEffect(Effect):
    """
    Meteoros de colores cayendo por las barras de LEDs.
    Cada meteoro deja una estela que se desvanece.
    """
    name        = "meteor_shower"
    family      = "plugin_demo"
    duration_ms = 4000
    scope       = EffectScope.ALL_BARS
    geometry    = EffectGeometry.GEOMETRY_3D
    symmetry    = EffectSymmetry.ASYMMETRIC
    description = "Meteoros de colores cayendo por las barras (plugin ejemplo)"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        n_bars    = bars_state.shape[0]
        n_leds    = bars_state.shape[1]
        out       = np.zeros_like(bars_state)
        t         = elapsed_time / 1000.0       # segundos
        speed     = params.get('speed', 1.5)    # barras/seg
        n_meteors = int(params.get('n_meteors', 4))
        tail_len  = int(params.get('tail_len', 12))

        # Colores por meteoro (fijos pero variados)
        COLORS = [
            (255, 120,  30),   # naranja
            ( 80, 200, 255),   # cyan
            (200,  60, 255),   # violeta
            (100, 255, 100),   # verde
        ]

        energy = float(audio_context.get('energy', 0.5)) if audio_context else 0.5

        for m in range(n_meteors):
            # Posicion del meteoro: avanza de arriba a abajo en la barra
            phase_offset = m / n_meteors
            cycle_t = (t * speed + phase_offset) % 1.0
            head_pos = cycle_t * n_leds          # posicion LED cabeza

            # Barra donde aparece este meteoro (se distribuye)
            bar_idx = (m + int(t * 0.3 * speed)) % n_bars

            col = COLORS[m % len(COLORS)]

            # Estela
            for tail in range(tail_len):
                led = int(head_pos) - tail
                if 0 <= led < n_leds:
                    fade = (1.0 - tail / tail_len) ** 2
                    # Modular por energy
                    brightness = fade * (0.4 + 0.6 * energy)
                    out[bar_idx, led, 0] = min(255, int(col[0] * brightness))
                    out[bar_idx, led, 1] = min(255, int(col[1] * brightness))
                    out[bar_idx, led, 2] = min(255, int(col[2] * brightness))

        return out


# ─────────────────────────────────────────────────────────────────────────────
# Efecto 2: Corazon latente (pulso que expande desde el centro)
# ─────────────────────────────────────────────────────────────────────────────

class HeartbeatEffect(Effect):
    """
    Pulso tipo latido que expande desde el centro de cada barra.
    Reacciona a la energia del audio (energy -> brillo).
    """
    name        = "heartbeat"
    family      = "plugin_demo"
    duration_ms = 2000
    scope       = EffectScope.ALL_BARS
    geometry    = EffectGeometry.GEOMETRY_3D
    symmetry    = EffectSymmetry.SYMMETRIC
    description = "Pulso latido que expande desde el centro (plugin ejemplo)"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        n_bars = bars_state.shape[0]
        n_leds = bars_state.shape[1]
        out    = np.zeros_like(bars_state)
        t      = elapsed_time / 1000.0

        bpm        = float(params.get('bpm', 120.0))
        hue_r      = int(params.get('hue_r', 255))
        hue_g      = int(params.get('hue_g', 30))
        hue_b      = int(params.get('hue_b', 60))
        pulse_w    = float(params.get('pulse_width', 0.3))

        energy = float(audio_context.get('energy', 0.5)) if audio_context else 0.5

        # Dos pulsos por beat (sistole + diastole)
        beat_t = (t * bpm / 60.0) % 1.0
        # Pulso 1: 0..0.15, Pulso 2: 0.25..0.40
        def pulse_value(bt):
            p1 = max(0.0, 1.0 - bt / 0.15) if bt < 0.15 else 0.0
            p2 = max(0.0, 1.0 - (bt - 0.25) / 0.12) if 0.25 <= bt < 0.40 else 0.0
            return max(p1, p2)

        amp = pulse_value(beat_t) * (0.5 + 0.5 * energy)

        center = n_leds // 2
        for b in range(n_bars):
            for led in range(n_leds):
                dist = abs(led - center) / center   # 0.0 en centro, 1.0 en extremo
                brightness = amp * max(0.0, 1.0 - dist / pulse_w)
                out[b, led, 0] = min(255, int(hue_r * brightness))
                out[b, led, 1] = min(255, int(hue_g * brightness))
                out[b, led, 2] = min(255, int(hue_b * brightness))

        return out


# ─────────────────────────────────────────────────────────────────────────────
# Registro de efectos del plugin
# IDs en rango 1000+ para no colisionar con efectos base (0-999)
# ─────────────────────────────────────────────────────────────────────────────

PLUGIN_EFFECTS = {
    1000: MeteorShowerEffect(),
    1001: HeartbeatEffect(),
}
