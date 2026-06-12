# ADR-001: Pipeline de stages para parámetros de clips

**Estado:** Aceptada · **Fecha:** 2026-06-12 (Fase F0) · **Decide:** equipo + usuario

## Contexto
Las features del ROADMAP v2 (modulación, automatización, micro-eventos, macros) transforman
los parámetros que recibe un efecto. Sin un punto único, cada una parchearía el bucle de
render a su manera (espagueti) o peor: la firma de `Effect.render` (rompe 51 efectos + plugins).

## Decisión
Función pura `resolve_params(clip, t_ms, actx, stages)` en `src/core/param_pipeline.py`,
interpuesta en `session.compute_frame` entre la resolución del preset y `effect.render`.
Las features se registran como `ParamStage`s ordenados en `session.param_stages`.
Orden canónico: modulación → automatización → micro-eventos → macros
(lo dibujado a mano pisa lo automático; lo del directo pisa todo).

## Opciones consideradas
- **A. Pipeline de stages (elegida)**: bajo acoplamiento, efectos intactos, testeable puro.
- **B. Que cada efecto lea sus links/curvas**: rompe el contrato de efectos, duplica lógica ×51.
- **C. Subclasificar Clip por feature**: explosión de clases, persistencia frágil.

## Consecuencias
- (+) Los efectos JAMÁS se enteran de las features nuevas; parity garantizado sin stages.
- (+) Cada stage se testea en aislamiento.
- (−) Un dict de params puede copiarse hasta 4 veces por clip/frame en el peor caso →
  mitigado con el fast path (sin stages aplicables = cero copias) y el bench I5.
- Un stage roto se salta silenciosamente (el render nunca cae) — el stage es responsable
  de su propio logging.
