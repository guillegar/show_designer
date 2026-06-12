"""
param_pipeline.py — Punto de extensión ÚNICO para transformar parámetros de clips.
(ROADMAP v2, Fase F0.1)

Antes, el render hacía: `effect.render(t, frame, actx, **clip.params)` — los params
del clip iban DIRECTOS al efecto. Este módulo interpone una función pura:

    params_efectivos = resolve_params(clip, t_ms, audio_context, stages)

Las features futuras (modulación A1, automatización A2, micro-eventos A4, macros C2)
se implementan como `ParamStage`s que se registran en la sesión — NUNCA tocando la
firma de los efectos ni el bucle de render.

Reglas para implementar un stage (leer antes de escribir uno):
  1. `apply()` es PURA: no muta `params` (si va a escribir, copia primero:
     `out = dict(params)`), no toca red/disco/UI, no guarda estado entre frames
     salvo caches invalidables.
  2. Si el stage no aplica a este clip, devuelve `params` TAL CUAL (sin copiar) —
     así el fast path se conserva.
  3. Los stages se ejecutan en el orden de la lista. Orden canónico del proyecto:
     modulación (A1) → automatización (A2) → micro-eventos (A4) → macros (C2).
     (El preset se resuelve ANTES del pipeline, en `_resolve_clip_effect`,
     porque además de params puede cambiar el effect_id.)

Este módulo NO importa nada de server/, web/, fastapi ni efectos concretos
(regla de oro: core agnóstico).
"""
from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class ParamStage(Protocol):
    """Contrato de una etapa del pipeline de parámetros."""

    def apply(self, params: Dict[str, Any], clip: Any, t_ms: int,
              audio_context: Dict[str, Any]) -> Dict[str, Any]:
        """Devuelve los params transformados (o `params` sin tocar si no aplica)."""
        ...


def resolve_params(clip: Any, t_ms: int, audio_context: Dict[str, Any],
                   stages: List[ParamStage],
                   base_params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Devuelve los parámetros EFECTIVOS del clip en el instante t_ms.

    Args:
        clip: el Clip (se pasa entero: los stages leen uid/track/start_ms/links...).
        t_ms: tiempo absoluto del timeline en ms.
        audio_context: dict de señales de análisis en t (rms, flux, mel_bands...).
        stages: lista ordenada de ParamStage registrados en la sesión.
        base_params: params de partida ya resueltos (p.ej. los del preset si el
            clip tiene `preset_id`). Si es None, se usan `clip.params`.

    FAST PATH (rendimiento, invariante del ROADMAP): sin stages, devuelve el dict
    de entrada SIN COPIAR (cero allocs). A 30 FPS × N clips, copiar "por si acaso"
    es churn de GC gratuito. El test verifica identidad de objeto.
    """
    params = base_params if base_params is not None else clip.params
    if not stages:
        return params
    out = params
    for stage in stages:
        try:
            res = stage.apply(out, clip, t_ms, audio_context)
        except Exception:
            # Un stage roto NUNCA tumba el render: se salta y se sigue.
            # (El stage es responsable de loguear con throttle si lo necesita.)
            continue
        if res is not None:
            out = res
    return out
