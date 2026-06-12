"""
modulation.py — Motor de modulación de parámetros por señales de audio.
(ROADMAP v2, Fase A1)

Permite vincular cualquier parámetro numérico de un efecto a una señal del análisis
musical (rms, flux, centroid, mel_bands.3, etc.) con transformaciones (gain, offset,
curve, clamp). Ejemplo: brightness ← rms → las barras respiran con la música.

Modelo de datos:
  ParamLink — persistido en Clip.param_links, describe un mapeo param → source + transformaciones
  ModulationStage — implementa ParamStage del pipeline, aplica los links a params en tiempo real

La modulación SIEMPRE lee de actx['norm'] (señales normalizadas 0..1), nunca de la cruda,
para evitar sorpresas con rangos dispares (centroid ~1000-4000, rms ~0-0.5).

Módulo puro: SIN imports de server/, web/, fastapi, efectos concretos.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
import numpy as np

from src.core.param_pipeline import ParamStage


@dataclass
class ParamLink:
    """Vínculo entre un parámetro del clip y una señal de análisis.

    Attrs:
        param: nombre del parámetro del efecto (ej. 'brightness', 'speed', 'hue').
        source: señal a leer (ej. 'rms', 'flux', 'centroid', 'mel_bands.3').
        gain: multiplicador del valor interpolado (default 1.0).
        offset: desplazamiento después del gain (default 0.0).
        curve: transformación ('linear', 'exp', 'log', 'invert').
        min_v: clamp inferior del resultado (default 0.0).
        max_v: clamp superior del resultado (default 1.0).
    """
    param: str
    source: str
    gain: float = 1.0
    offset: float = 0.0
    curve: str = 'linear'
    min_v: float = 0.0
    max_v: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ParamLink:
        return cls(
            param=d['param'],
            source=d['source'],
            gain=float(d.get('gain', 1.0)),
            offset=float(d.get('offset', 0.0)),
            curve=d.get('curve', 'linear'),
            min_v=float(d.get('min_v', 0.0)),
            max_v=float(d.get('max_v', 1.0)),
        )


def _apply_curve(value: float, curve: str) -> float:
    """Aplica una curva de transformación no-lineal a un valor 0..1."""
    value = max(0.0, min(1.0, value))
    if curve == 'linear':
        return value
    elif curve == 'exp':
        return value ** 2  # exponencial: acentúa los extremos
    elif curve == 'log':
        return np.sqrt(value)  # logarítmica: suaviza
    elif curve == 'invert':
        return 1.0 - value
    else:
        return value


def _read_signal_from_context(source: str, audio_context: Dict[str, Any]) -> Optional[float]:
    """Lee una señal del audio_context, soportando índices con punto.

    Ej: 'mel_bands.3' → audio_context['norm']['mel_bands'][3].
    Si la señal no existe o no está normalizada, devuelve None.
    """
    norm = audio_context.get('norm', {})
    if not norm:
        return None

    if '.' in source:
        base, idx_str = source.rsplit('.', 1)
        try:
            idx = int(idx_str)
            arr = norm.get(base)
            if arr is not None and hasattr(arr, '__getitem__'):
                if isinstance(arr, (list, np.ndarray)):
                    if 0 <= idx < len(arr):
                        return float(arr[idx])
        except (ValueError, IndexError, TypeError):
            pass
        return None
    else:
        val = norm.get(source)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        return None


class ModulationStage(ParamStage):
    """Etapa del pipeline que aplica los param_links del clip.

    Lee los links del clip (Clip.param_links), busca cada señal en audio_context['norm'],
    aplica transformaciones (curve, gain, offset, clamp) y escribe el parámetro resultante.

    Si el clip no tiene links o una señal no existe, devuelve params sin modificar.
    """

    def apply(self, params: Dict[str, Any], clip: Any, t_ms: int,
              audio_context: Dict[str, Any]) -> Dict[str, Any]:
        """Aplica los param_links del clip.

        Fast path: si el clip no tiene links, devuelve params sin copiar.
        Si aplica, copia params una sola vez al principio.
        """
        links = getattr(clip, 'param_links', None)
        if not links:
            return params

        out = None  # copia perezosa
        for link_dict in links:
            try:
                link = ParamLink.from_dict(link_dict) if isinstance(link_dict, dict) else link_dict
                signal_val = _read_signal_from_context(link.source, audio_context)
                if signal_val is None:
                    # Señal no disponible: no tocar el parámetro
                    continue

                # Aplicar transformaciones: curve → gain/offset → clamp
                modulated = _apply_curve(signal_val, link.curve)
                modulated = modulated * link.gain + link.offset
                modulated = max(link.min_v, min(link.max_v, modulated))

                # Copiar params solo cuando vayamos a escribir
                if out is None:
                    out = dict(params)

                out[link.param] = modulated

            except Exception:
                # Un link roto no tumba todo el stage; se salta silencioso
                # (el logger se encarga en tests/user debugging).
                continue

        return out if out is not None else params
