"""
automation.py — Curvas de automatización (ROADMAP v2, Fase A2).

Pistas de automatización tipo FL Studio/Ableton: dibujás una curva de un parámetro
(ej. 'hue', 'brightness') a lo largo del timeline con puntos, y el valor se aplica
a los clips/tracks que cubra.

Modelo de datos:
  AutomationPoint — un punto en la curva (t_ms, value, shape)
  AutomationLane — una pista de automatización (uid, target, points[], enabled)
  parse_target() — parseador robusto de targets ('clip:<uid>:<param>', etc.)

Lógica:
  AutomationStage — stage del pipeline que aplica los valores de las lanes
  Orden: después de modulación (A1), las curvas mandan

Módulo puro: SIN imports de server/, web/, fastapi.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import asdict, dataclass, field
from typing import Any

from src.core.param_pipeline import ParamStage


@dataclass
class AutomationPoint:
    """Un punto en la curva de automatización.

    Attrs:
        t_ms: tiempo absoluto del timeline (ms)
        value: valor 0..1 normalizado
        shape: interpolación ('linear', 'hold', 'smooth' cosine)
    """
    t_ms: int
    value: float
    shape: str = 'linear'

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AutomationPoint:
        return cls(
            t_ms=int(d['t_ms']),
            value=float(d['value']),
            shape=d.get('shape', 'linear'),
        )


@dataclass
class Target:
    """Parsed target de una lane de automatización.

    Ej: 'clip:<uid>:<param>' → target_type='clip', uid=..., param=param
        'track:<n>:<param>' → target_type='track', track_id=n, param=param
        'master:brightness' → target_type='master', param=brightness
    """
    target_type: str  # 'clip', 'track', 'master'
    param: str
    uid: str | None = None       # para clip
    track_id: int | None = None  # para track


def parse_target(target_str: str) -> Target | None:
    """Parsea un target string a Target struct.

    Ej:
      'clip:abc123def456:brightness' → clip abc123def456, param brightness
      'track:3:speed' → track 3, param speed
      'master:hue' → master, param hue
    """
    if not target_str or ':' not in target_str:
        return None
    parts = target_str.split(':')
    try:
        if len(parts) >= 3 and parts[0] == 'clip':
            uid = parts[1]
            param = ':'.join(parts[2:])  # param puede tener ':' (poco probable pero permitir)
            return Target(target_type='clip', uid=uid, param=param)
        elif len(parts) >= 3 and parts[0] == 'track':
            track_id = int(parts[1])
            param = ':'.join(parts[2:])
            return Target(target_type='track', track_id=track_id, param=param)
        elif len(parts) >= 2 and parts[0] == 'master':
            param = ':'.join(parts[1:])
            return Target(target_type='master', param=param)
    except (ValueError, IndexError):
        pass
    return None


@dataclass
class AutomationLane:
    """Una pista de automatización.

    Attrs:
        uid: identificador único (uuid4 hex[:12])
        target: string parseable ('clip:<uid>:<param>', 'track:0:speed', 'master:brightness')
        points: lista de AutomationPoint, SIEMPRE ordenada por t_ms
        enabled: si False, no se aplica
    """
    uid: str
    target: str
    points: list[dict[str, Any]] = field(default_factory=list)  # persistidos como dicts
    enabled: bool = True

    def value_at(self, t_ms: int) -> float | None:
        """Interpola el valor en t_ms.

        Antes del primer punto → primer valor
        Después del último → último valor
        En medio → interpola según shape
        """
        if not self.points:
            return None

        points = [AutomationPoint.from_dict(p) if isinstance(p, dict) else p
                 for p in self.points]
        if not points:
            return None

        # Puntos siempre ordenados
        times = [p.t_ms for p in points]
        idx = bisect_right(times, t_ms)

        if idx == 0:
            # Antes del primer punto: usar su valor
            return points[0].value
        if idx > len(points):
            # Después del último: usar su valor
            return points[-1].value

        # Buscar si exactamente estamos en un punto
        p0_idx = idx - 1
        if p0_idx < len(points) and points[p0_idx].t_ms == t_ms:
            return points[p0_idx].value

        # Interpolar entre points[idx-1] y points[idx]
        if idx >= len(points):
            return points[-1].value

        p0 = points[idx - 1]
        p1 = points[idx]

        # Caso especial: hold (mantener el valor anterior hasta el siguiente punto)
        if p0.shape == 'hold':
            return p0.value

        # Interpolación lineal o smooth (cosine)
        t0, t1 = p0.t_ms, p1.t_ms
        if t1 == t0:
            return p0.value
        w = (t_ms - t0) / (t1 - t0)

        # Smooth: cosine interpolation (más suave que lineal)
        if p0.shape == 'smooth':
            w = 0.5 * (1.0 - math.cos(math.pi * w))

        return p0.value + (p1.value - p0.value) * w

    def to_dict(self) -> dict[str, Any]:
        return {
            'uid': self.uid,
            'target': self.target,
            'points': [p.to_dict() if isinstance(p, AutomationPoint) else p
                      for p in self.points],
            'enabled': self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AutomationLane:
        points = [AutomationPoint.from_dict(p) if isinstance(p, dict) else p
                 for p in d.get('points', [])]
        return cls(
            uid=d['uid'],
            target=d['target'],
            points=[p.to_dict() if isinstance(p, AutomationPoint) else p
                   for p in points],
            enabled=d.get('enabled', True),
        )


class AutomationStage(ParamStage):
    """Etapa del pipeline que aplica las lanes de automatización.

    Lee las lanes del timeline, busca las que aplican a este clip/track,
    evalúa sus valores en t_ms y escribe los parámetros.

    Orden en el pipeline: DESPUÉS de modulación (A1). Las curvas mandan.
    """

    def __init__(self, get_automation_lanes=None):
        """get_automation_lanes: callable que devuelve lista de AutomationLane.

        Se pasa al construir porque AutomationStage es agnóstico del timeline.
        """
        self.get_automation_lanes = get_automation_lanes or (lambda: [])

    def apply(self, params: dict[str, Any], clip: Any, t_ms: int,
              audio_context: dict[str, Any]) -> dict[str, Any]:
        """Aplica las lanes de automatización que aplican a este clip."""
        lanes = self.get_automation_lanes()
        if not lanes:
            return params

        clip_uid = getattr(clip, 'uid', None)
        clip_track = getattr(clip, 'track', None)
        out = None

        for lane in lanes:
            if not lane.enabled:
                continue

            target = parse_target(lane.target)
            if target is None:
                continue

            # Determinar si esta lane aplica a este clip
            applies = False
            if target.target_type == 'clip' and target.uid == clip_uid:
                applies = True
            elif target.target_type == 'track' and target.track_id == clip_track:
                applies = True
            # master no aplica a clips individuales (B2)

            if not applies:
                continue

            # Evaluar el valor de la lane
            val = lane.value_at(t_ms)
            if val is None:
                continue

            # Escribir el parámetro
            if out is None:
                out = dict(params)
            out[target.param] = val

        return out if out is not None else params
