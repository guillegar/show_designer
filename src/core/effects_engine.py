"""
Effects Engine - Sistema de 50 efectos para barras WLED
v2.0: Multi-capa, multi-disparador, 2D/3D, simétrico/asimétrico
"""

import math
import numpy as np
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Optional, Tuple, Dict, Any
from enum import Enum


# ------------------------------------------------------------
# v2.3: Constantes de geometría de las barras
# ------------------------------------------------------------
NUM_BARS = 10        # 10 barras WLED físicas
LEDS_PER_BAR = 93    # LEDs por barra
CENTER_BAR = NUM_BARS // 2   # 5 (para 10 barras; antes era 3 con 7)


# ------------------------------------------------------------
# v2.0 Helpers de normalización para features de audio.
# Garantizan que mfcc/tonnetz/contrast/centroid lleguen a [0,1]
# antes de mapearse a HSV o uint8 (evita overflow al castear).
# ------------------------------------------------------------

def _norm_mfcc(v):
    """MFCC coefficient → [0,1]. Rango típico [-100, 200]."""
    return float(np.clip((float(v) + 100.0) / 300.0, 0.0, 1.0))


def _norm_tonnetz(v):
    """Tonnetz coordinate → [0,1]. Rango típico [-0.1, 0.1]."""
    return float(np.clip(float(v) * 5.0 + 0.5, 0.0, 1.0))


def _norm_contrast(v):
    """Spectral contrast band → [0,1]. Rango típico [0, 60]."""
    return float(np.clip(float(v) / 60.0, 0.0, 1.0))


def _norm_centroid(v):
    """Spectral centroid (Hz) → [0,1]. Rango típico [0, 8000]."""
    return float(np.clip(float(v) / 8000.0, 0.0, 1.0))


def _norm01(v):
    """Clamp genérico a [0,1] para valores ya normalizados (chroma, energy, rms)."""
    return float(np.clip(float(v), 0.0, 1.0))


class EffectScope(Enum):
    """Alcance del efecto"""
    PER_BAR = "per_bar"      # Efecto independiente por barra
    ALL_BARS = "all_bars"    # Efecto en todas las barras
    GLOBAL = "global"        # Efecto global


class EffectGeometry(Enum):
    """Geometría del efecto"""
    GEOMETRY_2D = "2D"       # Dentro de 1 barra (93 LEDs)
    GEOMETRY_3D = "3D"       # Todas las barras + LEDs


class EffectSymmetry(Enum):
    """Simetría del efecto"""
    SYMMETRIC = "symmetric"        # Espejo vertical: bar[i] = bar[6-i]
    ASYMMETRIC = "asymmetric"      # Sin simetría, movimiento libre


# ============================================================================
# BASE CLASS
# ============================================================================

class Effect(ABC):
    """Clase base para todos los efectos"""

    name: str = "unnamed_effect"
    family: str = "generic"
    duration_ms: int = 1000
    scope: EffectScope = EffectScope.ALL_BARS
    geometry: EffectGeometry = EffectGeometry.GEOMETRY_3D
    symmetry: EffectSymmetry = EffectSymmetry.ASYMMETRIC
    description: str = "Efecto sin descripción"

    # Schema de parámetros para la UI auto-generada (F2).
    # {} = sin schema → controles de texto genéricos (sin regresión para efectos legacy).
    # Formato de cada entrada:
    #   {"type": "float"|"int"|"color"|"bool"|"enum",
    #    "min": ..., "max": ..., "step": ...,   # float/int
    #    "options": ["a","b"],                  # enum
    #    "default": ..., "label": "...", "unit": "..."}
    PARAM_SCHEMA: ClassVar[Dict[str, dict]] = {}

    def __init__(self):
        pass

    @abstractmethod
    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        """
        Renderiza el efecto.

        Args:
            elapsed_time: Tiempo desde que disparó el efecto (ms)
            bars_state: Estado actual de las barras (NUM_BARS, 93, 3)
            audio_context: Datos de audio (mfcc, energy, centroid, flux, etc)
            **params: Parámetros dinámicos del efecto

        Returns:
            Frame RGB. La forma la fija el contrato `expected_output_shape`,
            derivado del `scope`:
              • PER_BAR            → (1, LEDS_PER_BAR, 3): una fila; el motor la
                                     asigna a la barra del clip.
              • ALL_BARS / GLOBAL  → (NUM_BARS, LEDS_PER_BAR, 3): frame completo.
        """
        pass

    @property
    def expected_output_shape(self) -> Tuple[int, int, int]:
        """Forma válida de salida de `render()`, derivada del `scope`.

        PER_BAR devuelve una sola fila (1, LEDS_PER_BAR, 3) que el motor pinta
        en la barra del clip; ALL_BARS/GLOBAL devuelven el frame completo
        (NUM_BARS, LEDS_PER_BAR, 3). Formaliza el contrato que antes era
        implícito (ver ANALYSIS.md hallazgo 1).
        """
        if self.scope == EffectScope.PER_BAR:
            return (1, LEDS_PER_BAR, 3)
        return (NUM_BARS, LEDS_PER_BAR, 3)

    def _normalize_time(self, elapsed_time: float) -> float:
        """Retorna tiempo normalizado 0.0 a 1.0"""
        return min(1.0, max(0.0, elapsed_time / self.duration_ms))

    @staticmethod
    def apply_symmetry(frame_3d: np.ndarray, mode: str = "vertical_mirror") -> np.ndarray:
        """
        Aplica simetría a un frame 3D.

        Args:
            frame_3d: Shape (NUM_BARS, LEDS, 3)
            mode: "vertical_mirror" → bar[i] = bar[N-1-i]

        Returns:
            Frame con simetría aplicada
        """
        if mode == "vertical_mirror":
            n = frame_3d.shape[0]
            result = frame_3d.copy()
            # Promediar/espejar: las 2 mitades reflejan respecto al centro.
            for i in range(n // 2):
                result[i] = frame_3d[n - 1 - i]
                result[n - 1 - i] = frame_3d[i]
            return result
        return frame_3d

    @staticmethod
    def hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
        """Convierte HSV (0-360, 0-1, 0-1) a RGB (0-255)"""
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, v)
        return (int(r * 255), int(g * 255), int(b * 255))


# ============================================================================
# FAMILY 1: FLASH EFFECTS (10)
# ============================================================================

class WhiteFlashEffect(Effect):
    """Efecto 0: Destello blanco puro - global, simétrico"""
    name = "white_flash"
    family = "flash"
    duration_ms = 50
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC
    description = "Destello blanco puro en todas las barras"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        brightness = max(0, 1.0 - progress)  # Fade out
        frame = np.full((NUM_BARS, 93, 3), [255, 255, 255], dtype=np.uint8)
        frame = (frame.astype(float) * brightness).astype(np.uint8)
        return self.apply_symmetry(frame, "vertical_mirror")


class ColorFlashEffect(Effect):
    """Efecto 1: Flash de color por barra - per-bar, asimétrico"""
    name = "color_flash"
    family = "flash"
    duration_ms = 100
    scope = EffectScope.PER_BAR
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC
    description = "Flash de color diferente por barra"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        brightness = max(0, 1.0 - progress)
        hue = params.get('hue', 0)
        r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
        frame = np.full((1, 93, 3), [r, g, b], dtype=np.uint8)
        return frame


class PulseEffect(Effect):
    """Efecto 2: Pulsación - per-bar, simétrico"""
    name = "pulse"
    family = "flash"
    duration_ms = 500
    scope = EffectScope.PER_BAR
    geometry = EffectGeometry.GEOMETRY_2D
    symmetry = EffectSymmetry.SYMMETRIC
    description = "Pulsación suave (latido)"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import math
        progress = self._normalize_time(elapsed_time)
        # Oscilación suave
        brightness = 0.5 + 0.5 * math.sin(progress * math.pi * 2)
        hue = params.get('hue', 180)  # Cian por defecto
        r, g, b = self.hsv_to_rgb(hue, 0.8, brightness)
        frame = np.full((1, 93, 3), [r, g, b], dtype=np.uint8)
        return frame


class StrobeEffect(Effect):
    """Efecto 3: Estrobo rápido - global, asimétrico"""
    name = "strobe"
    family = "flash"
    duration_ms = 300
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC
    description = "Parpadeo rápido tipo estrobo"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        # 10 Hz strobe
        strobe_freq = 10  # Hz
        phase = (elapsed_time / 1000.0) * strobe_freq * 2 * 3.14159
        import math
        brightness = 1.0 if math.sin(phase) > 0 else 0.3
        frame = np.full((NUM_BARS, 93, 3), [255, 255, 255], dtype=np.uint8)
        frame = (frame.astype(float) * brightness).astype(np.uint8)
        return frame


class SaturationFlashEffect(Effect):
    """Efecto 4: Flash de saturación pura"""
    name = "saturation_flash"
    family = "flash"
    duration_ms = 100
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC
    description = "Flash de saturación extrema"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        brightness = max(0, 1.0 - progress)
        hue = params.get('hue', 0)
        r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
        frame = np.full((NUM_BARS, 93, 3), [r, g, b], dtype=np.uint8)
        return self.apply_symmetry(frame, "vertical_mirror")


# Efectos 5-9: Variantes por banda
class BassFlashEffect(Effect):
    """Efecto 5: Flash rojo (bass)"""
    name = "bass_flash"
    family = "flash"
    duration_ms = 75
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        brightness = max(0, 1.0 - progress)
        frame = np.full((NUM_BARS, 93, 3), [255, 0, 0], dtype=np.uint8)
        frame = (frame.astype(float) * brightness).astype(np.uint8)
        return self.apply_symmetry(frame, "vertical_mirror")


class MidFlashEffect(Effect):
    """Efecto 6: Flash verde (mids)"""
    name = "mid_flash"
    family = "flash"
    duration_ms = 75
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        brightness = max(0, 1.0 - progress)
        frame = np.full((NUM_BARS, 93, 3), [0, 255, 0], dtype=np.uint8)
        frame = (frame.astype(float) * brightness).astype(np.uint8)
        return self.apply_symmetry(frame, "vertical_mirror")


class TrebleFlashEffect(Effect):
    """Efecto 7: Flash azul (treble)"""
    name = "treble_flash"
    family = "flash"
    duration_ms = 75
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        brightness = max(0, 1.0 - progress)
        frame = np.full((NUM_BARS, 93, 3), [0, 0, 255], dtype=np.uint8)
        frame = (frame.astype(float) * brightness).astype(np.uint8)
        return self.apply_symmetry(frame, "vertical_mirror")


class MultiColorFlashEffect(Effect):
    """Efecto 8: Flash multi-color con parámetro"""
    name = "multicolor_flash"
    family = "flash"
    duration_ms = 100
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        brightness = max(0, 1.0 - progress)
        hue = params.get('hue', 280)  # Magenta por defecto
        r, g, b = self.hsv_to_rgb(hue, 0.9, brightness)
        frame = np.full((NUM_BARS, 93, 3), [r, g, b], dtype=np.uint8)
        return self.apply_symmetry(frame, "vertical_mirror")


class RandomFlashEffect(Effect):
    """Efecto 9: Flash aleatorio con color random"""
    name = "random_flash"
    family = "flash"
    duration_ms = 100
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import random
        progress = self._normalize_time(elapsed_time)
        brightness = max(0, 1.0 - progress)
        hue = random.uniform(0, 360)
        r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
        frame = np.full((NUM_BARS, 93, 3), [r, g, b], dtype=np.uint8)
        return frame


# ============================================================================
# FAMILY 2: WAVE EFFECTS (10)
# ============================================================================

class HorizontalWaveEffect(Effect):
    """Efecto 10: Onda horizontal izq→der - per-bar, 2D"""
    name = "horizontal_wave"
    family = "wave"
    duration_ms = 1000
    scope = EffectScope.PER_BAR
    geometry = EffectGeometry.GEOMETRY_2D
    symmetry = EffectSymmetry.ASYMMETRIC
    description = "Onda que viaja de izquierda a derecha"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        led_pos = progress * 93  # 0→93
        wave_width = params.get('width', 10)
        hue = params.get('hue', 60)  # Amarillo

        frame = np.zeros((1, 93, 3), dtype=np.uint8)
        for led in range(93):
            dist = abs(led - led_pos)
            brightness = max(0, 1.0 - (dist / wave_width))
            r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
            frame[0, led] = [r, g, b]
        return frame


class VerticalWaveEffect(Effect):
    """Efecto 11: Onda vertical bar 0→6 - global, 3D"""
    name = "vertical_wave"
    family = "wave"
    duration_ms = 1500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC
    description = "Onda que viaja entre barras verticalmente"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        bar_pos = progress * 7  # 0→7
        wave_width = params.get('width', 1.5)
        hue = params.get('hue', 200)  # Cian

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            dist = abs(bar - bar_pos)
            brightness = max(0, 1.0 - (dist / wave_width))
            r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
            frame[bar, :] = [r, g, b]
        return frame


class SymmetricRadialWaveEffect(Effect):
    """Efecto 12: Onda radial simétrica bar 3→edges"""
    name = "radial_wave_sym"
    family = "wave"
    duration_ms = 1500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC
    description = "Onda que expande desde el centro simétricamente"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        max_dist = progress * 3  # 0→3
        hue = params.get('hue', 120)  # Verde

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            dist_from_center = abs(bar - CENTER_BAR)
            brightness = max(0, 1.0 - abs(dist_from_center - max_dist) / 1.5)
            r, g, b = self.hsv_to_rgb(hue, 0.8, brightness)
            frame[bar, :] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class RainbowWaveEffect(Effect):
    """Efecto 13: Onda arcoíris asimétrica"""
    name = "rainbow_wave"
    family = "wave"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC
    description = "Onda de colores arcoíris"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        led_offset = progress * 93

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Arcoíris basado en posición LED
                hue = ((led + led_offset) % 93) * (360.0 / 93.0)
                brightness = 0.5 + 0.5 * np.cos((led - led_offset) / 10.0)
                brightness = max(0, min(1.0, brightness))
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]
        return frame


class EnergyWaveEffect(Effect):
    """Efecto 14: Onda de energía RMS - global, 3D"""
    name = "energy_wave"
    family = "wave"
    duration_ms = 1000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC
    description = "Altura de onda basada en energía actual"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        energy = audio_context.get('energy', 0.5)  # 0-1
        wave_height = int(energy * 93)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                if led < wave_height:
                    brightness = (led / max(1, wave_height))
                    hue = 280 - (led / 93.0) * 100  # Magenta→violeta
                    r, g, b = self.hsv_to_rgb(hue, 0.9, brightness)
                    frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class SpiralWaveEffect(Effect):
    """Efecto 15: Onda espiral simétrica"""
    name = "spiral_wave"
    family = "wave"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC
    description = "Patrón espiral simétrico"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import math
        progress = self._normalize_time(elapsed_time)
        phase = progress * 2 * math.pi

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Ecuación espiral
                angle = math.atan2(bar - CENTER_BAR, led - 46) + phase
                dist = math.sqrt((bar - CENTER_BAR)**2 + (led - 46)**2) / 50.0
                brightness = 0.5 + 0.5 * math.sin(angle - dist * 3.14159)
                brightness = max(0, min(1.0, brightness))
                hue = (angle * 180 / 3.14159) % 360
                r, g, b = self.hsv_to_rgb(hue, 0.7, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class MFFCWaveEffect(Effect):
    """Efecto 16: Onda guiada por MFCC"""
    name = "mfcc_wave"
    family = "wave"
    duration_ms = 1000
    scope = EffectScope.PER_BAR
    geometry = EffectGeometry.GEOMETRY_2D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        mfcc = audio_context.get('mfcc', None)
        if mfcc is None:
            mfcc = np.zeros(13)

        progress = self._normalize_time(elapsed_time)
        frame = np.zeros((1, 93, 3), dtype=np.uint8)

        for led in range(93):
            mfcc_idx = (led // 7) % len(mfcc)  # Map LEDs to MFCC coeffs
            energy = mfcc[mfcc_idx] if mfcc_idx < len(mfcc) else 0.5
            brightness = (energy + 0.5 * progress) % 1.0
            hue = (mfcc_idx * 30) % 360
            r, g, b = self.hsv_to_rgb(hue, 0.8, brightness)
            frame[0, led] = [r, g, b]

        return frame


class ChromaWaveEffect(Effect):
    """Efecto 17: Onda guiada por Chroma (12 notas)"""
    name = "chroma_wave"
    family = "wave"
    duration_ms = 1500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        chroma = audio_context.get('chroma', None)
        if chroma is None:
            chroma = np.zeros(12)

        progress = self._normalize_time(elapsed_time)
        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)

        for bar in range(NUM_BARS):
            for led in range(93):
                chroma_idx = (led // 7) % 12
                intensity = chroma[chroma_idx] if chroma_idx < len(chroma) else 0.5
                brightness = (intensity + 0.3 * progress) % 1.0
                hue = chroma_idx * 30  # 12 notas = 30° cada una
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]

        return frame


class CombinedSpectraWaveEffect(Effect):
    """Efecto 18: Onda combinada MFCC + Chroma"""
    name = "combined_spectra_wave"
    family = "wave"
    duration_ms = 1500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        mfcc = audio_context.get('mfcc', np.zeros(13))
        chroma = audio_context.get('chroma', np.zeros(12))
        progress = self._normalize_time(elapsed_time)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            mfcc_idx = bar % len(mfcc)
            chroma_idx = (bar + int(progress * 12)) % len(chroma)

            mfcc_energy = mfcc[mfcc_idx] if mfcc_idx < len(mfcc) else 0.5
            chroma_energy = chroma[chroma_idx] if chroma_idx < len(chroma) else 0.5

            for led in range(93):
                brightness = (mfcc_energy + chroma_energy) / 2.0
                brightness = (brightness + 0.5 * progress) % 1.0
                hue = (bar * 60 + led * 0.5) % 360
                r, g, b = self.hsv_to_rgb(hue, 0.8, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class DistortionWaveEffect(Effect):
    """Efecto 19: Onda con distorsión armónica"""
    name = "distortion_wave"
    family = "wave"
    duration_ms = 1200
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import math
        progress = self._normalize_time(elapsed_time)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Patrón armónico
                x = (led / 93.0) * 4 * math.pi + progress * 2 * math.pi
                y = math.sin(x) + 0.3 * math.sin(2 * x) + 0.1 * math.sin(3 * x)
                brightness = 0.5 + 0.5 * y
                brightness = max(0, min(1.0, brightness))
                hue = (bar * 60 + led * 0.4) % 360
                r, g, b = self.hsv_to_rgb(hue, 0.7, brightness)
                frame[bar, led] = [r, g, b]

        return frame


# ============================================================================
# FAMILY 3: GRADIENT EFFECTS (10)
# ============================================================================

class LinearGradientEffect(Effect):
    """Efecto 20: Gradiente lineal 2D (0→93)"""
    name = "linear_gradient"
    family = "gradient"
    duration_ms = 1000
    scope = EffectScope.PER_BAR
    geometry = EffectGeometry.GEOMETRY_2D
    symmetry = EffectSymmetry.ASYMMETRIC
    description = "Gradiente lineal de color"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        hue_start = params.get('hue_start', 0)
        hue_end = params.get('hue_end', 180)

        frame = np.zeros((1, 93, 3), dtype=np.uint8)
        for led in range(93):
            ratio = led / 93.0
            hue = hue_start + (hue_end - hue_start) * ratio
            hue = hue % 360
            r, g, b = self.hsv_to_rgb(hue, 1.0, 1.0)
            frame[0, led] = [r, g, b]

        return frame


class RadialGradientEffect(Effect):
    """Efecto 21: Gradiente radial 3D simétrico (bar 3→edges)"""
    name = "radial_gradient"
    family = "gradient"
    duration_ms = 1500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC
    description = "Gradiente radial desde el centro"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        hue_center = params.get('hue_center', 120)
        hue_edge = params.get('hue_edge', 240)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Distancia desde centro (bar 3, led 46)
                dist = math.sqrt((bar - CENTER_BAR)**2 + ((led - 46) / 10.0)**2) / 3.0
                dist = min(1.0, dist)

                hue = hue_center + (hue_edge - hue_center) * dist
                hue = hue % 360
                brightness = 1.0 - dist * 0.5
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class AsymmetricGradientEffect(Effect):
    """Efecto 22: Gradiente asimétrico 3D (cascada bar 0→6)"""
    name = "asymmetric_gradient"
    family = "gradient"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC
    description = "Gradiente que cae como cascada"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        hue_start = params.get('hue_start', 0)
        hue_end = params.get('hue_end', 300)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Cascada diagonal
                ratio = ((bar / 7.0) + (led / 93.0) + progress) % 1.0
                hue = hue_start + (hue_end - hue_start) * ratio
                hue = hue % 360
                brightness = 0.5 + 0.5 * np.sin(ratio * 3.14159)
                r, g, b = self.hsv_to_rgb(hue, 0.9, brightness)
                frame[bar, led] = [r, g, b]

        return frame


class MFFCGradientEffect(Effect):
    """Efecto 23: Gradiente guiado por MFCC"""
    name = "mfcc_gradient"
    family = "gradient"
    duration_ms = 1500
    scope = EffectScope.PER_BAR
    geometry = EffectGeometry.GEOMETRY_2D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        mfcc = audio_context.get('mfcc', np.zeros(13))

        frame = np.zeros((1, 93, 3), dtype=np.uint8)
        for led in range(93):
            mfcc_idx = (led // 7) % len(mfcc)
            raw = mfcc[mfcc_idx] if mfcc_idx < len(mfcc) else 0.0
            energy = _norm_mfcc(raw)  # [0,1]

            hue = energy * 360  # Mapa energía a matiz
            brightness = energy
            r, g, b = self.hsv_to_rgb(hue, 0.8, brightness)
            frame[0, led] = [r, g, b]

        return frame


class ChromaGradientEffect(Effect):
    """Efecto 24: Gradiente cíclico Chroma (12 notas)"""
    name = "chroma_gradient"
    family = "gradient"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC
    description = "12 notas musicalescíclicas"

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        chroma = audio_context.get('chroma', np.zeros(12))
        progress = self._normalize_time(elapsed_time)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                chroma_idx = ((led // 7) + int(progress * 12)) % 12
                intensity = chroma[chroma_idx] if chroma_idx < len(chroma) else 0.5

                hue = chroma_idx * 30  # 12 notas
                brightness = intensity
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class EnergyGradientEffect(Effect):
    """Efecto 25: Gradiente de energía dinámica"""
    name = "energy_gradient"
    family = "gradient"
    duration_ms = 1000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        energy = audio_context.get('energy', 0.5)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Gradiente basado en energía
                ratio = (led / 93.0) * energy
                hue = 300 - (ratio * 100)  # Magenta → azul
                hue = max(0, hue)
                brightness = energy * (1.0 - (led / 93.0) * 0.5)
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class HeatmapGradientEffect(Effect):
    """Efecto 26: Mapa de calor con simetría dinámica"""
    name = "heatmap_gradient"
    family = "gradient"
    duration_ms = 1500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        energy = audio_context.get('energy', 0.5)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Mapa de calor: cyan → rojo
                intensity = ((led / 93.0) * energy + progress * 0.5) % 1.0
                if intensity < 0.33:
                    hue = 180 + intensity * 150  # Cyan → verde
                elif intensity < 0.66:
                    hue = 60 + (intensity - 0.33) * 150  # Verde → rojo
                else:
                    hue = 0  # Rojo

                brightness = 0.3 + 0.7 * intensity
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class PulseGradientEffect(Effect):
    """Efecto 27: Gradiente con pulsación"""
    name = "pulse_gradient"
    family = "gradient"
    duration_ms = 1200
    scope = EffectScope.PER_BAR
    geometry = EffectGeometry.GEOMETRY_2D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import math
        progress = self._normalize_time(elapsed_time)
        pulse = 0.5 + 0.5 * math.sin(progress * 2 * math.pi)

        frame = np.zeros((1, 93, 3), dtype=np.uint8)
        for led in range(93):
            ratio = led / 93.0
            hue = 240 * ratio  # Azul → rojo
            brightness = ratio * pulse
            r, g, b = self.hsv_to_rgb(hue, 0.9, brightness)
            frame[0, led] = [r, g, b]

        return frame


class WaveGradientEffect(Effect):
    """Efecto 28: Gradiente ondelante"""
    name = "wave_gradient"
    family = "gradient"
    duration_ms = 1500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import math
        progress = self._normalize_time(elapsed_time)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Onda sinusoidal + gradiente
                x = (led / 93.0) * 4 * math.pi + progress * 2 * math.pi
                wave = 0.5 + 0.5 * math.sin(x)

                hue = (led / 93.0) * 360
                brightness = wave
                r, g, b = self.hsv_to_rgb(hue, 0.8, brightness)
                frame[bar, led] = [r, g, b]

        return frame


class StepGradientEffect(Effect):
    """Efecto 29: Gradiente por pasos/bandas"""
    name = "step_gradient"
    family = "gradient"
    duration_ms = 1000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        num_steps = params.get('steps', 7)
        step_size = 93 // num_steps

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                step = led // step_size
                hue = (step / num_steps) * 360
                brightness = 1.0 - (step / num_steps) * 0.5
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


# ============================================================================
# FAMILY 4: PATTERN EFFECTS (10) - Números 30-39
# ============================================================================

class StripesPattern2DEffect(Effect):
    """Efecto 30: Franjas horizontales 2D simétrico"""
    name = "stripes_2d"
    family = "pattern"
    duration_ms = 1000
    scope = EffectScope.PER_BAR
    geometry = EffectGeometry.GEOMETRY_2D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        stripe_width = params.get('width', 5)
        hue = params.get('hue', 0)

        frame = np.zeros((1, 93, 3), dtype=np.uint8)
        for led in range(93):
            if (led // stripe_width) % 2 == 0:
                r, g, b = self.hsv_to_rgb(hue, 1.0, 1.0)
            else:
                r, g, b = self.hsv_to_rgb(hue, 0.2, 0.5)
            frame[0, led] = [r, g, b]

        return frame


class Stripes3DEffect(Effect):
    """Efecto 31: Franjas verticales 3D simétricas"""
    name = "stripes_3d"
    family = "pattern"
    duration_ms = 1200
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        stripe_width = params.get('width', 1)
        hue = params.get('hue', 240)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                if ((bar + led // 10) // stripe_width) % 2 == 0:
                    r, g, b = self.hsv_to_rgb(hue, 1.0, 1.0)
                else:
                    r, g, b = self.hsv_to_rgb(hue, 0.3, 0.4)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class BreathingEffect(Effect):
    """Efecto 32: Respiración 3D simétrica (pulsación)"""
    name = "breathing"
    family = "pattern"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import math
        progress = self._normalize_time(elapsed_time)
        brightness = 0.5 + 0.5 * math.sin(progress * 2 * math.pi)
        hue = params.get('hue', 200)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            r, g, b = self.hsv_to_rgb(hue, 0.7, brightness)
            frame[bar, :] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class SpinningEffect(Effect):
    """Efecto 33: Rotación 3D asimétrica"""
    name = "spinning"
    family = "pattern"
    duration_ms = 2000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import math
        progress = self._normalize_time(elapsed_time)
        angle = progress * 2 * math.pi

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Patrón rotatorio
                x, y = led - 46, bar - CENTER_BAR
                rot_x = x * math.cos(angle) - y * math.sin(angle)
                hue = (math.atan2(y, x) * 180 / math.pi + progress * 360) % 360
                brightness = 0.5 + 0.5 * math.sin(rot_x / 20.0)
                r, g, b = self.hsv_to_rgb(hue, 0.8, brightness)
                frame[bar, led] = [r, g, b]

        return frame


class SparkleEffect(Effect):
    """Efecto 34: Puntos aleatorios/chispas 3D asimétrico"""
    name = "sparkle"
    family = "pattern"
    duration_ms = 500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import random
        progress = self._normalize_time(elapsed_time)
        density = params.get('density', 0.1)  # % de LEDs que brillan

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        random.seed(int(elapsed_time / 50))  # Cambio semi-aleatorio cada 50ms

        for bar in range(NUM_BARS):
            for led in range(93):
                if random.random() < density:
                    hue = random.uniform(0, 360)
                    brightness = random.uniform(0.5, 1.0)
                    r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                    frame[bar, led] = [r, g, b]

        return frame


class ChaseEffect(Effect):
    """Efecto 35: Persecución 3D simétrica"""
    name = "chase"
    family = "pattern"
    duration_ms = 1500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        chase_pos = progress * 93
        chase_width = params.get('width', 5)
        hue = params.get('hue', 60)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                dist = abs(led - chase_pos) + abs(bar - CENTER_BAR) * 2
                brightness = max(0, 1.0 - (dist / chase_width))
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


# Efectos 36-39: Variantes
class AlternatingStripesEffect(Effect):
    """Efecto 36: Franjas alternadas rápidas"""
    name = "alternating_stripes"
    family = "pattern"
    duration_ms = 600
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)
        phase = int(progress * 10) % 2  # Alterna cada 60ms

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                if ((led + bar + phase) % 2) == 0:
                    r, g, b = (255, 0, 0)  # Rojo
                else:
                    r, g, b = (0, 0, 255)  # Azul
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class DiamondPatternEffect(Effect):
    """Efecto 37: Patrón de diamantes/rombos"""
    name = "diamond_pattern"
    family = "pattern"
    duration_ms = 1500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        progress = self._normalize_time(elapsed_time)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Distancia Manhattan desde el centro
                dist = abs(bar - CENTER_BAR) + abs((led - 46) / 10.0)
                brightness = max(0, 1.0 - ((dist - progress * 3.5) % 3.5) / 1.75)
                hue = (progress * 360 + dist * 20) % 360
                r, g, b = self.hsv_to_rgb(hue, 0.8, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class StarbburstEffect(Effect):
    """Efecto 38: Explosión radial tipo starburst"""
    name = "starburst"
    family = "pattern"
    duration_ms = 800
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import math
        progress = self._normalize_time(elapsed_time)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                dx, dy = led - 46, bar - CENTER_BAR
                angle = math.atan2(dy, dx / 5.0) * 180 / math.pi
                dist = math.sqrt((dx / 5.0)**2 + dy**2)

                # Rayos que explotan hacia afuera
                brightness = max(0, 1.0 - abs(dist - progress * 5.0) / 1.0)
                hue = (angle + progress * 360) % 360
                r, g, b = self.hsv_to_rgb(hue, 0.9, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class NeonGlowEffect(Effect):
    """Efecto 39: Efecto neón/brillo"""
    name = "neon_glow"
    family = "pattern"
    duration_ms = 1200
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        import math
        progress = self._normalize_time(elapsed_time)
        glow = 0.5 + 0.5 * math.sin(progress * 2 * math.pi)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        hue = params.get('hue', 270)  # Magenta por defecto

        for bar in range(NUM_BARS):
            for led in range(93):
                # Efecto de brillo/glow
                center_dist = abs(led - 46) + abs(bar - CENTER_BAR) * 2
                local_glow = max(0.2, glow - (center_dist / 100.0))

                r, g, b = self.hsv_to_rgb(hue, 1.0, local_glow)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


# ============================================================================
# FAMILY 5: SPECTRAL EFFECTS (10) - Números 40-49
# ============================================================================

class MFFCSonogram2DEffect(Effect):
    """Efecto 40: MFCC sonograma en 2D"""
    name = "mfcc_sonogram_2d"
    family = "spectral"
    duration_ms = 500
    scope = EffectScope.PER_BAR
    geometry = EffectGeometry.GEOMETRY_2D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        mfcc = audio_context.get('mfcc', np.zeros(13))

        frame = np.zeros((1, 93, 3), dtype=np.uint8)
        for led in range(93):
            mfcc_idx = (led // 7) % len(mfcc)
            raw = mfcc[mfcc_idx] if mfcc_idx < len(mfcc) else 0.0
            coeff_value = _norm_mfcc(raw)  # [0,1]

            # Mapear coef MFCC a color
            hue = coeff_value * 360
            brightness = coeff_value
            r, g, b = self.hsv_to_rgb(hue, 0.9, brightness)
            frame[0, led] = [r, g, b]

        return frame


class MFFCSonogram3DEffect(Effect):
    """Efecto 41: MFCC sonograma 3D simétrico"""
    name = "mfcc_sonogram_3d"
    family = "spectral"
    duration_ms = 600
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        mfcc = audio_context.get('mfcc', np.zeros(13))

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            mfcc_idx = bar % len(mfcc)
            raw = mfcc[mfcc_idx] if mfcc_idx < len(mfcc) else 0.0
            coeff_value = _norm_mfcc(raw)  # [0,1]

            for led in range(93):
                # Cada bar = un coef MFCC
                brightness = coeff_value
                hue = (bar * 30 + led * 0.5) % 360
                r, g, b = self.hsv_to_rgb(hue, 0.8, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class ChromaDisplayEffect(Effect):
    """Efecto 42: Visualización de 12 notas (Chroma)"""
    name = "chroma_display"
    family = "spectral"
    duration_ms = 500
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        chroma = audio_context.get('chroma', np.zeros(12))

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                chroma_idx = (led // 7) % len(chroma)
                intensity = chroma[chroma_idx] if chroma_idx < len(chroma) else 0.5

                hue = chroma_idx * 30  # 12 notas = 30° cada una
                brightness = intensity
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]

        return frame


class CentroidFollowEffect(Effect):
    """Efecto 43: Seguimiento de centroide (altura tonal) 3D asimétrico"""
    name = "centroid_follow"
    family = "spectral"
    duration_ms = 800
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        centroid = audio_context.get('centroid', 0.5)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        centroid_led = int(centroid * 93)  # 0-93

        for bar in range(NUM_BARS):
            for led in range(93):
                # Brillo máximo en la posición del centroide
                dist = abs(led - centroid_led)
                brightness = max(0, 1.0 - (dist / 15.0))

                hue = (centroid * 360 + bar * 50) % 360
                r, g, b = self.hsv_to_rgb(hue, 0.9, brightness)
                frame[bar, led] = [r, g, b]

        return frame


class FluxPeaksEffect(Effect):
    """Efecto 44: Picos de flux (cambio espectral) 3D simétrico"""
    name = "flux_peaks"
    family = "spectral"
    duration_ms = 400
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        flux = audio_context.get('flux', 0.5)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                # Mayor brillo en picos de flux
                brightness = flux
                hue = (led * 2) % 360
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class EnergyMeterEffect(Effect):
    """Efecto 45: Medidor de energía (llama) 2D-3D"""
    name = "energy_meter"
    family = "spectral"
    duration_ms = 600
    scope = EffectScope.PER_BAR
    geometry = EffectGeometry.GEOMETRY_2D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        energy = audio_context.get('energy', 0.5)
        flame_height = int(energy * 93)

        frame = np.zeros((1, 93, 3), dtype=np.uint8)
        for led in range(93):
            if led < flame_height:
                # Gradiente de llama: naranja→amarillo→blanco
                ratio = led / max(1, flame_height)
                if ratio < 0.5:
                    r, g, b = int(255), int(100 * (ratio * 2)), 0  # Naranja
                else:
                    r, g, b = 255, int(100 + 155 * ((ratio - 0.5) * 2)), 0  # Amarillo
                brightness = ratio
                r, g, b = int(r * brightness), int(g * brightness), int(b * brightness)
                frame[0, led] = [r, g, b]

        return frame


# Efectos 46-49: Variantes espectrales
class CombinedMFFCChromaEffect(Effect):
    """Efecto 46: MFCC + Chroma combinados 3D simétrico"""
    name = "combined_mfcc_chroma"
    family = "spectral"
    duration_ms = 700
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        mfcc = audio_context.get('mfcc', np.zeros(13))
        chroma = audio_context.get('chroma', np.zeros(12))

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                mfcc_idx = (bar % len(mfcc))
                chroma_idx = ((led // 7) % len(chroma))

                mfcc_raw = mfcc[mfcc_idx] if mfcc_idx < len(mfcc) else 0.0
                chroma_raw = chroma[chroma_idx] if chroma_idx < len(chroma) else 0.5
                mfcc_val = _norm_mfcc(mfcc_raw)
                chroma_val = _norm01(chroma_raw)

                brightness = (mfcc_val + chroma_val) / 2.0
                hue = chroma_idx * 30  # Basado en nota
                r, g, b = self.hsv_to_rgb(hue, 0.8, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class TonnetzEffect(Effect):
    """Efecto 47: Tonnetz (6 dimensiones tonales) 3D asimétrico"""
    name = "tonnetz"
    family = "spectral"
    duration_ms = 800
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        tonnetz = audio_context.get('tonnetz', np.zeros(6))

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            tonnetz_idx = bar % len(tonnetz)
            raw = tonnetz[tonnetz_idx] if tonnetz_idx < len(tonnetz) else 0.0
            tonval = _norm_tonnetz(raw)  # [0,1]

            for led in range(93):
                brightness = tonval
                hue = (tonnetz_idx * 60 + led * 0.3) % 360
                r, g, b = self.hsv_to_rgb(hue, 0.9, brightness)
                frame[bar, led] = [r, g, b]

        return frame


class ContrastVizEffect(Effect):
    """Efecto 48: Visualización de contraste espectral"""
    name = "contrast_viz"
    family = "spectral"
    duration_ms = 600
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        # contrast es array (7,) — una banda por barra
        contrast = audio_context.get('contrast', np.zeros(7))
        if np.ndim(contrast) == 0:
            contrast = np.full(7, float(contrast))

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            band_idx = bar % len(contrast)
            band_val = _norm_contrast(contrast[band_idx])  # [0,1]
            hue = (band_val * 360) % 360
            for led in range(93):
                brightness = band_val
                r, g, b = self.hsv_to_rgb(hue, 1.0, brightness)
                frame[bar, led] = [r, g, b]

        return self.apply_symmetry(frame, "vertical_mirror")


class AllSpectralEffect(Effect):
    """Efecto 49: Todos los datos espectrales (mega-visualización)"""
    name = "all_spectral"
    family = "spectral"
    duration_ms = 1000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.ASYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        mfcc = audio_context.get('mfcc', np.zeros(13))
        chroma = audio_context.get('chroma', np.zeros(12))
        energy = audio_context.get('energy', 0.5)
        centroid = audio_context.get('centroid', 0.5)

        # Normalizar scalars de audio_context
        energy_n = _norm01(energy)
        centroid_n = _norm_centroid(centroid)

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            mfcc_idx = bar % len(mfcc)
            mfcc_raw = mfcc[mfcc_idx] if mfcc_idx < len(mfcc) else 0.0
            mfcc_val = _norm_mfcc(mfcc_raw)  # [0,1]

            for led in range(93):
                chroma_idx = (led // 7) % len(chroma)
                chroma_raw = chroma[chroma_idx] if chroma_idx < len(chroma) else 0.5
                chroma_val = _norm01(chroma_raw)

                # Combina todo (todos ya en [0,1])
                combined = (mfcc_val * 0.4 + chroma_val * 0.3 + energy_n * 0.3)
                brightness = combined

                # Hue basado en centroide normalizado
                hue = centroid_n * 360
                r, g, b = self.hsv_to_rgb(hue, 0.9, brightness)
                frame[bar, led] = [r, g, b]

        return frame


# ============================================================================
# FAMILY 6: RING EFFECTS (50+) — Aros que se expanden
# ============================================================================

class RingExpandEffect(Effect):
    """Efecto 50: Aro de luz que se expande desde el centro vertical hacia los extremos.

    El aro nace como una banda fina en el LED central (46) de TODAS las barras y se
    expande hacia los LEDs 0 y 92 a medida que avanza el tiempo. El brillo decae
    suavemente con la expansión (efecto onda de choque).

    Parámetros opcionales (params):
        hue (float, 0-360): matiz del aro (default 200 = cyan)
        saturation (float, 0-1): saturación HSV (default 1.0)
        ring_width (int): grosor del aro en LEDs (default 4)
        speed (float): multiplicador de velocidad de expansión (default 1.0)
    """
    name = "ring_expand"
    family = "ring"
    duration_ms = 1000
    scope = EffectScope.ALL_BARS
    geometry = EffectGeometry.GEOMETRY_3D
    symmetry = EffectSymmetry.SYMMETRIC

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        # Progreso 0→1 sobre la duración total del efecto
        progress = self._normalize_time(elapsed_time)
        # Permite acelerar/ralentizar la onda sin tocar duration_ms
        speed = float(params.get('speed', 1.0))
        progress = min(1.0, progress * speed)

        # El aro se centra en el LED 46 (mitad del bar, 93 LEDs)
        center_led = 46
        max_radius = 46  # los LEDs 0 y 92 son la "pared" del aro al expandirse
        radius = progress * max_radius
        ring_width = float(params.get('ring_width', 4))
        half_w = ring_width / 2.0

        # Color del aro (cyan brillante por defecto)
        hue = float(params.get('hue', 200.0))
        saturation = _norm01(params.get('saturation', 1.0))

        # Modulación opcional por energía del audio: el aro brilla más con golpes fuertes
        energy = _norm01(audio_context.get('energy', audio_context.get('rms', 0.5)))
        energy_mult = 0.6 + energy * 0.4  # [0.6, 1.0]

        # Decay de brillo a medida que el aro se aleja del centro (shockwave fade)
        brightness_base = max(0.0, 1.0 - progress * 0.4) * energy_mult

        frame = np.zeros((NUM_BARS, 93, 3), dtype=np.uint8)
        for bar in range(NUM_BARS):
            for led in range(93):
                dist = abs(led - center_led)
                offset_from_ring = abs(dist - radius)
                # ¿LED dentro del grosor del aro?
                if offset_from_ring < half_w:
                    # Atenuación suave hacia los bordes del aro (forma gaussiana ligera)
                    edge_norm = offset_from_ring / half_w  # 0=centro del aro, 1=borde
                    intensity = (1.0 - edge_norm) * brightness_base
                    r, g, b = self.hsv_to_rgb(hue, saturation, intensity)
                    frame[bar, led] = [r, g, b]

        # Como todas las barras tienen el aro a la misma altura, la simetría
        # vertical ya está garantizada por construcción.
        return frame


# ============================================================================
# EFFECT LIBRARY
# ============================================================================

PLUGIN_BASE_ID = 1000   # IDs de plugins empiezan desde aquí


class EffectLibrary:
    """Librería central de efectos (50 base + plugins autodescubiertos)

    Plugins: colocar archivos .py en plugins/effects/.
    Cada archivo puede definir PLUGIN_EFFECTS = {id: Effect()} o
    simplemente subclases de Effect (se autodescubren con IDs desde 1000).
    """

    def __init__(self):
        # Crear instancias de todos los 50 efectos
        self.effects = {
            # Family 1: Flash (0-9)
            0: WhiteFlashEffect(),
            1: ColorFlashEffect(),
            2: PulseEffect(),
            3: StrobeEffect(),
            4: SaturationFlashEffect(),
            5: BassFlashEffect(),
            6: MidFlashEffect(),
            7: TrebleFlashEffect(),
            8: MultiColorFlashEffect(),
            9: RandomFlashEffect(),

            # Family 2: Wave (10-19)
            10: HorizontalWaveEffect(),
            11: VerticalWaveEffect(),
            12: SymmetricRadialWaveEffect(),
            13: RainbowWaveEffect(),
            14: EnergyWaveEffect(),
            15: SpiralWaveEffect(),
            16: MFFCWaveEffect(),
            17: ChromaWaveEffect(),
            18: CombinedSpectraWaveEffect(),
            19: DistortionWaveEffect(),

            # Family 3: Gradient (20-29)
            20: LinearGradientEffect(),
            21: RadialGradientEffect(),
            22: AsymmetricGradientEffect(),
            23: MFFCGradientEffect(),
            24: ChromaGradientEffect(),
            25: EnergyGradientEffect(),
            26: HeatmapGradientEffect(),
            27: PulseGradientEffect(),
            28: WaveGradientEffect(),
            29: StepGradientEffect(),

            # Family 4: Pattern (30-39)
            30: StripesPattern2DEffect(),
            31: Stripes3DEffect(),
            32: BreathingEffect(),
            33: SpinningEffect(),
            34: SparkleEffect(),
            35: ChaseEffect(),
            36: AlternatingStripesEffect(),
            37: DiamondPatternEffect(),
            38: StarbburstEffect(),
            39: NeonGlowEffect(),

            # Family 5: Spectral (40-49)
            40: MFFCSonogram2DEffect(),
            41: MFFCSonogram3DEffect(),
            42: ChromaDisplayEffect(),
            43: CentroidFollowEffect(),
            44: FluxPeaksEffect(),
            45: EnergyMeterEffect(),
            46: CombinedMFFCChromaEffect(),
            47: TonnetzEffect(),
            48: ContrastVizEffect(),
            49: AllSpectralEffect(),

            # Family 6: Ring (50+)
            50: RingExpandEffect(),
        }

        # ── Cargar plugins autodescubiertos ──────────────────────────────────
        self._load_plugins()

    def _load_plugins(self):
        """Descubre y carga efectos desde plugins/effects/*.py.

        Para cada archivo:
          1. Si define PLUGIN_EFFECTS = {id: Effect()} → usa esos IDs.
          2. Si no, busca subclases concretas de Effect y les asigna IDs
             consecutivos desde PLUGIN_BASE_ID.
        Los IDs de plugins (>=1000) nunca solapan con los base (0-999).
        """
        import importlib.util, sys
        from pathlib import Path as _Path

        plugins_dir = _Path(__file__).parent.parent.parent / 'plugins' / 'effects'
        if not plugins_dir.is_dir():
            return

        next_auto_id = PLUGIN_BASE_ID
        # Reservar IDs ya ocupados por PLUGIN_EFFECTS en archivos anteriores
        for existing_id in list(self.effects.keys()):
            if existing_id >= PLUGIN_BASE_ID:
                next_auto_id = max(next_auto_id, existing_id + 1)

        for plugin_file in sorted(plugins_dir.glob('*.py')):
            if plugin_file.name.startswith('_'):
                continue   # skip __init__.py y archivos privados
            try:
                mod_name = f"plugins.effects.{plugin_file.stem}"
                spec = importlib.util.spec_from_file_location(mod_name, plugin_file)
                mod  = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)

                # 1) Si el módulo define PLUGIN_EFFECTS → usar esos IDs
                if hasattr(mod, 'PLUGIN_EFFECTS') and isinstance(mod.PLUGIN_EFFECTS, dict):
                    count = 0
                    for eff_id, eff_instance in mod.PLUGIN_EFFECTS.items():
                        if not isinstance(eff_instance, Effect):
                            continue
                        if eff_id < PLUGIN_BASE_ID:
                            print(f"[plugin] AVISO: {plugin_file.name} usa ID {eff_id} "
                                  f"(< {PLUGIN_BASE_ID}). Reasignando a {next_auto_id}.")
                            eff_id = next_auto_id
                        if eff_id in self.effects:
                            print(f"[plugin] AVISO: ID {eff_id} ya existe. Reasignando a {next_auto_id}.")
                            eff_id = next_auto_id
                        self.effects[eff_id] = eff_instance
                        next_auto_id = max(next_auto_id, eff_id + 1)
                        count += 1
                    if count:
                        print(f"[plugin] {plugin_file.name}: {count} efectos cargados (PLUGIN_EFFECTS)")
                    continue

                # 2) Autodescubrir subclases concretas de Effect en el módulo
                loaded = 0
                for attr_name in dir(mod):
                    cls = getattr(mod, attr_name)
                    if (isinstance(cls, type) and
                            issubclass(cls, Effect) and
                            cls is not Effect and
                            not getattr(cls, '__abstractmethods__', None)):
                        try:
                            instance = cls()
                            self.effects[next_auto_id] = instance
                            print(f"[plugin] {plugin_file.name}: {attr_name} -> ID {next_auto_id}")
                            next_auto_id += 1
                            loaded += 1
                        except Exception as e:
                            print(f"[plugin] {plugin_file.name}: error instanciando {attr_name}: {e}")
                if loaded == 0:
                    print(f"[plugin] {plugin_file.name}: ninguna subclase de Effect encontrada")

            except Exception as e:
                print(f"[plugin] Error cargando {plugin_file.name}: {e}")
                import traceback; traceback.print_exc()

    def get_effect(self, effect_id: int) -> Optional[Effect]:
        """Obtiene un efecto por ID (0-49)"""
        return self.effects.get(effect_id)

    def list_effects(self) -> Dict[int, Dict[str, Any]]:
        """Lista metadatos de todos los efectos"""
        result = {}
        for effect_id, effect in self.effects.items():
            result[effect_id] = {
                'name': effect.name,
                'family': effect.family,
                'duration_ms': effect.duration_ms,
                'scope': effect.scope.value,
                'geometry': effect.geometry.value,
                'symmetry': effect.symmetry.value,
                'description': effect.description,
            }
        return result

    def list_by_family(self, family: str) -> Dict[int, Effect]:
        """Lista efectos de una familia específica"""
        return {
            effect_id: effect
            for effect_id, effect in self.effects.items()
            if effect.family == family
        }


if __name__ == "__main__":
    # Test básico
    import math
    library = EffectLibrary()
    print(f"[OK] Cargados {len(library.effects)} efectos")

    # Test un efecto
    effect = library.get_effect(0)
    print(f"[OK] Efecto 0: {effect.name}")

    # Renderizar un frame de prueba
    audio_ctx = {
        'mfcc': np.random.rand(13),
        'chroma': np.random.rand(12),
        'energy': 0.6,
        'centroid': 0.5,
        'flux': 0.4,
    }
    frame = effect.render(25, np.zeros((NUM_BARS, 93, 3)), audio_ctx)
    print(f"[OK] Frame shape: {frame.shape}")
    print(f"[OK] Effects Engine initialized successfully!")
