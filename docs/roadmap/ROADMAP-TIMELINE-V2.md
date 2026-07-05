# Timeline v2 — Análisis y propuesta de mejora

> Análisis 2026-07-05 sobre `web/src/views/Timeline.tsx` (1618 líneas) + `views/timeline/*`
> (4 módulos extraídos) + `timelineGeometry.ts` + `ClipInspector.tsx` (741) +
> `ClipDetailModal.tsx` (568). Backend: handlers de clips en `mcp_bridge.py` y
> `server/handlers/`.
>
> **Estado: ✅ COMPLETO (2026-07-05).** Las 5 fases aplicadas y verificadas en vivo,
> un commit por fase sobre `review-fixes`: A `cd11a3c` · B `07af52c` · C `8ff18ff` ·
> E (polish) · D `9f784cb`. Notas de implementación al final de cada fase.
> A3 (React.memo por fila) evaluada y DIFERIDA deliberadamente: con A1 el árbol solo
> se re-renderiza en cambios reales del modelo, y memoizar filas arriesga los
> invariantes de drag de la Fase 9 (rowRefs/pinClipEl/targets) por ganancia marginal.

## 1. Lo que ya está bien (no tocar)

- **Interacción moveable/selecto** reescrita y estable: drag XY con hit-test de rects
  medidos, resize por bordes, drag de grupo preservando disposición, Alt+drag = duplicar.
- **Drop optimista + pin imperativo** (Fase 9): el clip se queda donde se suelta en el
  mismo frame. NO volver a depender del round-trip.
- **Grid adaptativa al zoom** (densidad visual desacoplada de la granularidad del snap).
- **Zoom centrado en cursor** (Ctrl+rueda) con corrección de scrollLeft.
- Ecosistema completo: patterns, grupos colapsables, arranger, marcadores con categoría,
  waveform en ruler, ghost mode, quantize, generación por sección y show completo.

## 2. Hallazgos (por severidad)

### P0 — Rendimiento: el playhead re-renderiza TODO el árbol ~10×/s
`TimelineView` se suscribe a `s.t` (línea 37). El stream actualiza `t` a ~10 FPS →
**todo el componente (1.3k clips en el_taser) se re-renderiza 10 veces por segundo**
durante el playback, incluso sin tocar nada. Los filtros O(clips) por lane
(`clipsForLane`, `rowHeight`, `laneCount`) se recalculan en cada pasada →
O(lanes × clips × 10) por segundo.

### P1 — Mutaciones en lote = N round-trips secuenciales
- `commitMoves`: bucle `for` con un `move_clip` por clip. Mover un grupo de 40 clips =
  40 RPC + 40 bumps de `rev` (cada uno dispara refetch de listas en otros clientes).
- Borrar N clips (`Delete`): N × `delete_clip`. Pegar N: N × `add_clip` (y el undo
  granular queda raro: el snapshot solo al final, pero cada add ya persistió).
- Arranger: `duplicate_range` + `delete_range` **no atómico** — si el segundo falla,
  quedan clips duplicados.

### P1 — Dibujar no da feedback visual
En modo draw, mientras arrastras para crear un clip **no se pinta nada** (el rect
fantasma no existe; `draw.current` es solo un ref). El clip aparece tras el round-trip.
El modo cut tampoco muestra línea de tijera en hover.

### P2 — No hay "seguir al playhead"
Durante el playback la vista no hace auto-scroll (los únicos `scrollLeft` son el zoom y
el doble-clic del arranger). En una canción de 4:33 con zoom 7× el playhead se va de
pantalla en ~30 s.

### P2 — Snap incompleto
Moveable recibe `verticalGuidelines` (rejilla BPM + markers vía snapMs en creación),
pero **no `elementGuidelines`** → al arrastrar NO snapea a los bordes de otros clips
(lo estándar en DAWs). `snapMs()` tampoco se aplica al soltar un drag de Moveable
(solo las guías visuales de la rejilla).

### P2 — Sin loop de región (A/B)
`loop` del transport es un bool global (canción entera). Para componer se necesita
loopear un rango (una sección, 4 compases) mientras se itera un look.

### P3 — Deudas menores
- `cssColorToHex()` es un stub que devuelve siempre `#3a7acc` → todos los clips creados
  desde efecto base guardan el mismo color en show.json (el render lo disimula
  derivando de la familia).
- `window.prompt()` para nombre de marcador y de pattern (inconsistente con la edición
  inline del resto).
- Toasts mezclan idiomas ("clips painted", "clips pegados").
- Sin nudge por teclado de clips (flechas ±grid) ni zoom-to-selection.
- Status bar no muestra nº de seleccionados ni duración de la selección.
- Cut solo divide un clip por clic; no hay "dividir todo en el playhead".
- `barTicks` asume compás 4/4 fijo derivado de BPM (razonable aquí, documentarlo).

## 3. Propuesta por fases

### FASE A — Rendimiento (P0, la mayor ganancia) ~2h
- **A1**: extraer `<Playhead />` como componente propio que se suscribe a `t` (o mejor:
  update imperativo del `style.left` desde un `useEffect` + `stream.onState`, cero
  re-render de React). `TimelineView` deja de suscribirse a `s.t`; los usos puntuales
  (paste anchor, splitAt, "dividir en cursor") leen `useStore.getState().t` en el
  momento de la acción.
- **A2**: memoizar `Map<track, Clip[]>` (un solo pase sobre clips) y derivar
  `clipsForLane`/`laneCount`/`rowHeight` de ahí.
- **A3**: extraer `<LaneRow />` con `React.memo` — al editar 1 clip solo re-renderiza
  su fila. (Cuidado: `rowRefs`/`pinClipEl`/Moveable targets deben seguir funcionando.)
- Verificación: con el show de 1.3k clips, React DevTools profiler en playback ≈ 0
  renders/s en reposo; drag sigue fluido.

### FASE B — Mutaciones en lote atómicas (P1) ~2h
- **B1 backend**: `bulk_move_clips(moves: [{clip_id, new_start_ms, new_end_ms?,
  new_track?, new_layer?}])`, `bulk_delete_clips(clip_ids)`, `bulk_add_clips(clips)` —
  un snapshot I1 + una persistencia + un bump de rev. En `_TIMELINE_MUTATORS`.
- **B2 frontend**: `commitMoves`, delete múltiple, paste múltiple y `quantize` migran a
  las llamadas bulk (fallback al bucle si el handler no existe, para compat MCP).
- **B3**: `move_range(t0_ms, t1_ms, dest_ms)` atómico para el arranger (reemplaza
  duplicate+delete).
- Tests: 4-5 en `test_timeline_bulk.py` (atómico, conflictos, undo restaura todo).

### FASE C — Feedback de edición (P1-P2) ~2h
- **C1**: rect fantasma mientras dibujas (state local `drawPreview {lane, a, b}`
  actualizado en mousemove; se pinta como clip translúcido). Línea de tijera en hover
  con tool=cut.
- **C2**: toggle "⇥ Follow" en toolbar — auto-scroll suave cuando el playhead sale del
  viewport durante playback (patrón DAW: saltar media pantalla, no scroll continuo).
- **C3**: snap a bordes de clips vecinos — pasar `elementGuidelines` a Moveable
  (los `.clip` de las lanes visibles, excluyendo los seleccionados).
- **C4**: nudge por teclado — flechas ←/→ mueven selección ±1 paso de grid
  (Shift = ±1 compás); ↑/↓ cambian de layer. Reutiliza `commitMoves`.

### FASE D — Loop de región A/B (P2) ~2-3h, requiere backend
- **D1 backend**: `loop_range {start_ms, end_ms} | null` en el estado del transport;
  el tick hace wrap del reloj de audio al llegar a `end_ms` (seek del
  HeadlessAudioPlayer). Handler `set_loop_range`. OJO invariante mono-hilo del loop.
- **D2 frontend**: arrastrar en la mitad superior del ruler define la región (como
  Ableton); región pintada; clic en ella la quita; `L` = loop de la sección bajo el
  playhead.
- Es la fase con más riesgo (toca `tick.py`/audio player) — hacerla la última y con
  tests de seek.

### FASE E — Pulido (P3) ~1h
- `cssColorToHex` real (mapa familia→hex, o color del efecto).
- Prompts → input inline (marcador ya lo tiene al editar; usarlo también al crear)
  y mini-modal para nombre de pattern.
- Status bar: `N sel · X.Xs` cuando hay multi-selección.
- "Dividir todo en el playhead" en menú contextual de la regla.
- Unificar idioma de toasts (español).
- Zoom-to-selection (`Ctrl+E` o botón): encuadra la selección o la sección actual.

## 4. Orden y criterios

1. **A** (perf) — beneficia todo lo demás y no cambia comportamiento.
2. **B** (bulk) — reduce round-trips y arregla la atomicidad del arranger.
3. **C** (feedback) — la mejora de UX más visible día a día.
4. **E** (pulido) — barato, se puede intercalar.
5. **D** (loop A/B) — al final por riesgo backend.

Convenciones: un commit por fase, suite verde antes de pasar (982 Python + 36 Vitest),
`npx tsc --noEmit` + build, verificación en vivo con el show `el_taser` (1.3k clips),
y actualizar CLAUDE.md + `docs/usage/ui-guide.md` al cerrar cada fase (REGLA PERMANENTE).

Invariantes a respetar: I1 (undo por snapshot), drop optimista + `pinClipEl` +
`draggingRef` (Fase 9 — NO regresionar), mono-hilo del tick loop, token monótono en
`refreshClips`.
