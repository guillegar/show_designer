"""
micro_events.py — Micro-eventos: disparos puntuales dentro de un clip.
(ROADMAP v2, Fase A4)

Un MicroEvent es un override de parámetros que se activa durante una ventana
corta (default 100 ms ≈ 3 frames @ 30 FPS) en un instante relativo al clip.
Ejemplo: un flash extra de brightness=1.0 exactamente en el beat 3 del clip.

MicroEventStage implementa el contrato ParamStage de param_pipeline.py y se
registra en session.py como tercer stage (tras modulación y automatización).
El orden importa: los micro-eventos tienen prioridad sobre ambos (se aplican al final).

Fast path: si el clip no tiene eventos, devuelve params sin copiar (cero allocs).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from uuid import uuid4


@dataclass
class MicroEvent:
    """Override puntual de parámetros dentro de un clip."""
    uid: str = field(default_factory=lambda: uuid4().hex[:12])
    t_ms_rel: int = 0          # tiempo relativo a clip.start_ms
    duration_ms: int = 100     # ventana de activación
    params_override: Dict[str, Any] = field(default_factory=dict)

    def is_active_at(self, clip_elapsed_ms: int) -> bool:
        """True si el instante clip_elapsed_ms cae dentro de la ventana."""
        return self.t_ms_rel <= clip_elapsed_ms < self.t_ms_rel + self.duration_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "t_ms_rel": self.t_ms_rel,
            "duration_ms": self.duration_ms,
            "params_override": dict(self.params_override),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MicroEvent":
        return cls(
            uid=d.get("uid") or uuid4().hex[:12],
            t_ms_rel=int(d.get("t_ms_rel", 0)),
            duration_ms=int(d.get("duration_ms", 100)),
            params_override=dict(d.get("params_override", {})),
        )


class MicroEventStage:
    """ParamStage que aplica micro-eventos activos en el instante t_ms.

    Orden en el pipeline: modulación (A1) → automatización (A2) → micro-eventos (A4).
    Los micro-eventos tienen prioridad máxima sobre mod y auto para ese instante.
    """

    def apply(self, params: Dict[str, Any], clip: Any, t_ms: int,
              audio_context: Dict[str, Any]) -> Dict[str, Any]:
        events: List[Any] = getattr(clip, "events", [])
        if not events:
            return params  # fast path: sin micro-eventos, cero allocs

        clip_elapsed = t_ms - clip.start_ms
        merged: Dict[str, Any] | None = None

        for ev_d in events:
            ev = MicroEvent.from_dict(ev_d) if isinstance(ev_d, dict) else ev_d
            if ev.is_active_at(clip_elapsed):
                if merged is None:
                    merged = dict(params)   # primera copia al primer hit
                merged.update(ev.params_override)

        return merged if merged is not None else params
