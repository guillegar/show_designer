# ADR-003: Señales de modulación normalizadas en `actx['norm']`

**Estado:** Aceptada (se implementa en A1) · **Fecha:** 2026-06-12

## Contexto
La modulación (A1) vincula parámetros a señales del análisis. Las señales crudas tienen
rangos dispares (rms ≈ 0..0.5, centroid ≈ miles, mel_bands en dB negativos): exponerlas
crudas obligaría al usuario a adivinar gains absurdos por señal.

## Decisión
`AnalysisService` añade al audio context un dict paralelo `actx['norm']`: cada señal
escalar normalizada a 0..1 con min/max precalculados al cargar el timeseries (mismo
patrón que `rms_norm` de la Fase 5 de la auditoría). La modulación SIEMPRE lee de
`actx['norm']`; las señales crudas quedan donde están para los efectos legacy.

## Opciones consideradas
- **A. Dict paralelo `norm` (elegida)**: un solo objeto viaja por el pipeline; cero
  cambios en efectos existentes; coste = un lerp extra por señal usada.
- **B. Método aparte `get_audio_context_normalized(t)`**: dos llamadas/objetos por frame,
  riesgo de desincronización de t.
- **C. Normalizar en el ParamLink (gain/offset manuales)**: empuja el problema al usuario.

## Consecuencias
- (+) `brightness ← rms` funciona "de fábrica" con gain=1.
- (−) min/max globales de la canción: una sección muy quieta modula poco (es fiel a la
  canción; si molesta, se añadirá normalización por ventana en una fase futura).
