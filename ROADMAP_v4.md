# ROADMAP v4 — "La Consola"

**Objetivo**: elevar Show Designer del nivel "herramienta profesional de producción" al nivel
**consola de iluminación profesional** — comparable a grandMA Dot2 / ETC Eos lite — con editor
de fixtures visual, soporte DMX completo, pixel mapping, timeline de nivel DAW, grabación en
vivo, modo programmer, exportación profesional, visualización 3D avanzada, API pública REST y
multiusuario básico.

**Punto de partida**: v2.0 · 883 tests verdes · ROADMAP v2+v3 COMPLETOS · tag `v2.0-roadmap-v3`.
31 fases ejecutadas.

**TAG OBJETIVO**: `v3.0-roadmap-v4`

**Modelo de ejecución**: mismo que v2/v3 (ver §Reglas del juego a continuación). Los invariantes
I1–I5 y el checklist de cierre siguen vigentes. Este documento añade I6 y una regla v4 adicional.

**Audiencia**: equipo mid/junior. Cada fase tiene el PORQUÉ, el CÓMO y el criterio de
aceptación redactados para que no haya que asumir nada. Si algo no se entiende, preguntar
ANTES de programar.

---

## Mapa de los seis bloques

| Bloque | Quién lo usa | Qué añade |
|--------|-------------|-----------|
| **I — TIMELINE PRO** | El compositor avanzado | Grabación en vivo, marcadores con nombre, grupos colapsables, vista arranger, exportación PDF/CSV |
| **J — RIG PRO** | El técnico de iluminación | Editor de patch visual drag-and-drop, DMX completo por canal, biblioteca GDTF, test de fixtures avanzado |
| **K — VISUALIZACIÓN** | El diseñador y el técnico | Viewer 3D con posicionamiento 3D, pixel mapping imagen/vídeo, preview 2D en tiempo real |
| **L — RED Y COLABORACIÓN** | El equipo de producción | API REST pública, webhooks de eventos, modo multiusuario básico |
| **M — INTELIGENCIA** | El diseñador y el improvisador | Tap BPM + detección de tonalidad, generación automática de show, historial de gestos |
| **N — PLATAFORMA** | La comunidad y el equipo | Marketplace de plugins, backup y restauración completa de show |

### Grafo de dependencias v4

```
I1 (grabación) ── independiente (usa macros de C2 y lanes de A2)
I2 (marcadores) ── independiente
I3 (grupos) ──── independiente (BarGroups ya existen en el modelo)
I4 (arranger) ── depende de I2 (las secciones se calculan desde los marcadores)
I5 (export) ──── depende de B3 (render.npz para el CSV DMX)
J1 (patch visual) ── independiente
J2 (DMX canal) ─── depende de J1 (editor visual) y G3 (ChannelEffects ya existentes)
J3 (GDTF browser) ─ depende de J1 (add_fixture_from_gdtf al rig)
J4 (test avanzado) ─ depende de E4 (identify_fixture base a ampliar)
K1 (viewer 3D) ──── depende de J1 (posiciones 3D por fixture en rig_layout.json)
K2 (pixel map) ──── independiente (nuevo tipo de efecto en plugins/)
K3 (preview 2D) ─── independiente (consume /ws/stream ya existente)
L1 (API REST) ───── independiente
L2 (webhooks) ───── puede implementarse independiente; reutiliza eventos de E1/tick
L3 (multiusuario) ─ depende de L1 (el token de API key se amplía a rol)
M1 (tap + key) ──── depende de G2 (TempoSyncService ya existe — ampliar)
M2 (generate show) ─ depende de M1 (análisis de sección) y A2 (lanes para clips)
M3 (historial) ───── independiente
N1 (marketplace) ─── depende de H1 (SDK harness para validar plugins descargados)
N2 (backup) ──────── depende de H2 (conoce la estructura del bundle del instalador)
```

---

## 0. Reglas del juego (leer antes de CUALQUIER fase)

Estas reglas no son opcionales. Son las que han mantenido este proyecto sano durante 31 fases
y son INNEGOCIABLES:

1. **Un commit por fase, sobre rama propia.** Formato del mensaje:
   `roadmap-v4 fase <ID>: <resumen>` (ej. `roadmap-v4 fase I1: grabación en vivo de macros`).
   Si una fase necesita más de un commit (frontend+backend), squash antes de merge.
2. **La documentación se actualiza EN el mismo commit.** Mínimo: la entrada de estado en
   este ROADMAP_v4.md (PROPUESTO → APLICADA + fecha + nota) y la sección de CLAUDE.md que
   corresponda. Si la fase añade conceptos nuevos, añadir doc en `docs/`.
3. **Independencia de módulos — la regla de oro del proyecto:**
   - `src/core/` NO conoce red, ni FastAPI, ni el navegador, ni rutas de archivos de proyecto.
     Recibe datos, devuelve datos. Si tu módulo de core necesita un `import fastapi`, está
     mal diseñado: para.
   - Los efectos reciben `(elapsed_time, bars_state, audio_context, **params)` y devuelven
     un array RGB. PUNTO. Cualquier feature nueva (modulación, automatización) se aplica
     FUERA del efecto, transformando sus `params` antes de llamar a `render()`.
   - El frontend NO recalcula luces. Consume el frame binario del `/ws/stream` y manda
     órdenes por JSON-RPC. Si tu feature de UI necesita replicar lógica del motor en TS,
     el diseño está mal: expón un handler nuevo en el dispatcher.
   - JSON-RPC es un CONTRATO PÚBLICO (lo usa Claude vía MCP además de la web): los handlers
     existentes NO cambian de firma. Features nuevas = handlers nuevos.
4. **Tests primero en el core.** Cada módulo nuevo de `src/core/` o `server/` nace con su
   `tests/test_<modulo>.py`. La suite (883+) queda verde en cada commit. Si tocas web:
   `npx tsc --noEmit` limpio y `cd web && npm run build` antes de cerrar (sin build, el
   usuario no ve nada en :8000).
5. **Persistencia versionada.** `show.json` lleva `version`. Si tu fase añade campos:
   incrementa la versión, escribe la migración en `Timeline.load()` (cargar un show viejo
   NUNCA puede fallar ni perder datos), y añade un test de carga de show legacy.
6. **Guardado atómico** (ya existe: `.tmp` + `os.replace`) para cualquier archivo nuevo
   que se persista.
7. **Cuando dudes de una decisión que afecta a todo el sistema, pregunta al usuario**
   (regla de la casa). Las decisiones locales, tómalas y documenta el porqué.
8. **Decisiones estructurales → mini-ADR en `docs/adr/`** (plantilla: contexto, opciones,
   decisión, consecuencias; media página basta).
9. **[v4] Todo handler nuevo tiene su endpoint REST equivalente en L1 (si aplica).** Una vez
   implementada L1, cualquier fase posterior que añada un handler público debe añadir también
   el endpoint REST correspondiente en `/api/v1/`. Quedan exentos los handlers puramente
   internos: `preview_effect_frame`, `get_effect_schema`, `auth_get_role`, etc.

### 0.5 Invariantes transversales (aplican a TODAS las fases)

- **I1 — Undo = documento completo.** El undo del server es por snapshot. Toda entidad
  nueva persistible (marcadores con nombre, posiciones 3D, config de pixel map) ENTRA en el
  snapshot desde el día 1, o el undo corrompe el documento al mezclar estados parciales.
  Test obligatorio: mutar la entidad nueva → undo → estado idéntico.
- **I2 — Integridad referencial con borrado en cascada.** Borrar un clip borra sus lanes de
  automatización y links; borrar un fixture borra sus referencias en rig_layout.json.
  Prohibido dejar huérfanos en show.json o rig.json.
- **I3 — Mutadores devuelven la entidad mutada.** Todo handler nuevo devuelve el objeto
  resultante para que el frontend parchee el store de forma OPTIMISTA; `refreshClips` queda
  como reconciliación, no como única vía.
- **I4 — Nada bloquea el tick loop.** El tick corre a 30 FPS en el event loop. Cualquier
  trabajo > ~10 ms (render offline, carga de imagen, generación de show, llamada HTTP) va a
  un executor o se trocea con awaits. Si tu handler hace un bucle sobre toda la canción,
  está mal.
- **I5 — Presupuesto de rendimiento del frame**: `compute_frame(t)` p95 < 33 ms en la
  escena de referencia de 30 clips activos. Regresión > 20 % bloquea el merge.
- **I6 — Ningún handler bloquea más de 50 ms; trabajo pesado siempre en executor.**
  I4 ya prohíbe bloquear el tick. I6 formaliza el mismo contrato para TODOS los handlers
  del dispatcher: si el cuerpo del handler puede tardar > 50 ms (PDF, ZIP, análisis de
  imagen, llamada HTTP, generación de show), delegar a
  `asyncio.get_event_loop().run_in_executor(None, ...)`. Verificar con
  `time.perf_counter()` en los tests de handlers pesados.

---

# BLOQUE I — TIMELINE PRO

> *Llevar el timeline al nivel de un DAW profesional.*

## I1 — Grabación en vivo de macros (~2 días, Sonnet) ✅ APLICADA 2026-06-14

**Qué**: mientras suena el show, cada movimiento de macro (brightness, speed, hue, strobe)
se graba como lane de automatización (A2) sobre el tiempo actual. Al parar, el usuario tiene
una curva editable.

**Por qué**: el operador en directo ya ajusta macros con C2. Pero esas acciones se pierden.
Con REC activo, cada gesto se convierte en una `AutomationLane` permanente — convirtiendo el
directo en diseño.

### Modelo de datos

```python
# En ShowSession:
session._recording: bool = False
session._recorded_points: dict[str, list[tuple[int, float]]]
#   → {"master:brightness": [(t_ms, value), ...], ...}
```

Cuando `_recording` es True, `set_macro(name, value)` además de aplicar inmediatamente
añade `(session.t_ms, value)` a `_recorded_points[f"master:{name}"]`.

Al llamar a `stop_record()`:
- Para cada target en `_recorded_points`, crea o amplía una `AutomationLane` (A2) con
  los puntos grabados. Shape interpolada: `linear` entre puntos.
- Limpia `_recorded_points` y pone `_recording = False`.
- Devuelve `{ok: true, lanes_recorded: N}`.

### Backend

Handlers en `dispatcher.py`:
- `start_record()` → `{ok, t_ms}` — activa `_recording` y reinicia el buffer de puntos.
- `stop_record()` → `{ok, lanes_recorded: int}` — idempotente si no hay grabación activa.

### Frontend

- Botón ⏺ REC rojo en la `MacroStrip` de `Live.tsx` (junto al STOP).
- Al activar REC: borde pulsante rojo en la strip; barra inferior indica tiempo grabado.
- Al parar REC: notificación toast "N lanes grabadas" + abre el editor de automatización
  con las lanes recién creadas destacadas.
- Estado `recording` propagado por el stream: `{type: "recording_state", active: bool}`.

### Tests

`tests/test_live_record.py` (mínimo 5):
- `start_record` → `session._recording` True.
- `set_macro` durante REC añade punto a `_recorded_points`.
- `stop_record` crea `AutomationLane` con los puntos grabados.
- `stop_record` es idempotente (segunda llamada sin grabar no lanza).
- `stop_record` devuelve `lanes_recorded` con el conteo correcto.
- Undo de `stop_record` elimina las lanes creadas (I1).

**Aceptación**: pulso REC, muevo el slider de brightness de 0 a 1 durante 4 s, paro REC →
aparece una `AutomationLane` de `master:brightness_mul` con la curva de mis gestos en el editor.
**Commit**: `roadmap-v4 fase I1: grabación en vivo de macros`.

**Implementación (2026-06-14)**:
- `session.py`: `_recording`, `_record_start_ms`, `_recorded_lanes`, `_record_last_ms`;
  `_maybe_record_macros(t_ms)` con throttle 50ms llamado al final de ambas rutas de
  `compute_frame`; `automation` añadido a `get_extra`/`restore_extra` del UndoManager (I1).
- `dispatcher.py`: handlers `start_record`, `stop_record`, `get_record_state` registrados en
  `_LOCAL`. `stop_record` llama `snapshot()` antes de crear las lanes.
- `tick.py`: evento `record_state` emitido cada ~500ms durante grabación.
- `web/src/api/stream.ts`: tipo `RecordStateEvent` + subscriber `onRecordState`.
- `web/src/views/Live.tsx`: botón ⏺ REC / ⏹ STOP REC en `MacroStrip` (parpadeo rojo al
  grabar); toast al parar con número de lanes creadas; `ToastContainer`.
- `tests/test_macro_record.py`: 8 tests, todos verdes. Suite total: 885 tests verdes.

---

## I2 — Marcadores de timeline con nombre y color (~1 día, Haiku) ✅ APLICADA 2026-06-14

**Qué**: los `CuePoint` ya existen como marcadores pasivos. Ampliarlos con nombre editable,
color y categoría (intro/verso/estribillo/bridge/outro/custom).

**Por qué**: la vista arranger (I4) necesita marcadores con nombre para definir secciones.
Y el operador necesita ver de un vistazo la estructura del show en la regla sin recurrir
al panel de análisis.

### Modelo de datos

Ampliar `CuePoint` en `src/core/timeline_model.py`:

```python
@dataclass
class CuePoint:
    t_ms: int
    label: str = ""           # existente (etiqueta corta)
    name: str = ""            # NUEVO — nombre largo editable
    color: str = "#888888"    # NUEVO — hex color (#rrggbb)
    category: str = "custom"  # NUEVO — "intro"|"verso"|"estribillo"|"bridge"|"outro"|"custom"
```

Migración tolerante en `Timeline.load()`: campos `name/color/category` con defaults si
ausentes. No incrementar versión de schema (campos opcionales con default).

### Backend

Handlers:
- `cue_point_update(t_ms: int, name: str, color: str, category: str)` → devuelve el
  `CuePoint` actualizado (invariante I3).
- `list_cue_points(category: str = None)` → lista filtrada por categoría (o toda si None).

### Frontend

- En la regla del timeline: marcadores muestran su nombre truncado. Color del triángulo
  del marcador según el campo `color`. Tooltip con nombre completo + categoría.
- Clic en marcador → inline edit del nombre (input HTML superpuesto). Enter para confirmar.
- Clic derecho en marcador → menú con color picker + selector de categoría.
- Toolbar: filtro de categoría — chip activo filtra la visibilidad en la regla.

### Tests

`tests/test_cue_points_v2.py`:
- Roundtrip nombre + color en show.json (serialización/deserialización).
- Filtro por categoría devuelve solo los marcadores de esa categoría.
- Show sin campos nuevos carga con defaults (migración tolerante).
- `cue_point_update` devuelve el objeto actualizado (I3).
- Undo de `cue_point_update` restaura estado anterior (I1).

**Aceptación**: hago doble clic en un marcador → escribo "Estribillo" → Enter; el marcador
muestra el nombre en el color elegido. Filtro por "estribillo" → solo se ven esos marcadores.
**Commit**: `roadmap-v4 fase I2: marcadores de timeline con nombre y color`.

**Implementación (2026-06-14)**:
- `src/core/timeline_model.py`: `Marker` dataclass (`t_ms`, `name`, `color`, `category`);
  `_VALID_MARKER_CATEGORIES`; `Timeline.markers` persistido en `to_dict`/`from_dict`/`save`/`load`;
  migración tolerante (campo ausente → lista vacía).
- `server/session.py`: `markers` añadido a `get_extra`/`restore_extra` del UndoManager (I1).
- `server/dispatcher.py`: 4 handlers `list_markers`/`add_marker`/`delete_marker`/`update_marker`
  en `_LOCAL` con prioridad sobre el bridge; `add/delete/update_marker` en `_TIMELINE_MUTATORS`.
- `web/src/store.ts`: `MarkerCategory` type + `category` añadido a `Marker`.
- `web/src/views/Timeline.tsx`: filtro de categoría en toolbar; edición inline de nombre (clic
  en el label del marcador → input); menú contextual clic-derecho con color picker + selector de
  categoría + botón borrar.
- `web/src/styles-views.css`: `.marker-edit-input`, `.marker-ctx-menu`, `.marker-ctx-row`.
- `tests/test_cue_points_v2.py`: 8 tests, todos verdes. Suite total: 893 tests verdes.

---

## I3 — Grupos colapsables en timeline (~2 días, Sonnet) ✅ APLICADA 2026-06-14

**Implementación**: `collapsedGroups: Set<string>` en localStorage + `toggleGroupCollapse`.
`lanes` useMemo inserta `group-header` y `group-collapsed` por grupo primario. tl-heads y
tl-lanes renderizan cabecera colapsable y miniatura SVG de clips. Backend: `get_group_clips`
en dispatcher.py. CSS: `.tl-group-hdr`, `.tl-grp-sep`, `.tl-grp-toggle`. Tests: 5 en
`test_groups_collapse.py`. Suite total: 903 tests verdes.

**Qué**: los `BarGroup` existen en el modelo pero no son colapsables en la UI. Clic en la
cabecera de un grupo → colapsa sus pistas a 1 fila resumida con miniatura visual agregada.

**Por qué**: timelines con 10+ pistas son imposibles de navegar sin agrupar. Esta feature
es la diferencia entre un timeline básico y uno de DAW profesional.

### Modelo de datos

El estado de colapso vive en `localStorage` (no en show.json) — es preferencia visual,
no documento:

```typescript
// web/src/store.ts
collapsedGroups: Set<string>  // group_ids colapsados
```

### Backend

Sin cambios de backend — la colapsación es puramente visual. Los clips del grupo siguen
renderizándose con normalidad.

Handler de apoyo (si no existe): `get_group_clips(group_id: str)` → lista de clips del
grupo (para generar la miniatura en el cliente).

### Frontend

- Cabecera de grupo en `Timeline.tsx`: botón ▶/▼ para colapsar/expandir.
- Cuando colapsado: la fila del grupo muestra una miniatura SVG agregada — líneas de color
  por clip, proporcionales a su duración, mezcladas en una sola fila.
- La miniatura se calcula en el cliente: iterar los clips del grupo visibles en el viewport.
- Al reproducir, todos los clips del grupo siguen activos (solo cambia la UI).
- Estado de colapso persiste en `localStorage` entre sesiones.

### Tests

`tests/test_groups_collapse.py` (Python — verificar que `get_group_clips` es correcto):
- `get_group_clips` devuelve solo clips del grupo especificado.
- Clips del grupo "colapsado" (desde perspectiva del modelo) no se eliminan del timeline.
- `compute_frame` con clips dentro de un grupo colapsado produce el mismo resultado que
  sin colapsar.

`web/src/timeline.test.ts` (Vitest):
- Colapsar grupo → solo 1 fila visible para ese grupo.
- Expandir → N filas visibles con los clips originales.
- Estado de colapso persiste en localStorage (mock de localStorage).

**Aceptación**: timeline con 3 grupos; colapso el grupo "Estribillo" → sus 3 pistas
desaparecen en 1 fila de miniatura; el show sigue sonando correctamente.
**Commit**: `roadmap-v4 fase I3: grupos colapsables en timeline`.

---

## I4 — Vista Arranger: secciones como bloques (~3 días, Opus) ✅ APLICADA 2026-06-14

**Implementación**: `_h_delete_range` en dispatcher.py (borra clips solapados con el intervalo);
`delete_range` añadido a `_TIMELINE_MUTATORS` y `_LOCAL`. Frontend: estado `arrangerMode` +
`dragSecIdx` + `dragInsertMs` + `arrangerRef`. `arrangerSections` useMemo calculado desde
markers I2. Tira visual `.tl-arranger` entre ruler y tl-scroll; bloques `.arr-block` con drag
→ `duplicate_range` + `delete_range`. Botón "⊞ Arr" en toolbar. Doble-clic → scroll al
inicio de sección y cierra arranger. CSS: `.tl-arranger`, `.arr-block`, `.arr-drop-line`.
7 tests en `test_arranger.py`. Suite total: 910 tests verdes.

**Qué**: nueva vista alternativa al timeline (toggle en toolbar): muestra SECCIONES como
bloques de color grandes (como FL Studio → Song view). Cada sección = rango de tiempo entre
dos marcadores (I2). Drag horizontal para reordenar secciones.

**Por qué Opus**: la semántica de "reordenar secciones manteniendo coherencia del modelo"
es sutil. Mover una sección implica `duplicate_range` + `delete_range` con implicaciones
sobre cues, marcadores y patterns dentro del rango — múltiples edge cases.

### Modelo de datos

La vista Arranger es solo frontend — el modelo subyacente (show.json) no cambia.

Las secciones se calculan en el cliente desde los marcadores de I2:

```typescript
interface Section {
  name: string      // nombre del marcador de inicio
  color: string     // color del marcador de inicio
  start_ms: number
  end_ms: number    // inicio del marcador siguiente (o fin del audio)
}
```

### Backend

Handler `duplicate_range(start_ms: int, end_ms: int, insert_at_ms: int)` — verificar si
ya existe de A5; si no existe, crearlo. Copia todos los clips del rango desplazados al
nuevo offset.

Handler `delete_range(start_ms: int, end_ms: int)` — borra todos los clips cuyo rango
se solape con el intervalo especificado.

Ambos handlers en executor si el rango tiene muchos clips (I6).

### Frontend

Nueva vista toggle en `Timeline.tsx` — botón "⊞ Arranger" en el toolbar:
- Bloques de sección como rectángulos de color grandes (width proporcional a duración).
- Drag horizontal para reordenar: al soltar, llama a `duplicate_range` + `delete_range`.
  Feedback visual optimista: el bloque se mueve en la UI inmediatamente.
- Doble clic en bloque → vuelve a la vista de clips desplazada al inicio de esa sección.
- Tooltip con nombre, duración en segundos y conteo de clips al hacer hover.
- Sin drag vertical (las secciones son temporales, no tienen jerarquía vertical).

### Tests

`tests/test_arranger.py`:
- Secciones calculadas correctamente desde los marcadores (Python puro, sin UI).
- `duplicate_range(start_ms=0, end_ms=10000, insert_at_ms=30000)` copia clips al nuevo
  offset con el desplazamiento correcto.
- `delete_range(start_ms=0, end_ms=10000)` borra solo los clips en ese rango.
- Reordenar sección no corrompe los clips fuera del rango (invariante I2).
- Marcadores se mantienen en su posición original después del reordenado (decisión
  documentada en ADR o comentario inline — el usuario decide si los marcadores se mueven).

**Aceptación**: tengo 4 secciones (intro, verso, estribillo, outro). Arrastro "verso" al
final → los clips se reordenan en el timeline; reproduzco y el show sigue el nuevo orden.
**Commit**: `roadmap-v4 fase I4: vista arranger`.

---

## I5 — Exportación de timeline: PDF de patch + CSV DMX (~2 días, Haiku) ✅ APLICADA 2026-06-14

**Implementación**: `server/timeline_export.py` — `export_patch_pdf` (fpdf2 o txt fallback,
escritura atómica) + `export_dmx_csv` (reutiliza render.npz a 30fps si existe, compute_frame
on-the-fly si no; columnas t_ms,universe,ch_1..ch_512; una fila por frame). Handlers
`export_patch_pdf` y `export_dmx_csv` en `_LOCAL` del dispatcher. Frontend: botones
"📄 PDF Patch" y "📊 CSV DMX" en RenderPanel de Live.tsx con indicador ✓ de ruta.
8 tests en `test_timeline_export.py`. Suite total: 918 tests verdes.

**Qué**: dos exportaciones profesionales:
- **PDF de patch**: lista de clips por pista con tiempos, efectos y params (para el técnico
  en papel, como el "plot" de cualquier rider técnico).
- **CSV DMX**: una fila por frame muestreado (t_ms, universo, canal_1..512) — para importar
  como referencia en consolas externas (GrandMA, ETC Eos).

**Por qué**: en producción real el técnico necesita un documento en papel y otras consolas
necesitan poder leer los datos DMX fuera del sistema.

### Backend

`server/timeline_export.py` — NUEVO:

```python
def export_patch_pdf(session, out_path: str) -> str:
    """Genera PDF con lista de clips ordenados por pista y tiempo.
    Usa fpdf2 (PyPI). Fallback: .txt si fpdf2 no disponible."""

def export_dmx_csv(session, out_path: str, fps: int = 1) -> str:
    """Genera CSV con frames DMX muestreados a `fps` FPS.
    Reutiliza render.npz si existe; si no, renderiza on-the-fly los frames muestreados."""
    # Cabecera: t_ms,universe,ch_1,ch_2,...,ch_512
```

Dependencia: `fpdf2` (PyPI, más ligero que ReportLab). Si no disponible al importar,
fallback a texto plano con extensión `.txt`.

Handlers (en executor — I6):
- `export_patch_pdf()` → `{ok, path: "projects/<slug>/patch.pdf"}`
- `export_dmx_csv(fps: int = 1)` → `{ok, path: "projects/<slug>/dmx_export.csv"}`

### Frontend

- Botones "📄 PDF Patch" y "📊 CSV DMX" en el `RenderPanel` de `Live.tsx`.
- Spinner mientras se genera + enlace de descarga al completar.

### Tests

`tests/test_timeline_export.py`:
- `export_patch_pdf()` → archivo existe y tamaño > 0.
- PDF (o txt fallback) contiene al menos los nombres de los clips (leer bytes y buscar str).
- `export_dmx_csv(fps=1)` → archivo con cabecera correcta y `ceil(duration_s)` filas (±1).
- CSV reutiliza render.npz existente (mock: npz existe → no llama a compute_frame).
- Sin fpdf2 (mock del import) → fallback a `.txt` sin crash.
- Guardado atómico: el archivo no existe en ruta final hasta que la escritura completa.

**Aceptación**: con el show de 273 s, exporto CSV a 1 FPS → 273 filas + cabecera; exporto
PDF → archivo con todos los clips ordenados por pista y tiempo.
**Commit**: `roadmap-v4 fase I5: exportación PDF patch + CSV DMX`.

---

# BLOQUE J — RIG PRO

> *Gestión profesional del rig de fixtures — del parcheado visual al canal DMX exacto.*

## J1 — Editor de patch visual drag-and-drop (~3 días, Sonnet)

**Qué**: `Patch.tsx` (314 LOC) muestra una lista básica de fixtures. Reemplazar con un
editor visual: canvas 2D donde cada fixture es un icono arrastrable con su posición relativa
en el escenario (planta 2D).

**Por qué**: el parche visual es el corazón de cualquier consola profesional. Sin él, el
técnico trabaja con una lista de IPs y no tiene un modelo mental del rig físico.

### Modelo de datos

Ampliar `rig.json` (o el modelo de fixture existente) con coordenadas 2D:

```json
{
  "fixtures": [
    {
      "id": "bar_1",
      "name": "Barra Izq 1",
      "type": "wled_bar",
      "universe": 1,
      "start_channel": 1,
      "ip": "192.168.1.100",
      "x": 0.1,
      "y": 0.8
    }
  ]
}
```

`x` e `y` son coordenadas relativas (0.0..1.0) del canvas de patch. Migración tolerante:
fixtures sin `x/y` reciben posiciones por defecto en cuadrícula automática.

Handler: `move_fixture(fixture_id: str, x: float, y: float)` → fixture actualizado (I3).

### Frontend

`Patch.tsx` (reescritura de la sección de fixtures):
- Canvas 2D (div con position:relative) donde cada fixture es un componente arrastrable
  (`react-moveable` ya es dep del proyecto).
- Icono según `type`: barra horizontal para `wled_bar`, spot para `moving_head`, círculo
  para `dimmer`, rectángulo para `rgb` o `strobe`.
- Al soltar: llama a `move_fixture` con coordenadas normalizadas (optimista — I3).
- Selección: clic → panel lateral con propiedades editables (nombre, universo, canal,
  tipo, IP).
- Tecla `Delete`/`Supr` con fixture seleccionado → `delete_fixture(id)`.
- Tecla `Enter` → modo edición inline de propiedades del fixture seleccionado.
- Botón "+" → `add_fixture` (modal con campos).

### Tests

`tests/test_patch_visual.py`:
- `move_fixture` actualiza `x/y` en el modelo y devuelve el fixture actualizado.
- Posición persiste tras `reload_project` (roundtrip rig.json).
- Fixture sin `x/y` en rig.json recibe posición de cuadrícula por defecto (migración).
- `delete_fixture` borra el fixture y sus referencias en el rig (I2 — sin huérfanos).
- `add_fixture` con `type` desconocido → error limpio (no crash).

**Aceptación**: arrastro la "Barra 3" al centro del canvas → su posición se guarda; al
recargar la página, sigue en el centro. El icono refleja el tipo del fixture.
**Commit**: `roadmap-v4 fase J1: editor de patch visual drag-and-drop`.

✅ **APLICADA 2026-06-14** — `Fixture` dataclass añade `patch_x`/`patch_y: Optional[float] = None`
(migración tolerante: `from_dict` carga None si ausentes; `asdict` los serializa).
Handler `_h_move_fixture` en `_LOCAL` sobreescribe el bridge: acepta `x/y` (0..1) o
`position=[x,y,z]` legado; actualiza `patch_x`/`patch_y`; clampea a 0..1; persiste
`session.project.rig_file`. Devuelve `{ok, fixture}` (I3).
`Patch.tsx`: `posOverride` → `patchOverride: Record<string,[number,number]>`;
helper `pxOf(f)` prioriza override → `patch_x`/`patch_y` → `useLayout` legado.
Drag llama `move_fixture({x, y})`, recibe fixture actualizado; `refreshFixtures` limpia override.
7 tests en `test_patch_visual.py`. **925 tests verdes** (2 bench timing ignorados).

---

## J2 — Soporte DMX completo por canal (~4 días, Opus)

**Qué**: hoy el motor renderiza solo barras de LEDs (pixel mapping WLED). Ampliar para
fixtures DMX convencionales: dimmers, PARs RGB, moving heads (pan/tilt/color), strobos.

**Por qué Opus**: la semántica de cómo se mezclan múltiples clips que afectan al mismo
canal del mismo fixture en el mismo instante es sutil y errores aquí producen comportamiento
extraño o peligroso en hardware real (conflictos DMX, sobretensiones en dimmers).

### Modelo de datos

Tipos de fixture añadidos a `fixtures.json`:

```python
FIXTURE_TYPES = Literal["wled_bar", "dimmer", "rgb", "moving_head", "strobe"]
```

Canales por tipo (mínimo funcional; GDTF amplía esto en J3):
- `dimmer`: canal 1 = brightness (0..255).
- `rgb`: canales 1-3 = R, G, B.
- `moving_head`: canal 1=pan, 2=tilt, 3=dimmer, 4-6=RGB, 7=strobe (configurable).
- `strobe`: canal 1 = rate (0=off, 255=max rate).

Mezcla: `LAST_WINS` (ADR-004 ya existente de G3 — reutilizar política documentada).

### Backend

`src/core/dmx_render.py` — NUEVO (función pura, testeable sin hardware):

```python
def render_fixture_channels(
    fixture_type: str,
    clips: list,         # clips activos en t_ms
    t_ms: int,
    audio_context: dict,
) -> dict[int, int]:     # canal_dmx → valor 0..255
```

Integrar en `session.compute_frame` después del render pixel: para cada fixture de tipo
no-pixel, llamar a `render_fixture_channels` y escribir los bytes en el universo
correspondiente. `OutputRouter.send_universe` ya acepta 512 bytes — sin cambios en la capa
de salida.

Handler: `set_fixture_type(fixture_id: str, type: str)` → fixture actualizado.

### Frontend

`ClipInspector.tsx`: si el clip está asignado a un fixture de tipo no-pixel, mostrar
controles de canal en lugar de los params genéricos:
- `dimmer`: slider de brightness 0-255 + label "Intensidad".
- `rgb`: color picker (tres canales RGB).
- `moving_head`: sliders pan/tilt (reutilizar UI de G3) + color picker.
- `strobe`: slider de rate + duty cycle.

### Tests

`tests/test_dmx_render.py`:
- Fixture `dimmer`: `render_fixture_channels` → canal 1 = brightness del clip.
- Fixture `rgb`: clip con R=255, G=0, B=128 → canales 1-3 correctos.
- Fixture `moving_head`: canal pan en rango 0..255 para ángulo 0..360°.
- Fixture `strobe`: canal 1 proporcional al rate.
- Mezcla LAST_WINS: dos clips en mismo instante → el de layer más alto gana.
- `compute_frame` con fixture dimmer produce bytes correctos en el universo de salida.

**Aceptación**: añado un dimmer al rig en universo 2 canal 1, pinto un clip de
brightness=128 → el analizador DMX externo muestra universo 2, canal 1 = 128.
**Commit**: `roadmap-v4 fase J2: soporte DMX completo por canal`.

✅ **APLICADA 2026-06-14** — `Fixture` añade `kind_override: Optional[str] = None` (migración
tolerante: from_dict carga None si ausente). `src/core/dmx_render.py` (NUEVO):
`render_fixture_channels(fixture, profile, clips, t_ms)` pura; kind = kind_override > profile.kind;
LAST_WINS por capa; defaults por kind: dimmer(ch1=brightness), rgb(ch1-3=RGB),
moving_head(ch1=pan/360, ch2=tilt, ch3=dim, ch4-6=RGB, ch7=strobe), strobe(ch1=rate);
pixel kinds retornan {}.
`_h_set_fixture_type` en `_LOCAL`: actualiza kind_override + persiste rig.json (I3).
`session._compute_fixture_channels(t_ms)`: loop sobre fixtures no-pixel; clips por track=universe-1;
resultado en `self._fixture_dmx_channels: {universe: bytearray(512)}`. Llamado al final de
compute_frame (ambas rutas). 7 tests en `test_dmx_render.py`. **932 tests verdes.**

---

## J3 — Biblioteca GDTF: browser y búsqueda (~2 días, Sonnet)

**Qué**: `gdtf_profiles/` ya tiene perfiles GDTF. Añadir un browser en `Patch.tsx`: lista
searchable de perfiles disponibles, preview de canales del fixture, botón "Añadir al rig".

**Por qué**: sin este browser, el técnico tiene que saber el nombre exacto del archivo GDTF.
Con el browser, puede buscar "Robe Robin 100" y seleccionar el perfil en segundos.

### Backend

Handler `list_gdtf_profiles()` → `{ok, profiles: [{name, manufacturer, modes, channel_count, path}]}`.
Escanea `gdtf_profiles/*.gdtf`, extrae metadatos del XML interior, devuelve lista ordenada.
Caché en memoria al arrancar (los perfiles no cambian en caliente).

Handler `add_fixture_from_gdtf(profile_path: str, universe: int, start_channel: int,
name: str = "")` → `{ok, fixture}` — crea fixture con los canales del perfil GDTF
(invariante I3: devuelve el fixture creado).

### Frontend

Panel "GDTF Library" en `Patch.tsx` (drawer lateral o modal):
- Input de búsqueda — filtra por nombre y fabricante en tiempo real (cliente).
- Lista de resultados: nombre del fixture, fabricante, número de canales.
- Al seleccionar un perfil: preview de la tabla de canales (canal → nombre GDTF).
- Botón "Añadir al rig" → formulario con universo + canal de inicio + nombre custom →
  llama a `add_fixture_from_gdtf`.

### Tests

`tests/test_gdtf_browser.py`:
- `list_gdtf_profiles` devuelve todos los archivos `.gdtf` del directorio.
- `list_gdtf_profiles` con directorio vacío devuelve lista vacía sin crash.
- `add_fixture_from_gdtf` con perfil válido crea fixture con canales correctos.
- `add_fixture_from_gdtf` con perfil inexistente → error limpio.
- Fixture creado desde GDTF persiste en rig.json tras reload.

**Aceptación**: busco "Showtec" en el browser, selecciono "Showtec Phantom 25", lo añado al
rig en universo 3 canal 1 → aparece en el canvas de patch con sus 16 canales configurados.
**Commit**: `roadmap-v4 fase J3: biblioteca GDTF browser y búsqueda`.

✅ **APLICADA 2026-06-14** — `_h_list_gdtf_profiles`: escanea `PROFILES_DIR/*.gdtf`,
caché `_gdtf_cache` en memoria con `_gdtf_metadata` (pygdtf extrae name/manufacturer/modes/
channel_count); retorna lista ordenada. `_h_add_fixture_from_gdtf(profile_path, universe,
start_channel, name, mode_name)`: carga GDTF via `load_gdtf_profile`, genera fixture_id único,
añade al rig, persiste rig.json; retorna fixture (I3). Ambos en `_LOCAL`.
`Patch.tsx`: botón "GDTF" en toolbar; `GdtfBrowserModal` — input búsqueda filtrado local,
lista de perfiles (nombre/fabricante/canales), selector de modo si hay varios, form add
(universo/start/nombre). 5 tests en `test_gdtf_browser.py`. **937 tests verdes.**

---

## J4 — Test de fixtures avanzado: chase y fade (~1 día, Haiku)

**Qué**: ampliar `identify_fixture` (E4) con color y duración configurables. Añadir
`chase_test(universe)` que cicla colores por los fixtures del universo secuencialmente.

**Por qué**: verificar el cableado de un rig complejo antes del show. El `identify_fixture`
actual solo hace blanco fijo 2 s; el chase automático es el método estándar en consolas
profesionales para verificar el orden de los fixtures en el universo.

### Backend

Ampliar `identify_fixture(fixture_id, color=(255,255,255), duration_ms=2000)`:
- Añadir parámetros `color: tuple[int,int,int]` y `duration_ms: int` con defaults actuales.
- Backwards-compatible: llamadas sin parámetros siguen funcionando exactamente igual.

Handler `chase_test(universe: int)` → `{ok, chase_id: str}`:
- Cicla por cada fixture del universo con la secuencia rojo → verde → azul → blanco.
- Cada color dura 500 ms. Usa `asyncio.call_later` en cadena (no bloquea — I4).
- Estado efímero en sesión: `session._active_chases: dict[int, asyncio.TimerHandle]`.

Handler `chase_stop(universe: int)` → `{ok}`:
- Cancela el `TimerHandle` activo del universo y apaga ese universo.

### Frontend

`FixtureTestPanel` en `Patch.tsx` (ya existe de E4):
- Color picker en el botón "Identify" (añade color por defecto: blanco).
- Input de duración en ms (por defecto 2000).
- Botón "Chase" por universo → llama a `chase_test(universe)`.
- Botón "Stop Chase" (visible solo si hay chase activo en ese universo).

### Tests

`tests/test_fixture_test_advanced.py`:
- `identify_fixture(id, color=(255,0,0))` → frame rojo en ese fixture durante la duración.
- `identify_fixture(id, duration_ms=500)` → expira en 500 ms (mock de `asyncio.call_later`).
- `chase_test(1)` → secuencia rojo/verde/azul/blanco en los fixtures del universo 1.
- `chase_stop(1)` cancela el TimerHandle activo.
- `chase_test` en universo sin fixtures → error limpio (no crash).

**Aceptación**: pulso "Chase" en el universo 1 → las barras ciclan rojo/verde/azul/blanco
cada 500 ms. Pulso "Stop" → se apagan. Pulso "Identify" con color rojo → fixture en rojo.
**Commit**: `roadmap-v4 fase J4: test de fixtures avanzado chase y fade`.

✅ **APLICADA 2026-06-14** — `identify_fixture` ampliado con `color=[r,g,b]` y `duration_ms`
configurables (backwards-compatible: sin params → blanco 2 s); `_identify` entries ahora son
`{t_expires, color}` (session.py actualizado para leer ambos formatos). Handler `chase_test(universe)`:
secuencia rojo→verde→azul→blanco a 500ms via `asyncio.Task` en cadena; estado en
`session._active_chases`. Handler `chase_stop(universe)`: cancela task + limpia `_identify`.
Ambos en `_LOCAL`. `FixtureTestPanel`: color picker + input duración compartidos; botón
"▶Chase" por fixture (universo) con "⏹" stop cuando activo. 6 tests en
`test_fixture_test_advanced.py`. **943 tests verdes.**

---

# BLOQUE K — VISUALIZACIÓN

> *Previsualización profesional para diseñar sin hardware y verificar con precisión.*

## K1 — Viewer 3D mejorado: posicionamiento de fixtures (~3 días, Opus)

**Qué**: ampliar el viewer Three.js para que muestre los fixtures en sus posiciones 3D
reales (editables desde `Patch.tsx`), con iluminación en tiempo real desde el stream binario.

**Por qué Opus**: la integración entre la posición 3D editada en React, el modelo de datos
(`rig_layout.json`), y el render Three.js con datos del stream en tiempo real implica tres
piezas que deben sincronizarse con semántica cuidadosa (coordenadas, orientación, tipos de
fixture, colores actualizados frame a frame).

### Modelo de datos

`rig_layout.json` — NUEVO archivo en `projects/<slug>/`:

```json
{
  "fixtures": [
    {"id": "bar_1", "x": -2.0, "y": 4.0, "z": 0.0, "rx": 0, "ry": 0, "rz": 0}
  ]
}
```

Coordenadas en metros (espacio de escenario). Rotación en grados (euler XYZ).

Handler `set_fixture_3d(fixture_id: str, x: float, y: float, z: float,
rx: float = 0, ry: float = 0, rz: float = 0)` → `{ok, fixture}` — guarda en
`rig_layout.json` (atómico).

Handler `get_rig_layout()` → `{ok, fixtures: [{id, x, y, z, rx, ry, rz}]}`.

### Backend

Sin cambios al motor de render. El `rig_layout.json` es solo datos de visualización.

### Frontend

En `Patch.tsx`: tab "Vista 3D" (junto a "Planta 2D" de J1):
- Inputs numéricos `x/y/z` (metros) y `rx/ry/rz` (grados) por fixture seleccionado.
- Botón "Guardar posición 3D" → `set_fixture_3d` (optimista — I3).

En `web/public/v3d/main.js` (viewer Three.js existente):
- Al iniciar: fetch de `/api/v1/rig_layout` (o handler JSON-RPC) → posicionar cada fixture
  en su coordenada 3D con `mesh.position.set(x, y, z)` y `mesh.rotation.set(rx, ry, rz)`.
- Geometría según tipo: barra = `BoxGeometry(2, 0.05, 0.05)`, spot = `ConeGeometry`,
  dimmer = `CylinderGeometry`.
- Al recibir el frame binario del `/ws/stream`: actualizar `material.color` de cada fixture
  con el color promedio de sus LEDs activos.
- Botones de cámara: cenital (top-down), frontal, perspectiva libre (`OrbitControls`).

### Tests

`tests/test_rig_layout.py`:
- `set_fixture_3d` guarda en `rig_layout.json` con guardado atómico.
- `get_rig_layout` devuelve los fixtures con coordenadas correctas.
- `rig_layout.json` inexistente → `get_rig_layout` devuelve lista vacía sin crash.
- Fixture con `id` inexistente en `set_fixture_3d` → error limpio.
- Roundtrip: `set_fixture_3d` → `get_rig_layout` → mismas coordenadas.

**Aceptación** (manual): configuro las 10 barras en sus posiciones reales del escenario a
4 m de altura; reproduzco el show → las barras se iluminan con los colores correctos en 3D.
Los modos de cámara cenital y frontal funcionan.
**Commit**: `roadmap-v4 fase K1: viewer 3D con posicionamiento de fixtures`.

✅ **APLICADA 2026-06-14** — `Project.rig_layout_file` → `projects/<slug>/rig_layout.json`.
Handlers `get_rig_layout` + `set_fixture_3d(x,y,z,rx,ry,rz)` en `_LOCAL`; escritura atómica
`.tmp→replace`; `sync_rig_layout` mergeaa posiciones K1 sobre las auto-generadas. Viewer
`main.js`: `setupCameraButtons()` (cenital/frontal/perspectiva); `index.html`: estilos +
`#cam-controls` div. `Patch.tsx`: panel plegable "Posición 3D" (x/y/z metros + rx/ry/rz
grados) por fixture seleccionado; carga desde `get_rig_layout` al cambiar selección;
"Guardar posición 3D" → `set_fixture_3d`. 5 tests en `test_rig_layout.py`. **948 tests verdes.**

---

## K2 — Pixel mapping: vídeo/imagen → LEDs (~4 días, Opus)

**Qué**: nuevo tipo de efecto `PixelMapEffect` que mapea píxeles de una imagen (PNG/JPG)
o vídeo (MP4) a los LEDs de la barra según una región configurable.

**Por qué Opus**: el pixel mapping requiere coordinar carga de archivos externos, gestión
del estado de frame de vídeo sincronizado con `elapsed_time`, la interfaz de "region picker",
y el fallback limpio cuando el archivo no está disponible — múltiples piezas con acoplamiento
no trivial.

### Modelo de datos

```python
# plugins/effects/pixel_map.py — nuevo efecto
class PixelMapEffect(Effect):
    name = "pixel_map"
    family = "mapping"
    scope = EffectScope.PER_BAR
    PARAM_SCHEMA = {
        "source_path": {"type": "str",   "label": "Archivo fuente (PNG/JPG/MP4)"},
        "x":      {"type": "int",  "min": 0, "max": 9999, "default": 0,   "label": "X origen"},
        "y":      {"type": "int",  "min": 0, "max": 9999, "default": 0,   "label": "Y origen"},
        "width":  {"type": "int",  "min": 1, "max": 9999, "default": 100, "label": "Ancho región"},
        "height": {"type": "int",  "min": 1, "max": 9999, "default": 100, "label": "Alto región"},
        "fit_mode": {"type": "enum", "options": ["stretch", "crop", "tile"], "default": "stretch"},
        "speed":  {"type": "float","min": 0.1,"max": 4.0,"default": 1.0,  "label": "Velocidad (vídeo)","unit": "x"},
    }
```

### Backend

`src/core/pixel_map.py` — NUEVO (función pura):

```python
def sample_image_region(
    image_path: str,
    x: int, y: int, width: int, height: int,
    output_shape: tuple = (1, 93, 3),
    fit_mode: str = "stretch",
) -> np.ndarray:  # uint8, shape output_shape
    """Carga la imagen con Pillow, recorta la región, escala a output_shape."""
```

Para vídeo: usar `imageio` (ya posible dep) con import lazy. Si no disponible, tratar el
archivo como imagen estática (tomar el primer frame). Documentar con comentario.

`PixelMapEffect.render`: llamar a `sample_image_region`. Para vídeo, calcular
`frame_idx = int((elapsed_time / 1000.0) * speed * fps) % total_frames`.

Cache de imágenes cargadas por `source_path` en la instancia del efecto (`__init__`).

Handler `set_clip_pixel_map(clip_id: str, source_path: str, x: int, y: int, width: int,
height: int, fit_mode: str = "stretch")` → clip actualizado (I3).

### Frontend

`ClipInspector.tsx`: si `effect_id` es `PixelMapEffect`:
- File picker para `source_path` (filtra PNG/JPG/MP4).
- Miniatura de la imagen con el rectángulo de región superpuesto (SVG overlay).
- Sliders para x, y, width, height, speed (generados por F2 desde PARAM_SCHEMA).

### Tests

`tests/test_pixel_map.py`:
- Imagen PNG 100×100, región (0,0,10,10) → `sample_image_region` devuelve array (1,93,3).
- Output shape = (1, 93, 3), dtype = uint8, valores en [0, 255].
- `fit_mode="tile"` → sin crash, resultado de shape correcta.
- `source_path` vacío o inexistente → array negro (1,93,3) sin lanzar excepción (I4).
- `set_clip_pixel_map` actualiza params del clip y devuelve clip actualizado (I3).

**Aceptación**: cargo el logo del evento (PNG), lo asigno a la barra 1 con fit_mode
"stretch" → el logo aparece pixelado en los 93 LEDs. Cargo un vídeo MP4 → los frames del
vídeo se reproducen sincronizados con el show.
**Commit**: `roadmap-v4 fase K2: pixel mapping imagen/vídeo a LEDs`.

✅ **APLICADA 2026-06-14** — `src/core/pixel_map.py` (NUEVO): `sample_image_region` pura con
Pillow; cache `_IMG_CACHE` por ruta; `_fit_region` (stretch/crop/tile); soporte MP4 via
imageio lazy (fallback a imagen estática). `plugins/effects/pixel_map.py` (NUEVO):
`PixelMapEffect` (id=1010, scope=PER_BAR): PARAM_SCHEMA `source_path`/x/y/width/height/
fit_mode/speed; `render` calcula frame_idx para vídeo (elapsed_time × speed × 25fps).
Handler `set_clip_pixel_map` en `_LOCAL`: actualiza clip.params + clip.effect_id=1010 (I3).
`ClipInspector.tsx` + `schema.ts`: tipo "str" soportado en ParamControl (input texto, sin
conversión numérica, placeholder). 5 tests en `test_pixel_map.py`. **953 tests verdes.**

---

## K3 — Preview de show en tiempo real en el navegador (~2 días, Sonnet)

**Qué**: nueva pestaña "Preview" que muestra las 10 barras como rectángulos de color en
tiempo real, consumiendo el frame binario del `/ws/stream`. Canvas 2D con
`requestAnimationFrame`, sin Three.js, sin WebGL.

**Por qué**: el viewer 3D existe pero es pesado y requiere orientarse en el espacio 3D.
Una vista 2D plana y rápida (10 filas × 93 píxeles) es más útil para verificar el show en
producción, o en una segunda pantalla mientras se diseña.

### Backend

Sin cambios de backend. El stream binario ya emite el frame `(10 × 93 × 3)` uint8 en cada
tick.

### Frontend

`web/src/views/Preview.tsx` — NUEVO:

```typescript
// Canvas 2D, cada LED = pixelSize × pixelSize px (configurable)
// requestAnimationFrame loop: en cada frame, convierte el último ArrayBuffer del stream
// a ImageData y llama a ctx.putImageData
```

- Canvas con width = 93 × pixelSize, height = 10 × pixelSize.
- Slider de zoom: pixelSize = 2, 4, 6 px por LED.
- Toggle de "nombre de barra" (overlay de texto sobre cada fila).
- Nueva pestaña en el topbar junto a Timeline / Live / Analyzer / Patch.

Función pura exportable:
```typescript
export function buildImageData(frameBuffer: ArrayBuffer, pixelSize: number): ImageData
```

### Tests

`web/src/preview.test.ts` (Vitest):
- `buildImageData` con buffer de 10×93×3 bytes → `ImageData` con width=93, height=10.
- Primer LED (bytes 0-2 = 255,0,0) → píxel (0,0) rojo en ImageData.
- Buffer de tamaño incorrecto → no lanza (devuelve ImageData negro 93×10).

**Aceptación**: con el show reproduciéndose, abro la pestaña Preview → veo las 10 barras
coloreadas actualizándose a 30 FPS sin lag visible. Ajusto el zoom a ×4 → los LEDs son
grandes y claramente distinguibles. Sin hardware conectado.
**Commit**: `roadmap-v4 fase K3: preview 2D en tiempo real`.

✅ **APLICADA 2026-06-14** — `web/src/views/Preview.tsx` (NUEVO): `buildImageData` pura
(exportada para tests); `PreviewView` con `requestAnimationFrame`; zoom ×2/4/6/8;
toggle etiquetas de barra; `stream.latestFrame.buffer` → `tmpCanvas` → `drawImage` escalado.
`store.ts`: `Tab` + "preview". `App.tsx`: import + tab "Preview" + badge. `vite.config.ts`:
`test.environment = "happy-dom"`. `web/src/preview.test.ts` (Vitest, 3 tests): buffer correcto
→ shape correcta; LED rojo → píxel rojo; tamaño incorrecto → negro sin excepción. **953 tests
Python + 3 Vitest verdes.**

---

# BLOQUE L — RED Y COLABORACIÓN

> *Conectar múltiples operadores y sistemas externos sin fricción.*

## L1 — API REST pública (~3 días, Sonnet)

**Qué**: además del WebSocket JSON-RPC, exponer una API REST en `/api/v1/` para integrar
con sistemas externos (QLab scripts, sistemas de control de sala, herramientas custom) sin
necesitar un cliente WebSocket persistente.

**Por qué**: la API REST es la interfaz de integración estándar de la industria. OSC (E2)
cubre el tiempo real; la API REST cubre configuración, consulta y control puntual desde
scripts y herramientas.

### Backend

`server/rest_api.py` — NUEVO (router FastAPI montado en la app en `/api/v1`):

```python
# GET  /api/v1/clips                 → list_clips (con paginación offset/limit de H4)
# POST /api/v1/clips                 → add_clip
# GET  /api/v1/cues                  → get_cue_state
# POST /api/v1/cues/go               → go_next_cue
# GET  /api/v1/status                → {t_ms, bpm, section, blackout, baked}
# POST /api/v1/macros/{name}         → set_macro(name, value)
# GET  /api/v1/fixtures              → list_fixtures del rig
```

Autenticación: header `X-API-Key`. La key se configura en `output_targets.json["api_key"]`.
Si no configurada, la API queda sin autenticación (útil en desarrollo local — documentar).

Respuestas: `{"ok": true, "data": {...}}` o `{"ok": false, "error": "..."}`.

Los endpoints son wrappers sobre handlers del dispatcher — sin duplicar lógica de negocio.

Documentación: `docs/api/rest.md` con descripción de cada endpoint y ejemplos curl.

### Tests

`tests/test_rest_api.py` (con `httpx.AsyncClient` + `AsyncTestClient` de FastAPI):
- `GET /api/v1/status` → 200, `{ok: true, data: {t_ms: 0, ...}}`.
- `GET /api/v1/clips` con `limit=10` → respuesta paginada.
- `POST /api/v1/clips` con body válido → clip creado (201).
- `POST /api/v1/macros/brightness` con `{"value": 0.5}` → macro aplicada.
- Sin `X-API-Key` cuando api_key configurada → 401.
- Con `X-API-Key` correcta → 200.
- Con `X-API-Key` incorrecta → 401.

**Aceptación**: `curl http://localhost:8000/api/v1/status` devuelve el estado del show en
JSON sin necesitar WebSocket. `curl -X POST .../api/v1/cues/go -H "X-API-Key: mi_key"`
avanza al siguiente cue.
**Commit**: `roadmap-v4 fase L1: API REST pública`.

---

## L2 — Webhooks de eventos (~2 días, Haiku)

**Qué**: al producirse ciertos eventos en el show, el servidor hace POST a URLs externas
configuradas. Eventos disponibles: `on_cue_change`, `on_beat`, `on_section_change`,
`on_blackout`, `on_render_complete`.

**Por qué**: los webhooks permiten que sistemas externos (IFTTT, scripts custom, sistemas
de sala) reaccionen a eventos del show sin mantener un WebSocket abierto. Estándar de
integración en producción moderna.

### Backend

Config en `output_targets.json["webhooks"]`:
```json
[
  {
    "url": "https://mi-sistema.com/show-events",
    "events": ["on_cue_change", "on_beat"],
    "secret": "hmac_secret_opcional"
  }
]
```

`server/webhooks.py` — NUEVO:

```python
class WebhookDispatcher:
    async def emit(self, event: str, data: dict):
        """POST a todas las URLs suscritas al evento.
        Payload: {"event": "on_cue_change", "t_ms": 12345, "data": {...}}
        Header X-Signature-256: HMAC-SHA256(body, secret) si secret configurado.
        Reintentos: 3 intentos con backoff (1 s, 3 s, 9 s) en executor (I6)."""
```

`WebhookDispatcher` se instancia en `ShowSession`. Llamado desde los handlers que generan
esos eventos (E1 para `on_cue_change`, tick.py para `on_beat`, etc.).

Handlers: `webhook_get_config()`, `webhook_set_config(webhooks: list)` — guarda en
`output_targets.json` de forma atómica.

### Frontend

Panel "Webhooks" en `Patch.tsx` (nueva sección desplegable):
- Lista de webhooks configurados (url, eventos suscritos, con/sin secret).
- Formulario añadir/editar/eliminar webhook.
- Botón "Test" → envía un evento de prueba `{"event": "test", "t_ms": 0}` y muestra el
  status HTTP de la respuesta.

### Tests

`tests/test_webhooks.py` (con mock de `httpx.AsyncClient`):
- `emit("on_cue_change", {...})` → POST a la URL con payload correcto.
- HMAC-SHA256 en header `X-Signature-256` cuando `secret` configurado.
- Sin secret → header de firma no incluido.
- Reintento tras fallo HTTP 500 (3 reintentos, verificar backoff).
- URL inaccesible (timeout) → log de error + sin crash (I4/I6).
- `webhook_set_config` guarda en `output_targets.json` de forma atómica.

**Aceptación**: configuro webhook a `https://webhook.site/...`, reproduzco el show →
cada beat envía un POST con `{"event": "on_beat", "t_ms": ...}`. La firma HMAC-SHA256
se verifica correctamente en webhook.site.
**Commit**: `roadmap-v4 fase L2: webhooks de eventos`.

---

## L3 — Modo multiusuario básico (~3 días, Opus)

**Qué**: dos navegadores controlan el mismo show simultáneamente: operador principal
(permisos totales) + asistente (solo macros y cues). Tokens en el WebSocket handshake.

**Por qué Opus**: el control de acceso en un sistema de tiempo real con estado compartido
requiere pensar cuidadosamente qué handlers son seguros para el rol asistente (no pueden
corromper el show) y cuáles son exclusivos del operador (mutaciones del timeline). La
política de roles debe ser correcta desde el día 1 — no se puede parchar después sin
afectar a sesiones en vuelo.

### Modelo de datos

Config en `output_targets.json["tokens"]`:
```json
[
  {"token": "abc123", "role": "operator"},
  {"token": "xyz789", "role": "assistant"}
]
```

Roles:
- `operator`: acceso completo a todos los handlers.
- `assistant`: solo `set_macro`, `go_cue`, `go_next_cue`, `go_prev_cue`, `blackout`,
  `live_trigger`, `live_stop_all`, `get_*`, `list_*`.
- Sin tokens configurados (o token no presente): acceso completo — comportamiento actual,
  para desarrollo local (documentar en README).

### Backend

Token en el WebSocket handshake: query param `?token=X` en la URL del WS.

`server/auth.py` — NUEVO:

```python
def check_permission(token: str, handler_name: str, tokens_config: list) -> bool:
    """Devuelve True si el token tiene permiso para ejecutar el handler.
    Reglas: operator → todo; assistant → handler en ASSISTANT_HANDLERS."""

ASSISTANT_HANDLERS = frozenset({
    "set_macro", "go_cue", "go_next_cue", "go_prev_cue",
    "blackout", "live_trigger", "live_stop_all",
    # todos los get_* y list_* — verificar por prefijo
})
```

Integrar en `dispatcher.handle()`: antes de ejecutar, llamar a `check_permission`.
Si devuelve False → `{error: "permission_denied", code: 403}`.

El stream emite a TODOS los clientes conectados (ya funciona con `hub.broadcast`). El
asistente recibe el estado en tiempo real pero sus mutaciones son rechazadas.

Handler `auth_get_role()` → `{role: "operator"|"assistant"|"anonymous"}` — para que el
frontend sepa qué mostrar al conectar.

### Frontend

- URL del WS: `ws://localhost:8000/ws/control?token=X` — el frontend incluye el token si
  está disponible (por ejemplo, desde `?token=` en la URL de la página).
- Al conectar, llamar a `auth_get_role()` → si `assistant`, deshabilitar botones mutantes
  (add clip, delete, etc.) con `disabled` + tooltip "Permiso insuficiente".
- Si el servidor responde con `permission_denied` a pesar de lo anterior, mostrar toast.

### Tests

`tests/test_multiuser.py`:
- Token con rol `"assistant"` rechaza `add_clip` → `{error: "permission_denied"}`.
- Token con rol `"assistant"` acepta `go_next_cue` → OK.
- Token con rol `"assistant"` acepta `list_clips` (prefijo `list_`) → OK.
- Token con rol `"operator"` acepta `add_clip` → OK.
- Sin tokens configurados → todo accesible (backwards-compat).
- Token desconocido → `{error: "invalid_token"}`.
- Dos clientes conectados simultáneamente → ambos reciben el broadcast del stream.

**Aceptación**: abro dos browsers — uno con `?token=operator_token` (puede añadir clips) y
otro con `?token=assistant_token` (solo macros/cues, botones mutantes desactivados). Ambos
ven el show en tiempo real.
**Commit**: `roadmap-v4 fase L3: modo multiusuario básico`.

---

# BLOQUE M — INTELIGENCIA

> *Funciones avanzadas de análisis y generación que elevan la productividad del diseñador.*

## M1 — Análisis avanzado: BPM tap + key detection (~2 días, Sonnet)

**Qué**:
- **Tap tempo**: handler `tap_bpm()` registra timestamps de taps; tras 4+ taps, calcula
  BPM por mediana de intervalos y lo aplica como `tempo_sync` en modo manual.
- **Key detection**: usar `librosa.estimate_tuning` + chroma para detectar la tonalidad
  de la canción y exponerla en `get_audio_context`.

**Por qué**: el operador en directo a menudo no tiene audio analizado — toca con artistas
en vivo. El tap tempo es la forma humana de sincronizar el BPM. La detección de tonalidad
permite que el Auto-VJ (D1) o reglas custom usen la clave musical como trigger.

### Backend

Ampliar `server/tempo_sync.py` (`TempoSyncService`):

```python
def tap(self, t_wall: float) -> dict:
    """Registra un tap (timestamp en wall clock, time.perf_counter).
    Tras 4+ taps, calcula BPM por mediana de intervalos y activa mode='manual'.
    Retorna: {bpm: float|None, taps: int, ready: bool}"""
    # Buffer circular de últimos 8 taps
    # BPM = 60 / mediana(intervalos entre taps)
```

Handler `tap_bpm()` → llama a `tempo_sync.tap(time.perf_counter())` → devuelve
`{bpm, taps, ready}`.

`server/key_detector.py` — NUEVO (función pura, en executor — I6):

```python
def detect_key(audio_path: str) -> dict:
    """Detecta tonalidad usando librosa chroma + votación de Krumhansl-Schmuckler.
    Retorna: {key: "C", mode: "major"|"minor", confidence: 0.0..1.0}
    Corre en executor — puede tardar varios segundos en canciones largas."""
```

Handler `get_key_info()` → si ya calculado (caché en sesión), devuelve desde caché;
si no, lanza en executor y devuelve `{status: "computing"}` (el resultado llegará por
stream event `{type: "key_detected", key, mode, confidence}`).

`get_audio_context` incluye `key: {key, mode, confidence}` si disponible en caché.

### Frontend

- Botón `TAP` en el toolbar del timeline (tecla `T` en modo Live).
- 4 puntos que se van llenando al hacer taps — indicador visual de "taps acumulados".
- Chip de tonalidad detectada en el panel `Analyzer.tsx` (ej. "Am ·· 0.82").

### Tests

`tests/test_tap_bpm.py`:
- 4 taps con intervalos de 500 ms → `tempo_sync.bpm ≈ 120` (±1 BPM).
- 3 taps → `ready: False`, bpm no se actualiza.
- 8 taps con intervalos ruidosos (±20 ms) → mediana robusta, BPM correcto (±3 BPM).

`tests/test_key_detection.py`:
- WAV sintético de La mayor (senoide 440 Hz) → key ≈ "A" (o "Am" — tolerancia alta aquí).
- Audio path inexistente → `detect_key` devuelve `{error: "not found"}` sin crash del executor.
- Segunda llamada a `get_key_info` devuelve desde caché (sin re-analizar).

**Aceptación**: pulso TAP 4 veces a 128 BPM → el indicador BPM muestra "128.0" y el
Auto-VJ dispara en beat. El chip de tonalidad muestra "Am" para el himno de España.
**Commit**: `roadmap-v4 fase M1: tap BPM + key detection`.

---

## M2 — Generación automática de show desde análisis (~4 días, Opus)

**Qué**: handler `generate_show(style, density, replace)` que analiza el audio cargado y
genera clips automáticamente — sin IA externa, solo lógica determinista sobre el análisis.

**Por qué Opus**: la generación de un show coherente desde análisis de audio implica
coordinar beats, secciones detectadas, selección de efectos por estilo y densidad, y
asegurar que los clips no se solapen en el mismo layer — múltiples invariantes interactuando.

### Especificación del algoritmo

```python
handler generate_show(
    style: Literal["minimal", "club", "festival", "chill"],
    density: float,   # 0.0 (solo downbeats) .. 1.0 (cada beat)
    replace: bool = False,
) -> {ok, clips_created: int}
```

1. Obtener beats y secciones del análisis (ya disponibles vía `analyzer_service`).
2. Por sección: asignar color temático según índice y `style`:
   - `"minimal"`: blanco / azul / blanco alternados.
   - `"club"`: rojo / azul / verde / magenta por sección.
   - `"festival"`: arcoíris (matiz distribuido entre secciones).
   - `"chill"`: tonos pastel (baja saturación, colores cálidos).
3. En cada downbeat: clip de 1 beat de duración, efecto `solid_color`, layer 0.
4. Si `density > 0.5`: en cada beat (no solo downbeat), clip de 0.5 beats, layer 1.
5. Si `density > 0.8`: en cada onset fuerte, flash `strobe_color` de 50 ms, layer 2.
6. Sin solapamientos en el mismo layer (verificar antes de añadir cada clip).
7. Si `replace=True`: limpiar el timeline antes de generar.

El resultado es un show.json válido, editable como cualquier otro show.

### Backend

`server/show_generator.py` — NUEVO. Corre en executor (I6) para shows largos.
Usa `undo.push_snapshot()` antes de generar para que sea deshacibled (I1).

### Tests

`tests/test_show_generator.py`:
- `generate_show("club", 0.5)` → timeline con clips; ningún clip se solapa con otro en el
  mismo layer.
- `generate_show("minimal", 0.0)` → clips SOLO en downbeats (no en beats intermedios).
- `generate_show("festival", 1.0)` → clips en cada beat detectado.
- `replace=True` → timeline vacío antes de añadir los clips generados.
- `replace=False` → clips añadidos sobre los existentes sin borrar los previos.
- Show generado pasa roundtrip show.json (serializa/deserializa sin pérdida).

**Aceptación**: cargo `el_taser`, ejecuto `generate_show("club", 0.7)` → en 5 s aparece un
timeline con clips coherentes con los beats; reproduzco y el show sigue la música de forma
reconocible. Puedo deshacer la generación con Ctrl+Z.
**Commit**: `roadmap-v4 fase M2: generación automática de show`.

---

## M3 — Historial de gestos y replay (~2 días, Sonnet)

**Qué**: grabar los handlers ejecutados en sesión en vivo en un log en memoria (los 500
últimos), con capacidad de listarlos y re-ejecutarlos con un clic.

**Por qué**: el operador que hace algo brillante en directo no puede reproducirlo exactamente.
Con el historial, puede ver qué handlers ejecutó y repetirlos — o enseñar a otro operador
lo que hizo.

### Backend

`server/gesture_log.py` — NUEVO:

```python
class GestureLog:
    MAX_ENTRIES = 500
    _log: list[dict]  # [{idx, t_ms, handler, params, ts_wall}]

    def record(self, handler: str, params: dict, t_ms: int): ...
    def list(self, last: int = 200) -> list[dict]: ...
    def replay(self, idx: int, session) -> dict:
        """Re-ejecuta el handler del gesto con índice idx.
        Devuelve el resultado del handler re-ejecutado."""
```

El `GestureLog` se integra en el `dispatcher.handle()`: después de ejecutar cualquier
handler que no empiece por `list_`, `get_`, `preview_`, o `auth_` — llama a
`gesture_log.record(handler, params, session.t_ms)`.

Handlers:
- `list_gesture_history(last: int = 200)` → `{ok, gestures: [...]}`.
- `replay_gesture(idx: int)` → devuelve el resultado del handler re-ejecutado.
- `clear_gesture_history()` → `{ok}`.

### Frontend

Panel "Historia" en `Live.tsx` (lateral, colapsable):
- Lista scrollable de gestos: handler + params resumidos + t_ms en formato mm:ss.
- Botón "▶ Replay" por gesto → llama a `replay_gesture(idx)`.
- Botón "🗑 Limpiar" → `clear_gesture_history`.
- Actualización: polling cada 2 s (o evento stream `{type: "gesture_recorded", idx}`).

### Tests

`tests/test_gesture_log.py`:
- Ejecutar `add_clip` → `list_gesture_history` incluye la entrada con handler y params.
- Handlers de `list_*` y `get_*` NO se graban (verificar por prefijo).
- `replay_gesture(0)` re-ejecuta el primer gesto (efecto observable en el estado).
- `MAX_ENTRIES` respetado: tras 501 gestos, el más antiguo se descarta.
- `clear_gesture_history()` → `list_gesture_history` devuelve lista vacía.

**Aceptación**: en directo ejecuto 5 gestos. Abro el panel Historia → veo los 5 gestos con
su t_ms. Hago clic en Replay del gesto 3 → el efecto se re-aplica al show.
**Commit**: `roadmap-v4 fase M3: historial de gestos y replay`.

---

# BLOQUE N — PLATAFORMA

> *El ecosistema a largo plazo: comunidad, portabilidad y mantenibilidad.*

## N1 — Marketplace de plugins (~3 días, Sonnet)

**Qué**: directorio online de efectos y presets de la comunidad (manifest JSON remoto,
por ejemplo en un GitHub Release). El usuario puede instalar plugins con un clic desde
la UI.

**Por qué**: el SDK (H1) permite crear plugins pero sin distribución los plugins no llegan
a otros usuarios. El marketplace cierra el ciclo — convierte el SDK en un ecosistema.

### Backend

`server/marketplace.py` — NUEVO:

```python
# URL del manifest configurable en output_targets.json["marketplace_url"]
# Format manifest: [{name, author, version, effect_ids, download_url, description}]

async def fetch_manifest(url: str) -> list[dict]:
    """Fetch con timeout 10 s. Caché en memoria 5 min."""

async def install_plugin(download_url: str, plugins_dir: Path) -> dict:
    """Descarga el .py, valida con assert_valid_plugin_effect (H1 harness),
    copia a plugins/effects/, recarga EffectLibrary.
    Devuelve: {ok, name, effect_ids}"""
```

Seguridad: documentar en `plugin-sdk.md` que el marketplace solo instala plugins de URLs
en el manifest oficial (configurable por el admin). Plugins de URLs arbitrarias requieren
confirmación explícita del usuario.

Handlers (en executor — I6):
- `list_marketplace_plugins()` → `{ok, plugins: [...], cached: bool}`.
- `install_plugin(download_url: str)` → `{ok, name, effect_ids}`.

### Frontend

Pestaña "Marketplace" en el lateral `Browser` (junto a Clips, Presets):
- Lista de plugins disponibles: nombre, autor, versión, descripción.
- Botón "Instalar" por plugin.
- Estado "Instalando…" con spinner durante la descarga.
- Estado "Instalado ✓" si el effect_id ya está en `EffectLibrary`.
- Mensaje de error si el plugin falla la validación del harness.

### Tests

`tests/test_marketplace.py` (con mock de `httpx.AsyncClient`):
- Mock del manifest remoto → `list_marketplace_plugins` devuelve lista parseada.
- `install_plugin` con URL de un `.py` válido → plugin instalado en `plugins/effects/`.
- `install_plugin` con archivo que falla el harness → rechazado con error, sin instalar.
- Timeout del fetch del manifest → `{ok: false, error: "timeout"}` sin crash.
- Caché: segunda llamada en < 5 min no hace fetch HTTP (usa caché).

**Aceptación**: abro el Marketplace, veo "gradient_sweep_pro v1.1" de un autor externo,
hago clic en Instalar → en 3 s el efecto aparece en el Browser y puedo asignarlo a un clip.
**Commit**: `roadmap-v4 fase N1: marketplace de plugins`.

---

## N2 — Backup y restauración completa de show (~2 días, Haiku)

**Qué**: exportar TODO lo necesario para reproducir el show en otra máquina en un ZIP:
`show.json` + `autovj.json` + `output_targets.json` (sin credenciales) + plugins custom
usados + (opcionalmente) el audio.

**Por qué**: hoy si cambias de máquina pierdes la configuración del rig y los plugins
custom. El backup completo garantiza portabilidad total — el rider técnico puede enviarte
el bundle y montas el show en tu máquina en segundos.

### Backend

`server/show_bundle.py` — NUEVO:

```python
def export_show_bundle(session, include_audio: bool = False) -> str:
    """Genera projects/<slug>/show_bundle.zip.
    output_targets.json: sustituye API keys y tokens por placeholders.
    Guardado atómico (.tmp + os.replace)."""

def import_show_bundle(zip_path: str, projects_dir: Path) -> tuple[str, list[str]]:
    """Extrae ZIP, valida MANIFEST.json, registra como nuevo proyecto.
    Devuelve (slug, warnings: list[str])."""
```

Estructura del ZIP:
```
show_bundle.zip/
  MANIFEST.json          {version, created_at, show_slug, sd_version, plugins}
  show.json
  autovj.json            (si existe)
  output_targets.json    (credenciales sustituidas por placeholders)
  plugins/effects/*.py   (solo plugins no built-in usados en el show)
  audio/<archivo>        (solo si include_audio=True y tamaño < 500 MB)
```

Handlers (en executor — I6):
- `export_show_bundle(include_audio: bool = False)` → `{ok, path}`.
- `import_show_bundle(zip_path: str)` → `{ok, slug, warnings: [str]}`.

### Frontend

- Botón "📦 Exportar Bundle" en el topbar o en la vista de lista de proyectos.
- Al importar: botón "📥 Importar Bundle" + input de archivo ZIP.
- Lista de warnings post-import (plugins no reconocidos, audio no incluido, etc.).

### Tests

`tests/test_show_bundle.py`:
- `export_show_bundle()` → ZIP existe y contiene `show.json` y `MANIFEST.json`.
- `export_show_bundle(include_audio=False)` → ZIP no contiene el archivo de audio.
- `output_targets.json` en el bundle no contiene el api_key original (tiene placeholder).
- `import_show_bundle(zip_path)` → proyecto idéntico (comparar show.json sin timestamps
  ni rutas absolutas).
- ZIP corrupto → `import_show_bundle` devuelve error limpio sin crear proyecto parcial.
- Bundle con plugin desconocido → importado con warning en la lista de warnings.

**Aceptación**: exporto el bundle de `el_taser`, lo copio a otra máquina, importo → el
show aparece con los clips correctos y los plugins custom disponibles.
**Commit**: `roadmap-v4 fase N2: backup y restauración completa de show`.

---

## Resumen de esfuerzo y orden recomendado

| # | Fase | Nombre | Días | Modelo | Depende de |
|---|------|--------|------|--------|------------|
| 1 | I1 | Grabación en vivo de macros | 2 | Sonnet | C2, A2 |
| 2 | I2 | Marcadores con nombre y color | 1 | Haiku | — |
| 3 | I3 | Grupos colapsables | 2 | Sonnet | — |
| 4 | I4 | Vista Arranger | 3 | Opus | I2 |
| 5 | I5 | Exportación PDF + CSV DMX | 2 | Haiku | B3 |
| 6 | J1 | Editor de patch visual | 3 | Sonnet | — |
| 7 | J2 | DMX completo por canal | 4 | Opus | J1, G3 |
| 8 | J3 | GDTF browser | 2 | Sonnet | J1 |
| 9 | J4 | Test fixtures avanzado | 1 | Haiku | E4 |
| 10 | K1 | Viewer 3D posicionamiento | 3 | Opus | J1 |
| 11 | K2 | Pixel mapping | 4 | Opus | — |
| 12 | K3 | Preview 2D tiempo real | 2 | Sonnet | — |
| 13 | L1 | API REST pública | 3 | Sonnet | — |
| 14 | L2 | Webhooks de eventos | 2 | Haiku | — |
| 15 | L3 | Multiusuario básico | 3 | Opus | L1 |
| 16 | M1 | Tap BPM + key detection | 2 | Sonnet | G2 |
| 17 | M2 | Generación automática de show | 4 | Opus | M1, A2 |
| 18 | M3 | Historial de gestos | 2 | Sonnet | — |
| 19 | N1 | Marketplace de plugins | 3 | Sonnet | H1 |
| 20 | N2 | Backup y restauración | 2 | Haiku | H2 |

**Total ≈ 50 días** de trabajo efectivo (~60 con overhead de integración y revisión).

### Carriles de quick-wins (empezar aquí si hay tiempo limitado)

- **I2 + I3 + K3** (~5 días): timeline con marcadores y vista colapsable + preview 2D.
  Valor inmediato para cualquier sesión de diseño.
- **J1 + J4** (~4 días): patch visual y chase test. Valor inmediato la noche del bolo.
- **L1** (~3 días): API REST. Integración con cualquier sistema externo desde el primer día.
- **N2** (~2 días): backup completo. El show es portable entre máquinas inmediatamente.

### Hitos de demo

- Tras **I1 + I4**: "diseño el show improvisando en vivo y la vista arranger me muestra la
  estructura de secciones de un vistazo".
- Tras **J1 + J2**: "parcheo 20 fixtures de tres tipos distintos (dimmers, RGB, movers) en
  el canvas visual y los pruebo con el chase test".
- Tras **K2 + K3**: "proyecto un vídeo en las barras y lo verifico en el preview 2D sin
  hardware conectado".
- Tras **L1 + L3**: "el asistente controla cues desde su tablet mientras yo diseño desde
  el PC; el sistema de sala recibe webhooks en cada cue".
- Tras **M2**: "genero un show completo de 4 minutos en 10 segundos, listo para editar".

---

## Asignación de modelos por fase

Mismos criterios que v2/v3 (riesgo × ambigüedad × concurrencia determina el modelo):

| Fase | Modelo | Por qué |
|------|--------|---------|
| I1 Grabación | Sonnet | Estado efímero en sesión + integración A2 ya conocida |
| I2 Marcadores | **Haiku** | Extensión de datos existente; lógica mínima |
| I3 Grupos colapsables | Sonnet | Puramente frontend; backend trivial |
| I4 Vista Arranger | **Opus** | Semántica de reordenado de secciones; edge cases |
| I5 Export PDF + CSV | **Haiku** | Receta cerrada; fpdf2 + CSV estándar |
| J1 Patch visual | Sonnet | Canvas UI + handlers simples; receta conocida |
| J2 DMX por canal | **Opus** | Mezcla multi-clip en canal; correctitud crítica |
| J3 GDTF browser | Sonnet | Parser XML + búsqueda en UI; sin semántica sutil |
| J4 Test avanzado | **Haiku** | Extensión de E4; asyncio.call_later simple |
| K1 Viewer 3D | **Opus** | Sincronización React ↔ rig_layout.json ↔ Three.js ↔ stream |
| K2 Pixel mapping | **Opus** | Estado de frame de vídeo + region picker + fallbacks |
| K3 Preview 2D | Sonnet | Canvas 2D + stream; sin semántica compleja |
| L1 API REST | Sonnet | FastAPI router; receta cerrada; auth simple |
| L2 Webhooks | **Haiku** | HTTP POST + HMAC + reintentos; patrón estándar |
| L3 Multiusuario | **Opus** | Control de acceso en WS de tiempo real; política de roles |
| M1 Tap + key | Sonnet | `librosa` + mediana; patrón conocido de G2 |
| M2 Generación show | **Opus** | Coherencia musical + densidad + no-solapamiento de capas |
| M3 Historial | Sonnet | Log en memoria + replay; sin semántica sutil |
| N1 Marketplace | Sonnet | HTTP + validación harness + UI; receta especificada |
| N2 Backup bundle | **Haiku** | ZIP + migración; aceptación clara |

Reparto: **Opus** 6 fases (~21 días) · **Sonnet** 9 fases (~22 días) · **Haiku** 5 fases (~8 días).
Frente a "todo con Sonnet", ahorro estimado en tokens ~22 %.

---

## Convenciones adicionales v4

1. **Schema v5**: si alguna fase añade un campo no-opcional a `show.json` que requiera
   migración activa, incrementar `version` a 5 y añadir la migración en `Timeline.load()`.
   Los campos opcionales con default (I2, K1) no requieren nuevo número de versión.

2. **REST + JSON-RPC coexisten**: los endpoints REST de L1 son wrappers ligeros sobre
   los handlers del dispatcher — sin duplicar lógica de negocio. Toda la lógica vive
   en `dispatcher.py`; el router REST solo traduce HTTP → handler → respuesta JSON.

3. **Seguridad de uploads**: K2 (pixel mapping) y N2 (import bundle) aceptan archivos
   del usuario. Validar extensiones, tamaño (máx 100 MB para imágenes/vídeo, 500 MB
   para bundles) y estructura antes de procesar. No ejecutar código embebido en los
   archivos (excepto N1 marketplace, que usa el harness H1 explícitamente para validar).

4. **REST documentado en handlers.md**: cada endpoint de L1 y los equivalentes añadidos
   posteriormente aparecen en `docs/dev/handlers.md` con la firma REST equivalente al
   handler JSON-RPC.

5. **ADRs planificados**:
   - ADR-005: K2 — decisión sobre soporte de vídeo (imageio vs cv2 vs solo imágenes).
   - ADR-006: L3 — política de autorización (qué handlers son accesibles en cada rol).

---

## Checklist de cierre de CADA fase

```
[ ] Suite pytest verde (sin saltarse tests)
[ ] Tests nuevos del módulo escritos y pasando (mínimo 5 por fase)
[ ] Test de parity si la fase toca el camino del frame (compute_frame)
[ ] npx tsc --noEmit limpio + cd web && npm run build (si toca web)
[ ] show.json viejo carga sin pérdida (si toca persistencia)
[ ] Sin imports prohibidos (core no importa server/web/fastapi)
[ ] Handlers nuevos documentados en docs/dev/handlers.md
[ ] ROADMAP_v4.md: fase marcada APLICADA con fecha y notas
[ ] CLAUDE.md actualizado si cambia arquitectura o comandos
[ ] plugin-sdk.md actualizado si cambia el contrato de plugin (K2, N1)
[ ] [v4] Endpoint REST equivalente documentado en docs/api/rest.md (si L1 ya está aplicada)
[ ] Un commit con mensaje "roadmap-v4 fase <ID>: <resumen>"
[ ] Probado A MANO el criterio de aceptación (no solo los tests)
```
