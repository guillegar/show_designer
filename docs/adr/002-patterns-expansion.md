# ADR-002: Patterns por expansión, no por copia

**Estado:** Aceptada (se implementa en A3) · **Fecha:** 2026-06-12

## Contexto
Los patterns (A3) deben comportarse como en FL Studio: editar el pattern actualiza todas
sus instancias (enlace vivo). Hay dos formas: copiar los clips al instanciar, o expandir
las instancias al renderizar.

## Decisión
**Expansión en render**: `PatternInstance` solo guarda `pattern_uid + start_ms +
track_offset`. En `compute_frame`, las instancias se expanden a clips efímeros (cacheados
por contador de revisión). Los clips efímeros NO aparecen en `list_clips`, no son
seleccionables ni editables — la unidad de interacción es la instancia.

## Opciones consideradas
- **A. Expansión (elegida)**: enlace vivo gratis, documento pequeño, sin sincronización.
- **B. Copia + resincronización al editar el pattern**: enlace vivo requiere reconciliar
  N copias (bugs de divergencia garantizados, mismo error que las 4 copias del viewer3d).

## Consecuencias
- (+) "Editar pattern = cambian todas" sale de la arquitectura, no de código de sync.
- (−) El bucket index debe indexar también clips expandidos; cache con invalidación por
  revisión (puntos a vigilar en review).
- (−) Editar UN uso suelto requiere `dissolve_instance` explícito (decisión de UX asumida).
