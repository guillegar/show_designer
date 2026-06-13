# ADR-004: Política de mezcla de channel effects (Moving Heads)

**Fecha**: 2026-06-13  
**Estado**: Aceptado  
**Fase**: G3 — Moving heads pan/tilt en el timeline

---

## Contexto

Un fixture moving head tiene canales DMX físicos (pan, tilt, color_wheel, gobo...).
El timeline puede tener múltiples clips activos simultáneamente que afecten al mismo
fixture y canal: clips en layers distintos, clips en modo global, etc.

La pregunta es: **¿cómo se combina el resultado de múltiples clips que controlan el
mismo canal en el mismo instante?**

Para fixtures LED pixel, la regla ya estaba definida: `np.maximum` (el más brillante
gana). Para channel effects de movers, la semántica es diferente porque pan=0.9 y
pan=0.1 a la vez no tiene sentido promediarlos ni maximizarlos.

---

## Decisión

**LAST_WINS (LTP — Latest Takes Precedence)**: el clip con el layer más alto pisa al
de layer inferior. Si dos clips tienen el mismo layer, el que empezó después (mayor
`start_ms`) pisa al anterior.

Implementado en `ShowEngine.render_channels_for_fixture()`:
- Los clips se ordenan por `(layer, start_ms)` ascendente.
- El buffer DMX se sobreescribe (no se acumula), así el último iterado gana.
- Un clip con `layer=1` siempre pisa a `layer=0`, independientemente de las
  posiciones pan/tilt que genere.

---

## Alternativas consideradas

1. **Promedio ponderado** — difícil de predecir visualmente; el head nunca llega al
   punto pedido por ningún clip; descartado.
2. **np.maximum** — tiene sentido para intensidad pero no para posición; un mover que
   siempre fuera al máximo de dos posiciones sería imprevisible; descartado.
3. **Mezcla por crossfade** — requiere alpha explícito por clip; añade complejidad sin
   ganancia clara para el caso de uso; diferido.

---

## Consecuencias

- **Positivas**: comportamiento predecible, idéntico a consolas profesionales (GrandMA,
  EOS usan LTP para canales no-intensidad). El usuario sabe que el clip de layer mayor
  "manda".
- **Negativas**: no hay crossfade nativo entre clips de posición. Si se quiere fundido,
  hay que usar curvas de automatización (A2) sobre los parámetros del efecto.
- **Documentación**: los clips de canal deben anotarse con el layer explícito; layer=0
  por defecto (base/background).
