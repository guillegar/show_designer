"""
color_async.py — Efectos GLOBALES 2D (cross-bar) ASIMÉTRICOS que aceptan color (r,g,b).

Complementan a `color_global.py` (1030-1033), que están CENTRADOS en bar 4.5 y son
simétricos/equilibrados. Para una estética techno-minimal "asimétrica con barridos" hace
falta movimiento que NO nazca del centro: barridos de una sola dirección y pulsos que
emanan de un lado. Eso es lo que aportan estos dos:

IDs: 1034 cometa direccional (barrido de un solo sentido, con cola) · 1035 radial off-center.

Mismo contrato que color_global: ALL_BARS → (NUM_BARS, LEDS_PER_BAR, 3) uint8, color por params.
"""
import numpy as np
from typing import Dict, Any

from src.core.effects_engine import Effect, EffectScope, NUM_BARS, LEDS_PER_BAR

_BARS = np.arange(NUM_BARS, dtype=np.float32).reshape(NUM_BARS, 1)          # (10,1)
_LEDS = np.arange(LEDS_PER_BAR, dtype=np.float32).reshape(1, LEDS_PER_BAR)  # (1,93)

_RGB = {
    "r": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Rojo"},
    "g": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Verde"},
    "b": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Azul"},
}


def _rgb(params):
    return (max(0, min(255, int(params.get("r", 255)))),
            max(0, min(255, int(params.get("g", 255)))),
            max(0, min(255, int(params.get("b", 255)))))


def _pump(audio_context, source="rms", gamma=2.0):
    """Escalar 0..1 del audio (norm) con curva 'punchy' → bombeo con el kick.
    'rms' = buen rango dinámico (cuerpo); 'flux' = más transitorio (golpe seco)."""
    n = (audio_context or {}).get("norm", {}) or {}
    v = float(n.get(source, 0.0))
    v = max(0.0, min(1.0, v))
    return v ** max(0.1, gamma)


def _colorize(bright: np.ndarray, r: int, g: int, b: int) -> np.ndarray:
    """bright (10,93) en [0,1] → (10,93,3) uint8 con el color dado."""
    out = np.empty((NUM_BARS, LEDS_PER_BAR, 3), dtype=np.uint8)
    bright = np.clip(bright, 0.0, 1.0)
    out[..., 0] = (bright * r).astype(np.uint8)
    out[..., 1] = (bright * g).astype(np.uint8)
    out[..., 2] = (bright * b).astype(np.uint8)
    return out


class DirectionalCometEffect(Effect):
    """Cometa que barre las 10 barras en UN SOLO sentido (izq→der o der→izq), entra por
    un borde y sale por el otro, con frente nítido y cola que se desvanece. Es el barrido
    asimétrico base: NUNCA nace del centro, siempre cruza de lado a lado."""
    name = "color_directional_comet"
    family = "global2d"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    description = "Barrido/cometa de un solo sentido con cola (asimétrico)"
    PARAM_SCHEMA = {
        **_RGB,
        "speed":     {"type": "float", "min": 0.2, "max": 8.0, "step": 0.1, "default": 1.6, "label": "Velocidad", "unit": "barras/s"},
        "width":     {"type": "float", "min": 0.3, "max": 4.0, "step": 0.1, "default": 1.1, "label": "Ancho frente", "unit": "barras"},
        "tail":      {"type": "float", "min": 0.3, "max": 8.0, "step": 0.1, "default": 3.0, "label": "Cola", "unit": "barras"},
        "direction": {"type": "enum", "options": ["ltr", "rtl"], "default": "ltr", "label": "Sentido"},
        "min_brightness": {"type": "float", "min": 0.0, "max": 0.6, "step": 0.05, "default": 0.0, "label": "Brillo mínimo"},
        "pump": {"type": "float", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.0, "label": "Bombeo audio (kick)"},
        "pump_source": {"type": "enum", "options": ["rms", "flux"], "default": "rms", "label": "Fuente bombeo"},
    }

    def render(self, elapsed_time, bars_state, audio_context, **params):
        t = elapsed_time / 1000.0
        r, g, b = _rgb(params)
        speed = max(0.2, float(params.get("speed", 1.6)))
        width = max(0.3, float(params.get("width", 1.1)))
        tail = max(0.3, float(params.get("tail", 3.0)))
        min_b = max(0.0, min(0.6, float(params.get("min_brightness", 0.0))))
        pump = max(0.0, min(1.0, float(params.get("pump", 0.0))))
        s = -1.0 if str(params.get("direction", "ltr")) == "rtl" else 1.0

        # El cabezal recorre desde -tail (fuera, por el borde de entrada) hasta
        # NUM_BARS-1+width (fuera, por el de salida) y vuelve a entrar → un barrido
        # limpio de un solo sentido con la cola entrando antes que el frente.
        cycle = (NUM_BARS - 1) + tail + width
        travel = (t * speed) % cycle
        head = (travel - tail) if s > 0 else ((NUM_BARS - 1) - (travel - tail))

        proj = s * (_BARS - head)                 # >0 = por delante del frente; <0 = cola
        front = np.exp(-(np.maximum(proj, 0.0) ** 2) / (2.0 * width * width))
        trail = np.exp(np.minimum(proj, 0.0) / tail)   # proj<0 → decae con la distancia
        glow = np.where(proj >= 0.0, front, trail)

        bar_bright = min_b + (1.0 - min_b) * glow
        if pump > 0.0:
            # Bombea la intensidad del barrido con el kick (mezcla 1-pump..pump).
            p = _pump(audio_context, str(params.get("pump_source", "rms")))
            bar_bright = bar_bright * ((1.0 - pump) + pump * p)
        bright = np.broadcast_to(bar_bright, (NUM_BARS, LEDS_PER_BAR))
        return _colorize(bright, r, g, b)


class AudioPumpEffect(Effect):
    """Bombeo audio-reactivo: TODO el rig late con el kick (norm.rms/flux), con un
    'tilt' opcional que inclina el brillo hacia un lado (asimetría). Sin movimiento
    espacial: es el PULSO rítmico puro, base de las secciones con groove."""
    name = "color_audio_pump"
    family = "global2d"
    duration_ms = 1000
    scope = EffectScope.ALL_BARS
    description = "Pulso audio-reactivo de todo el rig (late con el kick)"
    PARAM_SCHEMA = {
        **_RGB,
        "gamma":  {"type": "float", "min": 0.5, "max": 4.0, "step": 0.1, "default": 2.0, "label": "Dureza del golpe"},
        "tilt":   {"type": "float", "min": -1.0, "max": 1.0, "step": 0.1, "default": 0.0, "label": "Inclinación (asimetría)"},
        "min_brightness": {"type": "float", "min": 0.0, "max": 0.6, "step": 0.05, "default": 0.04, "label": "Brillo mínimo"},
        "pump_source": {"type": "enum", "options": ["rms", "flux"], "default": "rms", "label": "Fuente"},
    }

    def render(self, elapsed_time, bars_state, audio_context, **params):
        r, g, b = _rgb(params)
        gamma = max(0.5, float(params.get("gamma", 2.0)))
        tilt = max(-1.0, min(1.0, float(params.get("tilt", 0.0))))
        min_b = max(0.0, min(0.6, float(params.get("min_brightness", 0.04))))
        p = _pump(audio_context, str(params.get("pump_source", "rms")), gamma)
        level = min_b + (1.0 - min_b) * p
        # Inclinación lateral: rampa de peso por barra (asimétrica) centrada en 1.0.
        ramp = (_BARS / float(NUM_BARS - 1)) - 0.5      # -0.5..+0.5
        weight = np.clip(1.0 + tilt * 2.0 * ramp, 0.0, 1.0)
        bar_bright = level * weight
        bright = np.broadcast_to(bar_bright, (NUM_BARS, LEDS_PER_BAR))
        return _colorize(bright, r, g, b)


class OffCenterRadialEffect(Effect):
    """Anillo de color que se expande desde un bar de ORIGEN arbitrario (no el centro),
    de modo que los pulsos nacen de un lado del array → radial asimétrico."""
    name = "color_offcenter_radial"
    family = "global2d"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    description = "Anillo expandiéndose desde un origen lateral (asimétrico)"
    PARAM_SCHEMA = {
        **_RGB,
        "speed":  {"type": "float", "min": 0.2, "max": 6.0, "step": 0.1, "default": 1.6, "label": "Velocidad"},
        "width":  {"type": "float", "min": 0.4, "max": 3.0, "step": 0.1, "default": 0.9, "label": "Grosor anillo"},
        "origin": {"type": "int", "min": 0, "max": 9, "step": 1, "default": 0, "label": "Barra de origen"},
        "min_brightness": {"type": "float", "min": 0.0, "max": 0.6, "step": 0.05, "default": 0.0, "label": "Brillo mínimo"},
    }

    def render(self, elapsed_time, bars_state, audio_context, **params):
        t = elapsed_time / 1000.0
        r, g, b = _rgb(params)
        speed = max(0.2, float(params.get("speed", 1.6)))
        width = max(0.4, float(params.get("width", 0.9)))
        origin = max(0, min(NUM_BARS - 1, int(params.get("origin", 0))))
        min_b = max(0.0, min(0.6, float(params.get("min_brightness", 0.0))))

        d = np.abs(_BARS - float(origin))            # distancia al origen lateral
        maxd = float(max(origin, NUM_BARS - 1 - origin))
        rad = (t * speed) % (maxd + width)            # radio del anillo, cíclico
        ring = np.exp(-((d - rad) ** 2) / (2.0 * width * width))
        bar_bright = min_b + (1.0 - min_b) * ring
        bright = np.broadcast_to(bar_bright, (NUM_BARS, LEDS_PER_BAR))
        return _colorize(bright, r, g, b)


PLUGIN_EFFECTS = {
    1034: DirectionalCometEffect(),
    1035: OffCenterRadialEffect(),
    1036: AudioPumpEffect(),
}
