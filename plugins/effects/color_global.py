"""
color_global.py — Efectos GLOBALES 2D (cross-bar) que aceptan color (r,g,b).

A diferencia del catálogo built-in de globales (radial/chase/gradientes/arcoíris),
que son multicolor y no aceptan color, estos producen patrones que recorren/abarcan
las 10 barras con SOLO el color que les pasas → encajan en una paleta (blanco/rosa/
morado). Todos son ALL_BARS → devuelven (NUM_BARS, LEDS_PER_BAR, 3) y están CENTRADOS
en el centro real del array (bar 4.5, entre bar_4 y bar_5).

IDs: 1030 chase-comet · 1031 ola 2D · 1032 radial desde centro · 1033 sweep.
"""
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import Effect, EffectScope, NUM_BARS, LEDS_PER_BAR

_TWO_PI = 2.0 * np.pi
_BARS = np.arange(NUM_BARS, dtype=np.float32).reshape(NUM_BARS, 1)        # (10,1)
_LEDS = np.arange(LEDS_PER_BAR, dtype=np.float32).reshape(1, LEDS_PER_BAR)  # (1,93)
_CENTER = (NUM_BARS - 1) / 2.0                                            # 4.5 (centrado real)

_RGB = {
    "r": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Rojo"},
    "g": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Verde"},
    "b": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Azul"},
}


def _rgb(params):
    return (max(0, min(255, int(params.get("r", 255)))),
            max(0, min(255, int(params.get("g", 255)))),
            max(0, min(255, int(params.get("b", 255)))))


def _colorize(bright: np.ndarray, r: int, g: int, b: int) -> np.ndarray:
    """bright (10,93) en [0,1] → (10,93,3) uint8 con el color dado."""
    out = np.empty((NUM_BARS, LEDS_PER_BAR, 3), dtype=np.uint8)
    bright = np.clip(bright, 0.0, 1.0)
    out[..., 0] = (bright * r).astype(np.uint8)
    out[..., 1] = (bright * g).astype(np.uint8)
    out[..., 2] = (bright * b).astype(np.uint8)
    return out


class ColorChaseBarsEffect(Effect):
    """Cometa de color que recorre las 10 barras (loop o rebote), con cola suave."""
    name = "color_chase_bars"
    family = "global2d"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    description = "Cometa(s) de color recorriendo las barras (simétrico por defecto)"
    PARAM_SCHEMA = {
        **_RGB,
        "speed": {"type": "float", "min": 0.2, "max": 8.0, "step": 0.1, "default": 2.5, "label": "Velocidad", "unit": "barras/s"},
        "width": {"type": "float", "min": 0.4, "max": 6.0, "step": 0.1, "default": 2.2, "label": "Ancho", "unit": "barras"},
        "min_brightness": {"type": "float", "min": 0.0, "max": 0.6, "step": 0.05, "default": 0.15, "label": "Brillo mínimo"},
        "symmetric": {"type": "bool", "default": True, "label": "Simétrico (desde el centro)"},
        "mode":  {"type": "enum", "options": ["loop", "bounce"], "default": "bounce", "label": "Modo (si no simétrico)"},
    }

    def render(self, elapsed_time, bars_state, audio_context, **params):
        t = elapsed_time / 1000.0
        r, g, b = _rgb(params)
        speed = max(0.2, float(params.get("speed", 2.5)))
        width = max(0.4, float(params.get("width", 2.2)))
        min_b = max(0.0, min(0.6, float(params.get("min_brightness", 0.15))))
        symmetric = bool(params.get("symmetric", True))
        mode = str(params.get("mode", "bounce"))
        phase = t * speed
        if symmetric:
            # Dos cometas espejo que SALEN del centro hacia ambos extremos y vuelven
            # → siempre equilibrado en las 10 barras.
            offset = abs((phase % (2.0 * _CENTER)) - _CENTER)   # 0..4.5..0
            d1 = _BARS - (_CENTER + offset)
            d2 = _BARS - (_CENTER - offset)
            head = np.maximum(np.exp(-(d1 * d1) / (2.0 * width * width)),
                              np.exp(-(d2 * d2) / (2.0 * width * width)))
        else:
            span = NUM_BARS - 1
            pos = (span - abs((phase % (2 * span)) - span)) if mode == "bounce" else (phase % NUM_BARS)
            d = _BARS - pos
            head = np.exp(-(d * d) / (2.0 * width * width))
        bar_bright = min_b + (1.0 - min_b) * head
        bright = np.broadcast_to(bar_bright, (NUM_BARS, LEDS_PER_BAR))
        return _colorize(bright, r, g, b)


class ColorWaveBarsEffect(Effect):
    """Ola 2D de color que viaja por las barras y a lo largo de los LEDs."""
    name = "color_wave_bars"
    family = "global2d"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    description = "Ola de color 2D (cross-bar + cross-LED)"
    PARAM_SCHEMA = {
        **_RGB,
        "speed":   {"type": "float", "min": 0.2, "max": 8.0,  "step": 0.1, "default": 2.0, "label": "Velocidad"},
        "bar_k":   {"type": "float", "min": 0.0, "max": 2.0,  "step": 0.05, "default": 0.6, "label": "Onda entre barras"},
        "led_k":   {"type": "float", "min": 0.0, "max": 0.3,  "step": 0.01, "default": 0.05, "label": "Onda en LEDs"},
        "min_brightness": {"type": "float", "min": 0.0, "max": 0.6, "step": 0.05, "default": 0.12, "label": "Brillo mínimo"},
    }

    def render(self, elapsed_time, bars_state, audio_context, **params):
        t = elapsed_time / 1000.0
        r, g, b = _rgb(params)
        speed = max(0.2, float(params.get("speed", 2.0)))
        bar_k = float(params.get("bar_k", 0.6))
        led_k = float(params.get("led_k", 0.05))
        min_b = max(0.0, min(0.6, float(params.get("min_brightness", 0.12))))
        # Onda simétrica respecto al centro real (|bar - 4.5|) → centrada.
        phase = t * speed * _TWO_PI
        val = 0.5 + 0.5 * np.sin(phase - np.abs(_BARS - _CENTER) * bar_k - _LEDS * led_k)
        bright = min_b + (1.0 - min_b) * val
        return _colorize(bright, r, g, b)


class ColorRadialEffect(Effect):
    """Anillo de color que se expande desde el centro del array hacia los extremos."""
    name = "color_radial"
    family = "global2d"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    description = "Anillo de color expandiéndose desde el centro (centrado)"
    PARAM_SCHEMA = {
        **_RGB,
        "speed": {"type": "float", "min": 0.2, "max": 6.0, "step": 0.1, "default": 1.6, "label": "Velocidad"},
        "width": {"type": "float", "min": 0.4, "max": 3.0, "step": 0.1, "default": 0.9, "label": "Grosor anillo"},
    }

    def render(self, elapsed_time, bars_state, audio_context, **params):
        t = elapsed_time / 1000.0
        r, g, b = _rgb(params)
        speed = max(0.2, float(params.get("speed", 1.6)))
        width = max(0.4, float(params.get("width", 0.9)))
        d = np.abs(_BARS - _CENTER)                 # distancia al centro real (0..4.5)
        rad = (t * speed) % (_CENTER + width)        # radio del anillo, cíclico
        ring = np.exp(-((d - rad) ** 2) / (2.0 * width * width))
        bright = np.broadcast_to(ring, (NUM_BARS, LEDS_PER_BAR))
        return _colorize(bright, r, g, b)


class ColorSweepEffect(Effect):
    """Bloque de color que barre de un extremo a otro (wipe) con borde suave."""
    name = "color_sweep"
    family = "global2d"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    description = "Barrido (wipe) de color de lado a lado"
    PARAM_SCHEMA = {
        **_RGB,
        "speed": {"type": "float", "min": 0.2, "max": 6.0, "step": 0.1, "default": 2.0, "label": "Velocidad"},
        "edge":  {"type": "float", "min": 0.4, "max": 3.0, "step": 0.1, "default": 1.2, "label": "Suavidad borde", "unit": "barras"},
        "min_brightness": {"type": "float", "min": 0.0, "max": 0.6, "step": 0.05, "default": 0.12, "label": "Brillo mínimo"},
        "symmetric": {"type": "bool", "default": True, "label": "Simétrico (desde el centro)"},
    }

    def render(self, elapsed_time, bars_state, audio_context, **params):
        t = elapsed_time / 1000.0
        r, g, b = _rgb(params)
        speed = max(0.2, float(params.get("speed", 2.0)))
        edge = max(0.4, float(params.get("edge", 1.2)))
        min_b = max(0.0, min(0.6, float(params.get("min_brightness", 0.12))))
        symmetric = bool(params.get("symmetric", True))
        phase = t * speed
        if symmetric:
            # Bloque que CRECE desde el centro hacia los extremos y se contrae
            # (llenado simétrico), con borde suave → equilibrado en las 10 barras.
            maxr = _CENTER + edge
            m = phase % (2.0 * maxr)
            radius = m if m <= maxr else (2.0 * maxr - m)      # 0..maxr..0
            d = np.abs(_BARS - _CENTER)
            fill = np.clip(1.0 - (d - radius) / edge, 0.0, 1.0)
        else:
            span = NUM_BARS - 1
            pos = span - abs((phase % (2 * span)) - span)
            d = np.abs(_BARS - pos)
            fill = np.clip(1.0 - d / (edge * 2.5), 0.0, 1.0)
        bar_bright = min_b + (1.0 - min_b) * fill
        bright = np.broadcast_to(bar_bright, (NUM_BARS, LEDS_PER_BAR))
        return _colorize(bright, r, g, b)


PLUGIN_EFFECTS = {
    1030: ColorChaseBarsEffect(),
    1031: ColorWaveBarsEffect(),
    1032: ColorRadialEffect(),
    1033: ColorSweepEffect(),
}
