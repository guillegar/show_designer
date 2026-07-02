"""
channel_effects.py — Catálogo de ChannelEffect para fixtures no-LED.

v1.7 Fase 6: 24 efectos en 5 categorías (position/color/intensity/optical/strobe).
Cada efecto es puro: recibe (t, audio_context, params) y devuelve {ch_name: 0-255}.
Sin Qt, sin red, sin rig — solo matemáticas.

Uso:
    lib = ChannelEffectLibrary()
    eff = lib.get('pos_circle')
    vals = eff.render(t=2.5, audio_context=ctx, params={'speed': 0.5})
    # → {'pan': 142, 'tilt': 98}
"""
from __future__ import annotations

import colorsys
import math
import random

CATEGORIES = ('position', 'color', 'intensity', 'optical', 'strobe')


# ════════════════════════════════════════════════════════════════
# Base
# ════════════════════════════════════════════════════════════════

class ChannelEffect:
    effect_id: str = ""
    name: str = ""
    category: str = ""
    required_channels: list[str] = []
    optional_channels: list[str] = []
    default_params: dict = {}

    def render(self, t: float, audio_context: dict | None,
               params: dict | None) -> dict[str, int]:
        """
        t: segundos desde el inicio del clip.
        audio_context: dict con rms, flux, etc. Puede ser None.
        params: parámetros del clip (sobreescriben default_params).
        Returns: {channel_name: 0-255}
        """
        raise NotImplementedError

    def _p(self, params: dict | None, key: str, default=None):
        if params and key in params:
            return params[key]
        return self.default_params.get(key, default)

    def _rms(self, audio_context: dict | None) -> float:
        if audio_context is None:
            return 0.0
        return float(audio_context.get('rms', 0.0))

    @staticmethod
    def _clamp(v: float) -> int:
        return max(0, min(255, int(round(v))))

    def describe(self) -> dict:
        return {
            'effect_id':        self.effect_id,
            'name':             self.name,
            'category':         self.category,
            'required_channels': list(self.required_channels),
            'optional_channels': list(self.optional_channels),
            'default_params':   dict(self.default_params),
        }


# ════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════

def _hsv_to_rgb(h: float, s: float, v: float):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)),
                                   max(0.0, min(1.0, v)))
    return int(r * 255), int(g * 255), int(b * 255)


def _hex_to_rgb(color: str):
    c = str(color).lstrip('#')
    if len(c) == 6:
        try:
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        except ValueError:
            pass
    return 255, 255, 255


# ════════════════════════════════════════════════════════════════
# POSICIÓN (pan / tilt)
# ════════════════════════════════════════════════════════════════

class ChanCircle(ChannelEffect):
    """Pan/tilt trazan un círculo continuo."""
    effect_id = 'pos_circle'
    name = 'Círculo'
    category = 'position'
    required_channels = ['pan', 'tilt']
    default_params = {
        'speed': 0.3, 'radius': 0.25, 'center_pan': 0.5, 'center_tilt': 0.5,
    }

    def render(self, t, audio_context, params):
        spd = self._p(params, 'speed', 0.3)
        rad = self._p(params, 'radius', 0.25)
        cp  = self._p(params, 'center_pan', 0.5)
        ct  = self._p(params, 'center_tilt', 0.5)
        a   = 2 * math.pi * spd * t
        return {
            'pan':  self._clamp((cp + rad * math.sin(a)) * 255),
            'tilt': self._clamp((ct + rad * math.cos(a)) * 255),
        }


class ChanFigure8(ChannelEffect):
    """Pan/tilt trazan un ocho (Lissajous 1:2)."""
    effect_id = 'pos_figure8'
    name = 'Ocho'
    category = 'position'
    required_channels = ['pan', 'tilt']
    default_params = {
        'speed': 0.2, 'radius': 0.30, 'center_pan': 0.5, 'center_tilt': 0.5,
    }

    def render(self, t, audio_context, params):
        spd = self._p(params, 'speed', 0.2)
        rad = self._p(params, 'radius', 0.30)
        cp  = self._p(params, 'center_pan', 0.5)
        ct  = self._p(params, 'center_tilt', 0.5)
        a   = 2 * math.pi * spd * t
        return {
            'pan':  self._clamp((cp + rad * math.sin(a)) * 255),
            'tilt': self._clamp((ct + rad * math.sin(2 * a) / 2) * 255),
        }


class ChanSway(ChannelEffect):
    """Balanceo lateral de pan, tilt estático."""
    effect_id = 'pos_sway'
    name = 'Balanceo'
    category = 'position'
    required_channels = ['pan']
    optional_channels = ['tilt']
    default_params = {
        'speed': 0.5, 'width': 0.40, 'center_pan': 0.5, 'center_tilt': 0.5,
    }

    def render(self, t, audio_context, params):
        spd = self._p(params, 'speed', 0.5)
        w   = self._p(params, 'width', 0.40)
        cp  = self._p(params, 'center_pan', 0.5)
        ct  = self._p(params, 'center_tilt', 0.5)
        pan = cp + (w / 2) * math.sin(2 * math.pi * spd * t)
        return {
            'pan':  self._clamp(pan * 255),
            'tilt': self._clamp(ct  * 255),
        }


class ChanBeatSnap(ChannelEffect):
    """Salta a posición aleatoria en cada beat (determinista)."""
    effect_id = 'pos_beat_snap'
    name = 'Beat Snap'
    category = 'position'
    required_channels = ['pan', 'tilt']
    default_params = {
        'bpm': 120.0, 'beat_div': 1.0,
        'center_pan': 0.5, 'center_tilt': 0.5, 'range': 0.35,
    }

    def render(self, t, audio_context, params):
        bpm   = float(self._p(params, 'bpm', 120.0))
        div   = max(0.25, float(self._p(params, 'beat_div', 1.0)))
        rng   = float(self._p(params, 'range', 0.35))
        cp    = float(self._p(params, 'center_pan', 0.5))
        ct    = float(self._p(params, 'center_tilt', 0.5))
        beat_dur = 60.0 / bpm * div
        slot  = int(t / beat_dur) if beat_dur > 0 else 0
        rnd   = random.Random(slot)
        pan   = cp + (rnd.random() * 2 - 1) * rng
        tilt  = ct + (rnd.random() * 2 - 1) * rng * 0.5
        return {
            'pan':  self._clamp(pan  * 255),
            'tilt': self._clamp(tilt * 255),
        }


class ChanPanSweep(ChannelEffect):
    """Barrido de pan de extremo a extremo y vuelta."""
    effect_id = 'pos_pan_sweep'
    name = 'Barrido Pan'
    category = 'position'
    required_channels = ['pan']
    optional_channels = ['tilt']
    default_params = {
        'speed': 0.15, 'from_pan': 0.10, 'to_pan': 0.90, 'center_tilt': 0.5,
    }

    def render(self, t, audio_context, params):
        spd  = self._p(params, 'speed', 0.15)
        fp   = self._p(params, 'from_pan', 0.10)
        tp   = self._p(params, 'to_pan', 0.90)
        ct   = self._p(params, 'center_tilt', 0.5)
        frac = (math.sin(2 * math.pi * spd * t) + 1) / 2
        pan  = fp + (tp - fp) * frac
        return {
            'pan':  self._clamp(pan * 255),
            'tilt': self._clamp(ct  * 255),
        }


# ════════════════════════════════════════════════════════════════
# COLOR (r, g, b)
# ════════════════════════════════════════════════════════════════

class ChanRainbow(ChannelEffect):
    """Ciclo de colores HSV continuo."""
    effect_id = 'col_rainbow'
    name = 'Arcoíris'
    category = 'color'
    required_channels = ['r', 'g', 'b']
    default_params = {'speed': 0.2, 'saturation': 1.0, 'value': 1.0}

    def render(self, t, audio_context, params):
        spd = self._p(params, 'speed', 0.2)
        sat = self._p(params, 'saturation', 1.0)
        val = self._p(params, 'value', 1.0)
        r, g, b = _hsv_to_rgb(spd * t, sat, val)
        return {'r': r, 'g': g, 'b': b}


class ChanColorFade(ChannelEffect):
    """Fundido suave entre dos colores."""
    effect_id = 'col_fade'
    name = 'Fundido de Color'
    category = 'color'
    required_channels = ['r', 'g', 'b']
    default_params = {
        'speed': 0.25, 'color_a': '#ff0000', 'color_b': '#0000ff',
    }

    def render(self, t, audio_context, params):
        spd = self._p(params, 'speed', 0.25)
        ca  = self._p(params, 'color_a', '#ff0000')
        cb  = self._p(params, 'color_b', '#0000ff')
        ra, ga, ba = _hex_to_rgb(ca)
        rb, gb, bb = _hex_to_rgb(cb)
        frac = (math.sin(2 * math.pi * spd * t) + 1) / 2
        return {
            'r': self._clamp(ra + (rb - ra) * frac),
            'g': self._clamp(ga + (gb - ga) * frac),
            'b': self._clamp(ba + (bb - ba) * frac),
        }


class ChanColorFlash(ChannelEffect):
    """Flash de color cuando el RMS supera un umbral."""
    effect_id = 'col_flash'
    name = 'Flash de Color'
    category = 'color'
    required_channels = ['r', 'g', 'b']
    default_params = {
        'color': '#ffffff', 'base_color': '#000000',
        'threshold': 0.4, 'decay': 4.0,
    }

    def __init__(self):
        self._last_flash: float = -999.0

    def render(self, t, audio_context, params):
        col   = self._p(params, 'color', '#ffffff')
        base  = self._p(params, 'base_color', '#000000')
        thr   = float(self._p(params, 'threshold', 0.4))
        decay = float(self._p(params, 'decay', 4.0))
        rms   = self._rms(audio_context)
        if rms >= thr:
            self._last_flash = t
        dt  = max(0.0, t - self._last_flash)
        amp = math.exp(-decay * dt)
        rf, gf, bf = _hex_to_rgb(col)
        rb, gb, bb = _hex_to_rgb(base)
        return {
            'r': self._clamp(rb + (rf - rb) * amp),
            'g': self._clamp(gb + (gf - gb) * amp),
            'b': self._clamp(bb + (bf - bb) * amp),
        }


class ChanWarmCold(ChannelEffect):
    """Oscila entre tono cálido (ámbar) y frío (azul)."""
    effect_id = 'col_warm_cold'
    name = 'Cálido-Frío'
    category = 'color'
    required_channels = ['r', 'g', 'b']
    default_params = {'speed': 0.15}

    def render(self, t, audio_context, params):
        spd  = self._p(params, 'speed', 0.15)
        frac = (math.sin(2 * math.pi * spd * t) + 1) / 2
        # ámbar (255,100,20) ↔ azul frío (20,80,255)
        return {
            'r': self._clamp(20  + (235) * frac),
            'g': self._clamp(80  + (20)  * frac),
            'b': self._clamp(255 + (-235) * frac),
        }


class ChanColorStrobe(ChannelEffect):
    """On/off en el color elegido a frecuencia fija."""
    effect_id = 'col_strobe'
    name = 'Strobe de Color'
    category = 'color'
    required_channels = ['r', 'g', 'b']
    default_params = {'freq_hz': 8.0, 'color': '#ffffff', 'duty': 0.5}

    def render(self, t, audio_context, params):
        freq  = float(self._p(params, 'freq_hz', 8.0))
        col   = self._p(params, 'color', '#ffffff')
        duty  = float(self._p(params, 'duty', 0.5))
        rf, gf, bf = _hex_to_rgb(col)
        on = (t * freq % 1.0) < duty
        if on:
            return {'r': rf, 'g': gf, 'b': bf}
        return {'r': 0, 'g': 0, 'b': 0}


# ════════════════════════════════════════════════════════════════
# INTENSIDAD (dim)
# ════════════════════════════════════════════════════════════════

class ChanPulse(ChannelEffect):
    """Pulso de intensidad sinusoidal."""
    effect_id = 'dim_pulse'
    name = 'Pulso'
    category = 'intensity'
    required_channels = ['dim']
    default_params = {'speed': 1.0, 'min_dim': 0.0, 'max_dim': 1.0}

    def render(self, t, audio_context, params):
        spd  = self._p(params, 'speed', 1.0)
        lo   = self._p(params, 'min_dim', 0.0)
        hi   = self._p(params, 'max_dim', 1.0)
        frac = (math.sin(2 * math.pi * spd * t) + 1) / 2
        return {'dim': self._clamp((lo + (hi - lo) * frac) * 255)}


class ChanBump(ChannelEffect):
    """Intensidad modulada por RMS del audio."""
    effect_id = 'dim_bump'
    name = 'Bump Audio'
    category = 'intensity'
    required_channels = ['dim']
    default_params = {'gain': 1.5, 'base_dim': 0.1}

    def render(self, t, audio_context, params):
        gain = self._p(params, 'gain', 1.5)
        base = self._p(params, 'base_dim', 0.1)
        rms  = self._rms(audio_context)
        dim  = min(1.0, float(base) + rms * float(gain))
        return {'dim': self._clamp(dim * 255)}


class ChanFadeIn(ChannelEffect):
    """Fade in lineal desde 0 hasta target_dim."""
    effect_id = 'dim_fade_in'
    name = 'Fade In'
    category = 'intensity'
    required_channels = ['dim']
    default_params = {'fade_time': 2.0, 'target_dim': 1.0}

    def render(self, t, audio_context, params):
        fade = max(0.001, float(self._p(params, 'fade_time', 2.0)))
        tgt  = float(self._p(params, 'target_dim', 1.0))
        dim  = min(1.0, t / fade) * tgt
        return {'dim': self._clamp(dim * 255)}


class ChanBreath(ChannelEffect):
    """Respiración lenta (sin²)."""
    effect_id = 'dim_breath'
    name = 'Respiración'
    category = 'intensity'
    required_channels = ['dim']
    default_params = {'speed': 0.25, 'min_dim': 0.05, 'max_dim': 1.0}

    def render(self, t, audio_context, params):
        spd  = self._p(params, 'speed', 0.25)
        lo   = self._p(params, 'min_dim', 0.05)
        hi   = self._p(params, 'max_dim', 1.0)
        raw  = math.sin(math.pi * float(spd) * t)
        frac = raw * raw
        return {'dim': self._clamp((float(lo) + (float(hi) - float(lo)) * frac) * 255)}


class ChanDimFlash(ChannelEffect):
    """Flash con decay exponencial activado por audio."""
    effect_id = 'dim_flash'
    name = 'Flash Dim'
    category = 'intensity'
    required_channels = ['dim']
    default_params = {'threshold': 0.5, 'decay': 6.0, 'base_dim': 0.0}

    def __init__(self):
        self._last_flash: float = -999.0

    def render(self, t, audio_context, params):
        thr   = float(self._p(params, 'threshold', 0.5))
        decay = float(self._p(params, 'decay', 6.0))
        base  = float(self._p(params, 'base_dim', 0.0))
        rms   = self._rms(audio_context)
        if rms >= thr:
            self._last_flash = t
        dt  = max(0.0, t - self._last_flash)
        amp = math.exp(-decay * dt)
        dim = base + (1.0 - base) * amp
        return {'dim': self._clamp(dim * 255)}


# ════════════════════════════════════════════════════════════════
# ÓPTICA (gobo, zoom, focus, frost)
# ════════════════════════════════════════════════════════════════

class ChanGoboSpin(ChannelEffect):
    """Rotación continua de gobo."""
    effect_id = 'opt_gobo_spin'
    name = 'Gobo Spin'
    category = 'optical'
    required_channels = ['gobo_rotation']
    default_params = {'speed': 1.0}

    def render(self, t, audio_context, params):
        spd = float(self._p(params, 'speed', 1.0))
        return {'gobo_rotation': int(t * spd * 255) % 256}


class ChanGoboStep(ChannelEffect):
    """Paso por posiciones del gobo wheel a intervalos fijos."""
    effect_id = 'opt_gobo_step'
    name = 'Gobo Step'
    category = 'optical'
    required_channels = ['gobo_wheel']
    default_params = {'step_time': 1.0, 'num_steps': 8, 'start_pos': 0}

    def render(self, t, audio_context, params):
        step_t = max(0.1, float(self._p(params, 'step_time', 1.0)))
        steps  = max(1, int(self._p(params, 'num_steps', 8)))
        start  = int(self._p(params, 'start_pos', 0))
        idx    = int(t / step_t) % steps
        return {'gobo_wheel': (start + idx * (256 // steps)) % 256}


class ChanZoomPulse(ChannelEffect):
    """Zoom oscila entre narrow y wide."""
    effect_id = 'opt_zoom_pulse'
    name = 'Zoom Pulso'
    category = 'optical'
    required_channels = ['zoom']
    default_params = {'speed': 0.5, 'min_zoom': 0.10, 'max_zoom': 0.90}

    def render(self, t, audio_context, params):
        spd  = self._p(params, 'speed', 0.5)
        lo   = self._p(params, 'min_zoom', 0.10)
        hi   = self._p(params, 'max_zoom', 0.90)
        frac = (math.sin(2 * math.pi * float(spd) * t) + 1) / 2
        return {'zoom': self._clamp((float(lo) + (float(hi) - float(lo)) * frac) * 255)}


class ChanFrostPulse(ChannelEffect):
    """Difusión (frost) oscila."""
    effect_id = 'opt_frost_pulse'
    name = 'Frost Pulso'
    category = 'optical'
    required_channels = ['frost']
    default_params = {'speed': 0.3, 'depth': 0.8}

    def render(self, t, audio_context, params):
        spd   = float(self._p(params, 'speed', 0.3))
        depth = float(self._p(params, 'depth', 0.8))
        frac  = (math.sin(2 * math.pi * spd * t) + 1) / 2
        return {'frost': self._clamp(frac * depth * 255)}


# ════════════════════════════════════════════════════════════════
# STROBE (intensity, speed)
# ════════════════════════════════════════════════════════════════

class ChanStrobeSimple(ChannelEffect):
    """Strobe simple a frecuencia constante."""
    effect_id = 'str_flash'
    name = 'Strobe Simple'
    category = 'strobe'
    required_channels = ['intensity']
    optional_channels = ['speed']
    default_params = {'freq_hz': 8.0, 'duty': 0.4, 'brightness': 1.0}

    def render(self, t, audio_context, params):
        freq = float(self._p(params, 'freq_hz', 8.0))
        duty = float(self._p(params, 'duty', 0.4))
        bri  = float(self._p(params, 'brightness', 1.0))
        on   = (t * freq % 1.0) < duty
        out  = {'intensity': self._clamp(bri * 255) if on else 0}
        if self.optional_channels and 'speed' in self.optional_channels:
            out['speed'] = self._clamp(min(1.0, freq / 25.0) * 255)
        return out


class ChanStrobeRamp(ChannelEffect):
    """Strobe que acelera progresivamente."""
    effect_id = 'str_ramp'
    name = 'Strobe Ramp'
    category = 'strobe'
    required_channels = ['intensity']
    default_params = {
        'start_hz': 1.0, 'end_hz': 20.0, 'ramp_time': 4.0, 'brightness': 1.0,
    }

    def render(self, t, audio_context, params):
        start = float(self._p(params, 'start_hz', 1.0))
        end   = float(self._p(params, 'end_hz', 20.0))
        ramp  = max(0.001, float(self._p(params, 'ramp_time', 4.0)))
        bri   = float(self._p(params, 'brightness', 1.0))
        prog  = min(1.0, t / ramp)
        freq  = start + (end - start) * prog
        on    = (t * freq % 1.0) < 0.4
        return {'intensity': self._clamp(bri * 255) if on else 0}


class ChanStrobeBeat(ChannelEffect):
    """Flash de strobe sincronizado con RMS del audio."""
    effect_id = 'str_beat'
    name = 'Strobe Beat'
    category = 'strobe'
    required_channels = ['intensity']
    default_params = {'threshold': 0.5, 'decay': 8.0, 'brightness': 1.0}

    def __init__(self):
        self._last_beat: float = -999.0

    def render(self, t, audio_context, params):
        thr   = float(self._p(params, 'threshold', 0.5))
        decay = float(self._p(params, 'decay', 8.0))
        bri   = float(self._p(params, 'brightness', 1.0))
        rms   = self._rms(audio_context)
        if rms >= thr:
            self._last_beat = t
        amp = math.exp(-decay * max(0.0, t - self._last_beat))
        return {'intensity': self._clamp(bri * amp * 255)}


class ChanStrobeBurst(ChannelEffect):
    """Ráfaga de N pulsos en burst_time segundos, luego apagado."""
    effect_id = 'str_burst'
    name = 'Strobe Ráfaga'
    category = 'strobe'
    required_channels = ['intensity']
    default_params = {'pulses': 6, 'burst_time': 0.8, 'brightness': 1.0}

    def render(self, t, audio_context, params):
        pulses  = max(1, int(self._p(params, 'pulses', 6)))
        burst_t = max(0.1, float(self._p(params, 'burst_time', 0.8)))
        bri     = float(self._p(params, 'brightness', 1.0))
        if t > burst_t:
            return {'intensity': 0}
        on = (t / burst_t * pulses % 1.0) < 0.4
        return {'intensity': self._clamp(bri * 255) if on else 0}


class ChanStrobeRandom(ChannelEffect):
    """Strobe pseudo-aleatorio determinista."""
    effect_id = 'str_random'
    name = 'Strobe Aleatorio'
    category = 'strobe'
    required_channels = ['intensity']
    default_params = {'avg_hz': 6.0, 'brightness': 1.0}

    def render(self, t, audio_context, params):
        avg = max(0.5, float(self._p(params, 'avg_hz', 6.0)))
        bri = float(self._p(params, 'brightness', 1.0))
        # Ventana de 50ms por slot
        slot = int(t * 20)
        on   = random.Random(slot * 7919).random() < (avg / 20.0)
        return {'intensity': self._clamp(bri * 255) if on else 0}


# ════════════════════════════════════════════════════════════════
# Librería global
# ════════════════════════════════════════════════════════════════

class PanTiltWaveEffect(ChannelEffect):
    """Pan/tilt con modos: circle, fig8, bounce_pan, bounce_tilt.

    Parámetros compatibles con F2 (PARAM_SCHEMA en base Effect):
      pan_center / tilt_center : 0..1 (posición central, default 0.5)
      pan_range  / tilt_range  : amplitud máxima (0..0.5, default 0.25)
      speed                    : Hz (default 0.5)
      mode                     : circle | fig8 | bounce_pan | bounce_tilt

    Convención de fase (circle):
      t=0 → pan = center + range (máximo)
      t=T/4 → tilt = center + range (máximo)
    """
    effect_id = 'pos_pantilt_wave'
    name = 'Pan/Tilt Wave'
    category = 'position'
    required_channels = ['pan', 'tilt']

    PARAM_SCHEMA = {
        "pan_center":  {"type": "float", "min": 0.0, "max": 1.0, "default": 0.5, "label": "Pan centro"},
        "tilt_center": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.5, "label": "Tilt centro"},
        "pan_range":   {"type": "float", "min": 0.0, "max": 0.5, "default": 0.25, "label": "Rango pan"},
        "tilt_range":  {"type": "float", "min": 0.0, "max": 0.5, "default": 0.25, "label": "Rango tilt"},
        "speed":       {"type": "float", "min": 0.1, "max": 4.0, "default": 0.5, "label": "Velocidad (Hz)"},
        "mode":        {"type": "enum", "options": ["circle", "fig8", "bounce_pan", "bounce_tilt"],
                        "default": "circle", "label": "Modo"},
    }

    default_params = {
        "pan_center": 0.5, "tilt_center": 0.5,
        "pan_range": 0.25, "tilt_range": 0.25,
        "speed": 0.5, "mode": "circle",
    }

    def render(self, t: float, audio_context: dict | None, params: dict | None = None) -> dict[str, int]:
        p = {**self.default_params, **(params or {})}
        cp = float(p.get("pan_center", 0.5))
        ct = float(p.get("tilt_center", 0.5))
        pr = float(p.get("pan_range", 0.25))
        tr = float(p.get("tilt_range", 0.25))
        spd = float(p.get("speed", 0.5))
        mode = str(p.get("mode", "circle"))
        ω = 2.0 * math.pi * spd * t

        if mode == "circle":
            pan  = cp + pr * math.cos(ω)
            tilt = ct + tr * math.sin(ω)
        elif mode == "fig8":
            pan  = cp + pr * math.sin(ω)
            tilt = ct + tr * math.sin(2 * ω) / 2.0
        elif mode == "bounce_pan":
            pan  = cp + pr * math.sin(ω)
            tilt = ct
        elif mode == "bounce_tilt":
            pan  = cp
            tilt = ct + tr * math.sin(ω)
        else:
            pan, tilt = cp, ct

        return {
            "pan":  self._clamp(pan * 255),
            "tilt": self._clamp(tilt * 255),
        }


_ALL_EFFECTS: list[ChannelEffect] = [
    # position
    PanTiltWaveEffect(), ChanCircle(), ChanFigure8(), ChanSway(), ChanBeatSnap(), ChanPanSweep(),
    # color
    ChanRainbow(), ChanColorFade(), ChanColorFlash(), ChanWarmCold(), ChanColorStrobe(),
    # intensity
    ChanPulse(), ChanBump(), ChanFadeIn(), ChanBreath(), ChanDimFlash(),
    # optical
    ChanGoboSpin(), ChanGoboStep(), ChanZoomPulse(), ChanFrostPulse(),
    # strobe
    ChanStrobeSimple(), ChanStrobeRamp(), ChanStrobeBeat(), ChanStrobeBurst(),
    ChanStrobeRandom(),
]


class ChannelEffectLibrary:
    """Registro y acceso a todos los ChannelEffect."""

    def __init__(self):
        self._by_id: dict[str, ChannelEffect] = {e.effect_id: e for e in _ALL_EFFECTS}

    def get(self, effect_id: str) -> ChannelEffect | None:
        return self._by_id.get(effect_id)

    def all(self) -> list[ChannelEffect]:
        return list(_ALL_EFFECTS)

    def by_category(self, category: str) -> list[ChannelEffect]:
        return [e for e in _ALL_EFFECTS if e.category == category]

    def compatible_with_profile(self, profile) -> list[ChannelEffect]:
        """Efectos cuyas required_channels están todas en profile.channel_map."""
        avail = set(profile.channel_map.keys())
        return [e for e in _ALL_EFFECTS
                if all(ch in avail for ch in e.required_channels)]

    def describe_all(self) -> list[dict]:
        return [e.describe() for e in _ALL_EFFECTS]

    def describe(self, effect_id: str) -> dict | None:
        e = self._by_id.get(effect_id)
        return e.describe() if e else None
