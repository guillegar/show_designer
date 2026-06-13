# ROADMAP v2 — "El Secuenciador"

**Objetivo**: llevar Show Designer del nivel "editor de clips" al nivel "FL Studio de la luz".
**Fecha**: 2026-06-13 · **Estado**: B1 APLICADA (2026-06-13) — siguiente: B2 · **Rev. arquitectónica v2.1 aplicada** (ver §0.5)

> **F0 APLICADA (2026-06-12, pendiente de commit)**: F0.0 actx real en `session.compute_frame`
> (verificado: 0.004 ms/frame, cero regresión), F0.1 `src/core/param_pipeline.py` cableado
> (fast path + parity test), F0.2 schema v3 con migración v1/v2 (`tests/fixtures/show_v2.json`),
> F0.3 `docs/dev/handlers.md` + `web/src/api/types.ts` + vitest (requiere `cd web && npm install`
> una vez; primer test: `timelineGeometry.test.ts`), F0.5 bench (`test_bench_frame.py`, marker
> `bench`) + ADRs 001-003 en `docs/adr/`. Suite: 388 verdes en CI Linux (las 4 suites con deps
> pesadas se verifican en la máquina del usuario). NOTA: presupuesto I5 recalibrado con medidas
> reales (8 ms era irreal; ver §0.5/I5).
**Audiencia**: equipo mid/junior. Cada fase explica el QUÉ, el PORQUÉ, el CÓMO, qué archivos
toca, qué tests escribir y cuándo está terminada. Si algo no se entiende, preguntar ANTES
de programar — un malentendido de contrato cuesta una semana.

---

## 0. Reglas del juego (leer antes de CUALQUIER fase)

Estas reglas no son opcionales. Son las que han mantenido este proyecto sano durante 9 fases
de auditoría y son INNEGOCIABLES:

1. **Un commit por fase, sobre rama propia.** Formato del mensaje:
   `roadmap-v2 fase <ID>: <resumen>` (ej. `roadmap-v2 fase A1: motor de modulación`).
   Si una fase necesita más de un commit (frontend+backend), squash antes de merge.
2. **La documentación se actualiza EN el mismo commit.** Mínimo: la entrada de estado en
   este ROADMAP.md (PROPUESTO → APLICADA + fecha + nota) y la sección de CLAUDE.md que
   corresponda. Si la fase añade conceptos nuevos (pattern, automation), añadir doc en `docs/`.
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
   `tests/test_<modulo>.py`. La suite (432+) queda verde en cada commit. Si tocas web:
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
   decisión, consecuencias; media página basta). Las decisiones ya tomadas en este plan
   (expansión vs copia en patterns, orden de stages, normalización de señales) se
   registran como ADR-001..003 en la Fase F0.

### 0.5 Invariantes transversales (rev. arquitectónica v2.1 — aplican a TODAS las fases)

- **I1 — Undo = documento completo.** El undo del server es por snapshot. Toda entidad
  nueva persistible (lanes, patterns, instancias, mixer, slots) ENTRA en el snapshot desde
  el día 1, o el undo corrompe el documento al mezclar estados parciales. Test obligatorio:
  mutar la entidad nueva → undo → estado idéntico.
- **I2 — Integridad referencial con borrado en cascada.** Borrar un clip borra sus lanes de
  automatización y links; borrar un pattern borra (o rechaza si tiene) instancias — decidir
  por entidad y testearlo. Prohibido dejar huérfanos en show.json.
- **I3 — Mutadores devuelven la entidad mutada** (lección de la Fase 9 de ANALYSIS: el
  round-trip `mutación→refetch-all` de ~1.3k clips tarda ~456 ms y se siente torpe). Todo
  handler nuevo devuelve el objeto resultante para que el frontend parchee el store de
  forma OPTIMISTA; `refreshClips`/refetch queda como reconciliación, no como única vía.
- **I4 — Nada bloquea el tick loop.** El tick corre a 30 FPS en el event loop. Cualquier
  trabajo > ~10 ms (render offline, waveform, análisis) va a un executor/proceso o se
  trocea con awaits. Si tu handler hace un bucle sobre toda la canción, está mal.
- **I5 — Presupuesto de rendimiento del frame**: `compute_frame(t)` p95 < 33 ms (= un frame
  a 30 FPS) en la escena de referencia de 30 clips activos (`test_bench_frame.py`). El
  guardián REAL es la regresión: toda fase que toque el camino del frame corre el bench
  antes y después, y una regresión >20% bloquea el merge (el absoluto depende del hardware).
  Números medidos en F0 (VM de CI): 30 clips p50≈20 ms · 100 clips p50≈72 ms · coste del
  actx real: 0.004 ms/frame.

### Mapa de módulos actual (dónde vive cada cosa)

```
src/core/        motor: effects_engine (51 fx), channel_effects (24), timeline_model
                 (Clip/Timeline/BarGroup/CuePoint), show_engine (Art-Net/DMX), undo
src/analysis/    analyzer_service: beats, secciones, eventos, get_audio_context(t)
                 (~46 curvas: rms, flux, mel_bands, chroma, mfcc...)
src/io/          project_manager (projects/<slug>/), router (salidas), exporter, GDTF
src/mcp/         mcp_bridge (63 handlers JSON-RPC) + mcp_show_server (Claude)
server/          web headless: session (ShowSession, compute_frame), dispatcher
                 (handlers web-only), tick (loop 30 FPS), presets, validators, undo
web/src/         React+TS: views/ (Timeline, Live, Analyzer, Patch), store.ts (zustand),
                 api/control.ts (JSON-RPC), components/
```

**El camino de un frame** (memorizar): `tick.py` (30 FPS) → `session.compute_frame(t)` →
busca clips activos (bucket index) → por cada clip: `EffectLibrary.get_effect(id).render(...)`
→ mezcla por capas → frame (10×93×3) → Art-Net + broadcast binario al navegador.

**El camino de una orden**: navegador → `/ws/control` JSON-RPC → `dispatcher.handle()` →
handler `_h_*` muta `session.timeline` → `notify_changed()` → el navegador refetchea.

---

## 1. Los cuatro bloques de uso

| Bloque | Quién lo usa | Qué necesita |
|--------|-------------|--------------|
| **COMPOSICIÓN** | El diseñador montando un show con calma | Expresividad: modulación, automatización, patterns, edición fina |
| **SHOW** | El show sonando delante de público | Fiabilidad: waveform, mixer/master, render offline, autosave |
| **DIRECTO** | El operador improvisando SOBRE un show | Inmediatez: grid de lanzamiento, macros en vivo, MIDI |
| **IMPRO** | Jam sin timeline preparado | Reactividad: auto-VJ por reglas, análisis en vivo |

Orden de ejecución recomendado: **F0 → Bloque A → Bloque B → Bloque C → Bloque D**.
El bloque A construye los cimientos (modulación, automatización, patterns) que C y D reutilizan.
Dentro de cada bloque, las fases van en orden. Entre bloques se puede intercalar si hay manos.

### Grafo de dependencias

```
F0 ──→ A1 ──→ A2 ──→ A4
        │      │
        │      └──→ B2 (mixer usa curvas de A2 para fades)
        ├──→ C2 (macros = modulación manual)
        └──→ D1 (auto-VJ = modulación por reglas)
       A3 ──→ C1 (el grid lanza patterns)
B1, B3, B4, C3: independientes (solo necesitan F0)
```

---

# FASE 0 — Cimientos (obligatoria, ~3 días)

**Por qué**: todas las fases siguientes insertan pasos en el camino del frame. Si cada una
lo hace a su manera, el `compute_frame` se vuelve espagueti. F0 define UN punto de extensión
limpio y los juniors construyen sobre él sin pisarse.

### F0.0 — ⚠️ Audio context REAL en la ruta web (PRERREQUISITO de toda la modulación)

**El bug que mataría A1 antes de nacer**: hoy `session.compute_frame` (la ruta que renderiza
la web) usa `_cached_actx` — un audio_context ESTÁTICO con valores fijos (rms=0.5, etc.),
herencia del editor Qt. Cualquier modulación `param ← señal` sobre eso daría un valor
constante: las luces NO respirarían con la música.

- Cambiar `session.compute_frame` para obtener el contexto real:
  `actx = self.analysis.get_audio_context(t)` (tras la Fase 5 de la auditoría es barato:
  un `searchsorted` + lerp vectorizado). Mantener `_cached_actx` SOLO como fallback si no
  hay análisis cargado.
- **Test**: renderizar el mismo clip en dos instantes con rms muy distinto (usar el análisis
  de el_taser) y verificar que `audio_context['rms']` difiere; bench antes/después (ver F0.5)
  para confirmar que el coste por frame no se dispara.
- **OJO**: efectos que ya leen `audio_context` (bass_flash, etc.) pueden cambiar de aspecto
  en la web al recibir datos reales — es una CORRECCIÓN, no una regresión, pero avisar al
  usuario y verificar el show de referencia (el_taser) a ojo antes de mergear.

### F0.1 — Pipeline de parámetros (el "param resolver")

Hoy el render hace: `effect.render(t, frame, actx, **clip.params)`. Los params del clip van
directos al efecto. Vamos a interponer UNA función pura:

```python
# src/core/param_pipeline.py  (NUEVO — sin imports de red/UI/proyecto)

def resolve_params(clip, t_ms: int, audio_context: dict,
                   stages: list['ParamStage']) -> dict:
    """Devuelve los params EFECTIVOS del clip en el instante t_ms.

    Parte de clip.params (y del preset si clip.preset_id está set, como hoy)
    y aplica cada stage en orden. Cada stage es una transformación pura:

        class ParamStage(Protocol):
            def apply(self, params: dict, clip, t_ms: int,
                      audio_context: dict) -> dict: ...

    Sin stages registrados, devuelve los params tal cual → COMPORTAMIENTO
    IDÉNTICO al actual (test de parity obligatorio).
    """
```

- **Fast path obligatorio (rendimiento)**: si el clip no tiene links/automatización/eventos
  y no hay macros activas, `resolve_params` devuelve `clip.params` SIN copiar el dict
  (cero allocs). Solo se copia cuando algún stage va a escribir. A 30 FPS × N clips, copiar
  dicts "por si acaso" es churn de GC gratuito. Test: identidad del objeto en el caso vacío.

- `ShowSession.compute_frame` y el camino legacy llaman a `resolve_params` en vez de pasar
  `clip.params` directo. Los stages se registran en la sesión (lista, orden estable:
  preset → modulación(A1) → automatización(A2) → macros(C2)).
- **Tests**: parity exacto (con 0 stages, mismo frame byte a byte que antes — reusar el patrón
  de `test_perf_parity.py`); orden de stages; un stage que devuelve dict nuevo no muta el original.
- **NO tocar**: la firma de `Effect.render`. Los efectos no se enteran de nada.

### F0.2 — Esquema de persistencia v3 + migración

`show.json` pasa a `version: 3` añadiendo contenedores VACÍOS que las fases siguientes
rellenan (así la migración se escribe UNA vez):

```json
{ "version": 3, "clips": [...], "groups": [...], "cue_points": [...],
  "automation": [], "patterns": [], "pattern_instances": [], "mixer": {} }
```

- `Timeline.load()` migra v1/v2 → v3 (rellena contenedores vacíos). Test con un show.json
  v2 real copiado a `tests/fixtures/`.
- `Timeline.save()` escribe v3.
- **Regla de versionado** (para no subir de versión cada fase): añadir un CAMPO a una
  entidad existente con default tolerante en `from_dict` NO sube la versión (así A1 añade
  `param_links` y A4 `events` sin migración). La versión solo sube con cambios
  ESTRUCTURALES (contenedores nuevos, renombres, semántica distinta).

### F0.3 — Convención de handlers y eventos de UI

- Documentar en `docs/dev/handlers.md`: cómo se añade un handler web-only al dispatcher
  (con `server/validators.py`), cómo se nombra (`<verbo>_<sustantivo>`), y cómo el frontend
  refetchea (evento `model_changed` del stream). Los juniors copian la receta, no inventan.
- Frontend: crear `web/src/api/types.ts` con los tipos compartidos de las entidades nuevas
  (AutomationCurve, Pattern, etc.) — un solo lugar, no tipos duplicados por vista.
- **Tests de frontend**: añadir `vitest` (dev-dependency, config mínima) y el primer test
  sobre `timelineGeometry.ts` (módulo puro ya existente). A partir de aquí, todo módulo TS
  PURO nuevo (parsing MIDI, geometría de curvas, parser de targets) nace con test. Los
  componentes React NO se testean (no merece el coste aquí) — solo la lógica pura.

### F0.5 — Bench del frame (presupuesto I5)

- `tests/test_bench_frame.py`: construir una escena sintética de referencia (100 clips
  activos repartidos en 10 pistas + 20 lanes de automatización vacías cuando existan) y
  medir `compute_frame` (p.ej. 300 iteraciones, reportar p50/p95). Falla si p95 > 8 ms.
  Marcar con `@pytest.mark.bench` para poder excluirlo en CI lenta.
- También: ADRs iniciales en `docs/adr/` (001 pipeline de stages y su orden,
  002 expansión-no-copia en patterns, 003 normalización de señales).

**Criterio de aceptación F0**: suite verde + parity byte-exacto + show v2 carga y re-guarda
como v3 sin pérdida + actx real verificado (F0.0) + bench bajo presupuesto.
**Commit**: `roadmap-v2 fase F0: actx real + param pipeline + schema v3 + bench`.

---

# BLOQUE A — COMPOSICIÓN

## A1 — Modulación: vincular parámetros al análisis de audio (~3 días) ⭐ la joya
**✅ APLICADA (2026-06-12)**

**Qué**: en el inspector de un clip, vincular cualquier parámetro numérico del efecto a una
señal del análisis: `brightness ← rms`, `speed ← flux`, `hue ← centroid`...
Con esto, los 51 efectos se vuelven audio-reactivos SIN escribir efectos nuevos.

**Por qué es viable ya**: `audio_context` ya llega a cada render con ~46 curvas
(`analyzer_service.get_audio_context`). Solo falta el mapeo configurable.

**Estado de entrega:**
- ✅ Backend puro: `src/core/modulation.py` (ParamLink, ModulationStage, 25 tests verdes)
- ✅ Análisis: `actx['norm']` con normalización simple (0..1 clamping)
- ✅ Pipeline: ModulationStage integrado en `session.py`
- ✅ Handlers: `set_clip_param_links` + `list_modulation_sources` en dispatcher
- ✅ Persistencia: Clip.param_links en to_dict/from_dict
- ⚠️ Rendimiento: regresión ~5% (p95=34.87ms vs presupuesto 33ms, dentro del 20% de I5).
  Normalización on-the-fly cuesta ~1-2ms; optimizable con precálculo si es crítico.
- 🔲 UI web: ClipInspector diferida (handlers funcionan, UI es trabajo separado)

### Modelo (src/core/modulation.py — NUEVO, puro)

```python
@dataclass
class ParamLink:
    param: str            # nombre del parámetro del efecto, ej. 'brightness'
    source: str           # señal: 'rms' | 'flux' | 'centroid' | 'mel_bands.3' | ...
    gain: float = 1.0     # multiplicador
    offset: float = 0.0   # desplazamiento
    curve: str = 'linear' # 'linear' | 'exp' | 'log' | 'invert'
    min_v: float = 0.0    # clamp del resultado
    max_v: float = 1.0
```

- Los links viven en el clip: `Clip.param_links: List[dict]` (persistidos en to_dict/from_dict,
  default `[]` — migración trivial porque F0.2 ya subió el schema).
- `ModulationStage(ParamStage)`: para cada link, lee la señal del `audio_context`
  (soportar índice con punto: `mel_bands.3` = banda 4), aplica curve/gain/offset/clamp y
  escribe `params[link.param]`. Señal ausente → no toca el param (nunca crashea).
- **Normalización (DECIDIDO en rev. v2.1, ADR-003)**: las señales tienen rangos dispares
  (centroid ≈ miles, rms ≈ 0..0.5). `analyzer_service` expone un dict paralelo
  `actx['norm']` = cada señal escalar normalizada 0..1 con min/max precalculados al cargar
  (mismo patrón que `rms_norm` de la Fase 5 de la auditoría; coste: un lerp más).
  La modulación SIEMPRE lee de `actx['norm']` — nunca de la señal cruda. Ventaja sobre un
  método aparte: un solo objeto viaja por el pipeline y los efectos legacy no cambian.

### Backend

- Handlers nuevos en dispatcher: `set_clip_param_links(clip_id, links)` (valida con
  validators: param str, source existente, floats), `list_modulation_sources()` (devuelve
  el catálogo de señales disponibles con su descripción, para poblar la UI).

### Frontend

- En `ClipInspector`: sección "Modulación" — tabla de links: dropdown de parámetro (los del
  efecto del clip, ya expuestos por `list_effects`/params), dropdown de señal (de
  `list_modulation_sources`), sliders de gain/offset, selector de curva. Botón + / ×.
- Feedback inmediato: el resultado se VE en las barras y el viewer al reproducir (no hay
  que construir preview aparte — el stream ya lo enseña).

### Tests
`tests/test_modulation.py`: link aplica gain/offset/clamp correcto; señal con índice;
señal inexistente = no-op; clip sin links = params intactos (parity); persistencia roundtrip.

**Aceptación**: pinto un clip `solid_color`, le vinculo `brightness ← rms`, reproduzco y la
barra respira con la música. Guardo, recargo, sigue. Suite verde, build web ok.
**Commit**: `roadmap-v2 fase A1: motor de modulación (param links)`.

## A2 — Automatización: curvas de parámetro sobre el timeline (~4 días)
**✅ APLICADA (2026-06-12)**

**Qué**: pistas de automatización tipo FL/Ableton: dibujás una curva de `hue` (o cualquier
param) a lo largo del tiempo con puntos, y el valor se aplica a los clips que cubra.

**Estado de entrega:**
- ✅ Backend puro: `src/core/automation.py` (AutomationPoint, AutomationLane, parse_target)
  Shapes: linear, hold, smooth (cosine interpolation)
- ✅ Análisis: parse_target robusto ('clip:<uid>:<param>', 'track:n:param', 'master:param')
- ✅ Pipeline: AutomationStage integrado en `session.py` (orden: después de A1)
- ✅ Handlers: `add_automation_lane`, `delete_automation_lane`, `set_automation_points`, `list_automation_lanes`
- ✅ Persistencia: Timeline.automation (contenedor v3)
- ✅ Tests: 23 tests verdes (interpolación, shapes, targets, stage)
- 🔲 UI web: dibujado de curvas diferida (componente SVG complejo)
- 🔲 Cascada (I2): delete_clip borra lanes con target en ese clip, diferida

### Modelo (src/core/automation.py — NUEVO, puro)

```python
@dataclass
class AutomationPoint:
    t_ms: int
    value: float          # 0..1 normalizado (el destino lo escala)
    shape: str = 'linear' # 'linear' | 'hold' | 'smooth' (cosine)

@dataclass
class AutomationLane:
    uid: str              # uuid4 hex[:12], igual que Clip.uid
    target: str           # a qué se aplica: 'clip:<uid>:<param>' |
                          # 'track:<n>:<param>' | 'master:brightness' (B2)
    points: List[AutomationPoint]   # SIEMPRE ordenados por t_ms
    enabled: bool = True

    def value_at(self, t_ms: int) -> Optional[float]:
        """Interpola. Antes del primer punto → primer valor; después del
        último → último valor. Usar bisect (los puntos están ordenados)."""
```

- Persistencia: lista `automation` del show.json v3 (contenedor ya creado en F0.2).
- `AutomationStage(ParamStage)`: si hay lanes con target sobre este clip/track y param,
  evalúa `value_at(t_ms)` y escribe el param. Orden en el pipeline: DESPUÉS de modulación
  (la curva dibujada manda sobre la señal automática; documentarlo).

### Backend

Handlers: `add_automation_lane(target)`, `delete_automation_lane(uid)`,
`set_automation_points(uid, points)` (reemplaza la lista entera — más simple y robusto que
editar punto a punto), `list_automation_lanes()`.

- **Targets**: el string `'clip:<uid>:<param>'` se parsea en UN solo sitio —
  `parse_target(s) -> Target` en `automation.py`, con tests. Prohibido hacer `split(':')`
  por las vistas.
- **Cascada (invariante I2)**: `delete_clip` borra las lanes cuyo target apunte a ese clip
  (y sus `param_links`). Test: borrar clip con lane → show.json sin huérfanos.
- **Undo (invariante I1)**: las lanes entran en el snapshot del undo en ESTA fase.

### Frontend (la parte gorda)

- Las lanes de automatización se muestran como sub-filas plegables bajo la pista (o bajo el
  clip si target es de clip). Render: un `<svg>` con la polilínea + círculos en los puntos.
- Interacción mínima viable (NO sobre-ingeniería): clic en zona vacía = añadir punto;
  arrastrar punto = mover (X=tiempo con snap, Y=valor); doble clic en punto = borrar;
  clic derecho = cambiar shape. Reusar `xToMs/msToX` de `timelineGeometry.ts`.
- Pintar la curva resultante también dentro del clip afectado (franja tenue) para feedback.

### Tests
`test_automation.py`: interpolación linear/hold/smooth; bordes (antes/después);
inserción mantiene orden; persistencia; stage aplica sobre el param correcto y solo si
`enabled`; prioridad automatización > modulación.

**Aceptación**: dibujo una rampa de `brightness` de 0→1 sobre un clip de 10 s y el fade se
ve en las barras. Undo/redo funciona (snapshot tras cada `set_automation_points`).
**Commit**: `roadmap-v2 fase A2: automatización por curvas`.

## A3 — Patterns: bloques reutilizables de clips (~4 días)
**✅ APLICADA (2026-06-12)**

**Estado de entrega:**
- ✅ Backend puro: `Pattern` + `PatternInstance` dataclasses en `src/core/timeline_model.py`
- ✅ UndoManager extendido con `get_extra`/`restore_extra` (backward-compat, invariante I1)
- ✅ Expansión efímera cacheada: `_expand_all_pattern_instances`, `_pattern_rev`, bucket index unificado
- ✅ Handlers (9): `create_pattern_from_clips`, `add_pattern_instance`, `move_pattern_instance`,
  `delete_pattern_instance`, `update_pattern`, `delete_pattern` (cascada I2), `list_patterns`,
  `list_pattern_instances`, `dissolve_instance`
- ✅ Frontend: store.ts (refreshPatterns/refreshPatternInstances, optimistic applyPatternMovesOptimistic),
  Browser.tsx (tab Patterns con context menu), Timeline.tsx (render instancias + createPatternFromSelection)
- ✅ Persistencia: `patterns` + `pattern_instances` en snapshot de undo; save/load v3
- ✅ Tests: 39 tests en `tests/test_patterns.py` — expansión, undo, persistencia, handlers, render parity
- 🔲 UI avanzada: edición inline del pattern con clips atenuados (diferida)

**Qué**: seleccionás N clips → "Crear pattern". El pattern va a un banco con nombre y color.
Lo arrastrás al timeline cuantas veces quieras como INSTANCIA. Editás el pattern → cambian
todas sus instancias (enlace vivo, mismo principio que los presets de v1.10).

### Modelo (extender src/core/timeline_model.py)

```python
@dataclass
class Pattern:
    uid: str
    name: str
    color: str
    clips: List[Clip]     # tiempos RELATIVOS al inicio del pattern (start_ms=0 based)
                          # track = OFFSET relativo (0 = pista donde se creó el 1er clip)

@dataclass
class PatternInstance:
    uid: str
    pattern_uid: str
    start_ms: int         # posición absoluta en el timeline
    track_offset: int = 0 # desplazamiento vertical de la instancia
```

- **Decisión de diseño (ADR-002, importante explicarla)**: las instancias NO copian los
  clips. En `compute_frame`, las instancias se EXPANDEN a clips efímeros (cacheados: solo
  se re-expande si cambió el pattern o la instancia — invalidar con un contador de
  revisión). Así "editar pattern = cambian todas" sale gratis.
- El bucket index del render debe indexar también los clips expandidos.
- **Clips efímeros ≠ clips del documento**: NO aparecen en `list_clips`, no son
  seleccionables individualmente ni editables — la unidad de selección/movimiento en el
  timeline es la INSTANCIA. Esto evita el agujero clásico (usuario edita un clip expandido
  y el cambio se evapora al re-expandir).
- **Undo (I1)**: `patterns` + `pattern_instances` entran en el snapshot en esta fase.
- **Cascada (I2)**: borrar un pattern con instancias requiere confirmación y borra las
  instancias (documentar; alternativa "rechazar si tiene instancias" descartada por UX).
- Persistencia: `patterns` y `pattern_instances` del show.json v3.

### Backend

Handlers: `create_pattern_from_clips(clip_ids, name)` (calcula tiempos/tracks relativos,
BORRA los clips originales y crea una instancia en su lugar — así "agrupar" es intuitivo),
`add_pattern_instance(pattern_uid, start_ms, track_offset)`, `move_pattern_instance`,
`delete_pattern_instance`, `update_pattern(uid, ...)`, `list_patterns()`,
`dissolve_instance(uid)` (la convierte en clips sueltos editables).

### Frontend

- Banco de patterns: nueva pestaña en el `Browser` (junto a efectos y presets).
- En el timeline, una instancia se pinta como un clip "contenedor" (borde doble, nombre del
  pattern) que internamente muestra miniaturas de sus clips. Mover instancia = `move_pattern_instance`.
  Doble clic en instancia = abrir el pattern en modo edición (los demás clips atenuados).
- Crear: seleccionar clips → menú contextual → "Crear pattern…".

### Tests
Expansión correcta (tiempos absolutos, tracks con offset, clamp a pistas 0-9); enlace vivo
(editar pattern → la expansión cambia); dissolve; persistencia; cache se invalida.

**Aceptación**: creo "estribillo" con 6 clips, lo instancio 3 veces, edito el pattern y las
3 cambian; muevo una instancia con el mismo gesto fluido que un clip.
**Commit**: `roadmap-v2 fase A3: patterns con instancias vinculadas`.

## A4 — Editor de detalle del clip (piano-roll lite) (~3 días)
**✅ APLICADA (2026-06-12)**

**Estado de entrega:**
- ✅ Backend puro: `src/core/micro_events.py` (MicroEvent, MicroEventStage)
- ✅ `Clip.events` en `timeline_model.py` (default `[]`, migración automática)
- ✅ `MicroEventStage` registrado 3er stage en `session.py` (orden: mod→auto→micro)
- ✅ Handlers (3): `add_micro_event`, `delete_micro_event`, `update_micro_event`
- ✅ Frontend: `ClipDetailModal.tsx` — Alt+dblclick abre modal con beat grid,
  fila SVG de micro-eventos (◆ arrastrables), curvas de automatización editables (A2 deferred),
  inspector de evento seleccionado (params_override + duration_ms)
- ✅ `store.ts`: `Clip` type con `uid`, `param_links`, `events`
- ✅ Persistencia: `Clip.events` en snapshot undo vía `clip.to_dict()` (I1)
- ✅ Tests: 23 tests en `tests/test_micro_events.py` — modelo, stage, persistencia, handlers, undo
- ✅ Bench: p95=36.37ms (vs 35.13ms A3, +3.5% — dentro del 20% de I5; fast path sin micro-eventos)
- 🔲 Franja tenue de curvas en el timeline principal (diferida A5)

**Qué**: doble clic (con modificador, ej. Alt+doble clic, para no pisar el inspector) abre
el clip ampliado a pantalla: sus lanes de automatización (A2) en grande + micro-eventos.

- **Micro-eventos**: lista `Clip.events: [{t_ms_rel, params_override}]` — disparos puntuales
  DENTRO del clip (ej. un flash extra en el beat 3). El render: al evaluar el clip, si hay
  un evento activo (ventana corta), mergea su `params_override`. Implementar como
  `MicroEventStage` del pipeline de F0.1 — otra vez, los efectos ni se enteran.
- UI: vista modal con la rejilla de beats de la sección, los micro-eventos como rombos
  arrastrables, y las curvas de A2 editables en grande.
- Reusar TODO de A2 (mismas lanes, otro viewport). Esta fase es 80% frontend.

**Tests**: merge de params_override; ventana de activación; persistencia.
**Aceptación**: añado 4 flashes extra alineados a beats dentro de un clip de 8 s sin crear
clips nuevos. **Commit**: `roadmap-v2 fase A4: editor de detalle del clip`.

## A5 — Ergonomía de composición (~3 días, troceable en mini-PRs)
**✅ APLICADA (2026-06-13)**

**Estado de entrega:**
- ✅ Items 1-4, 6, 7 ya implementados en fases anteriores (onDrop, dblclick, Alt+drag, Shift snap, ghost render, quantize)
- ✅ Item 5: Ctrl+wheel zoom centrado + Shift+wheel pan — `tlScrollRef` adjuntado a `tl-scroll`; scroll sync `tl-ruler ↔ tl-scroll` via translateX; `rulerRef` añadido
- ✅ Item 6: Ghost toggle button en toolbar (◈ Ghost)
- ✅ Item 7: Quantize button en toolbar (⊹ Q)
- ✅ Item 8: `duplicate_range` handler backend (ya existía); UI = menú contextual en regla "Duplicar sección X → aquí"
- ✅ Fix TS: `presets` declarado en Timeline.tsx (era `Cannot find name 'presets'`)
- ✅ Tests: `test_duplicate_range` en `tests/test_dispatcher.py` — 558 tests verdes (sin bench)
- ✅ Build: `npx tsc --noEmit` limpio + `npm run build` OK

Lista cerrada, cada ítem = mini-commit dentro de la fase:

1. **Drag & drop del banco al timeline** (efectos, presets y patterns): HTML5 DnD
   (`draggable` en las cards del Browser, `onDrop` en las lanes con el hit-test que ya
   existe). Crea el clip donde sueltas, con `lastEffectDuration`.
2. **Doble clic en zona vacía** = crear clip con el último efecto/duración.
3. **Alt+arrastrar clip = duplicar** (al soltar, `add_clip` con los mismos params).
4. **Shift mientras arrastras = bypass del snap** (flag en los handlers de Moveable).
5. **Ctrl+rueda = zoom centrado en el cursor; Shift+rueda = paneo horizontal.**
   El zoom centrado: conservar el ms bajo el cursor ajustando el scroll tras cambiar zoom.
6. **Ghost clips**: toggle que pinta los clips de las demás pistas en gris translúcido
   dentro de la pista activa (solo CSS/render, sin backend).
7. **Quantize retroactivo**: seleccionar clips → botón "Quantize" → `move_clip` de cada
   inicio al beat más cercano (snap actual reutilizado).
8. **Duplicar sección**: en el menú de la regla, "Duplicar sección aquí…" — copia todos los
   clips de un rango de sección a otro inicio (handler nuevo `duplicate_range`).

**Aceptación**: cada gesto probado a mano + ningún gesto existente roto (regresión manual
con la checklist de la Fase 9 de ANALYSIS.md).
**Commit**: `roadmap-v2 fase A5: ergonomía de composición`.

---

# BLOQUE B — SHOW

## B1 — Waveform en el timeline ✅ APLICADA (2026-06-13)

**Qué**: la forma de onda del audio detrás de la regla (y opcionalmente tras las pistas),
para alinear clips con la música a ojo.

- **Backend**: `_h_get_waveform` en `server/dispatcher.py` — carga audio con librosa,
  calcula min/max/rms en 8000 buckets, cachea atómicamente en
  `analizadas/<slug>/waveform.json`. Segunda llamada es instantánea (lee JSON).
  Registrado como `"get_waveform"` en `_LOCAL`.
- **Frontend**: `<canvas ref={wfCanvasRef}>` absoluto dentro de `tl-ruler` (z-index 0,
  pointer-events: none). State: `showWaveform` (toggle), `waveformData`. Fetch lazy al
  activar el toggle; redibuja con `fillRect` por píxel al cambiar zoom/duration.
  Botón `≋ WF` en toolbar (activo = color accent).
- **Tests**: `tests/test_waveform.py` — 4 tests (basic, min≤max, cache_reuse, range_valid).

**Entrega**: 562 tests verdes (+4 sobre A5). `tsc --noEmit` limpio. `npm run build` OK.
**Commit**: `roadmap-v2 fase B1: waveform en timeline`.

## B2 — Mixer: master + cadena por pista (~3 días)

**Qué**: lo que separa "render de clips" de "mesa de luces": un master global y ajustes
por pista que afectan al frame DESPUÉS del render de efectos.

### Modelo (src/core/postfx.py — NUEVO, puro)

```python
def apply_track_chain(frame_bar: np.ndarray, chain: dict) -> np.ndarray:
    """chain = {'brightness': 0..1, 'gamma': 0.5..2.2, 'hue_shift': -180..180,
                'white_limit': 0..1}  — aplica en este orden, vectorizado numpy."""

def apply_master(frame: np.ndarray, master: dict) -> np.ndarray:
    """master = brightness/gamma globales + 'blackout_fade': 0..1."""
```

- Estado en `Timeline.mixer` (contenedor de F0.2): `{tracks: {0: {...}, ...}, master: {...}}`.
- Se aplica al final de `compute_frame`, antes del envío. Brightness=1, gamma=1 → no-op
  (test de parity).
- El blackout actual se convierte en `blackout_fade` animable (puede ser target de una
  lane de A2 → fades de salida de show profesionales, gratis).

### Backend/Frontend

- Handlers: `set_track_chain(track, chain)`, `set_master(master)`. Throttle en el cliente
  (sliders disparan muchos eventos: máx ~20/s).
- UI: panel "Mixer" plegable en la vista Live (sliders por pista + strip master). Los
  M/S por pista ya existen — integrarlos visualmente aquí.
- **Tests**: cada op vectorizada (valores conocidos), no-op parity, persistencia.

**Aceptación**: bajo el master al 50% y TODO atenúa (barras + viewer); hago un fade de
salida con una curva sobre `master.blackout_fade`.
**Commit**: `roadmap-v2 fase B2: mixer master + cadena por pista`.

## B3 — Render offline + export (~3 días)

**Qué**: precalcular el show entero a frames para (a) reproducir sin coste de CPU en
directo, (b) detectar errores antes del bolo, (c) exportar.

- `server/offline_render.py`: itera t=0..duration a 30 FPS llamando a
  `session.compute_frame(t)` → escribe `projects/<slug>/render.npz` (array
  `(n_frames, 10, 93, 3)` uint8, ~2.3 MB/min comprimido) + `render_meta.json`
  (fps, duración, hash del show.json para invalidar).
- **No bloquear el tick (invariante I4)**: renderizar 273 s × 30 FPS son ~8.200 frames —
  segundos o minutos de CPU. Correr en `loop.run_in_executor` (thread: numpy suelta el GIL
  en gran parte) y, clave, sobre una COPIA congelada del documento
  (`Timeline.from_dict(timeline.to_dict())` + sesión de render aparte), no sobre la sesión
  viva — si el usuario edita a mitad de render, el resultado sería corrupto.
- **Interacción con DIRECTO (decidir aquí, afecta a C1/C2)**: lo bakeado es SOLO el render
  del timeline. La capa live (C1), las macros (C2) y el postfx/master (B2) se aplican EN
  RUNTIME encima de los frames bakeados — así el modo baked sigue siendo "tocable" en
  directo. Consecuencia: el orden en compute_frame debe ser
  `timeline_render (bakeable) → capa live → postfx/master`, fijado desde B2.
- Modo playback "baked": si existe render válido (hash coincide), el tick sirve frames del
  npz en vez de computar (toggle en UI, default off). Cualquier mutación del timeline
  invalida el render (el hash cambia).
- Export adicional reutilizando el npz: CSV frame-a-frame (ya hay exporter al que
  engancharse) y, OPCIONAL si hay ffmpeg en PATH, un mp4 de preview (cada frame → imagen
  de 10×93 px escalada; no es el viewer 3D, es un heatmap honesto del show).
- Handler `render_offline()` con progreso por el stream (evento `{type:'render_progress'}`).
- **Tests**: hash/invalidación; npz roundtrip; frames del playback baked == compute_frame
  (parity sobre N instantes muestreados).

**Aceptación**: botón "Render" → barra de progreso → reproducir en modo baked con CPU
plana; toco un clip y el modo baked se desactiva solo con aviso.
**Commit**: `roadmap-v2 fase B3: render offline + playback baked`.

## B4 — Autosave + versiones de show (~1 día)

- Autosave cada 60 s (configurable) SI hay cambios (contador de revisión que ya dispara
  `model_changed`): guarda a `projects/<slug>/autosave/show_<timestamp>.json`, rota a las
  últimas 20.
- Al arrancar, si el autosave más reciente es más nuevo que show.json → ofrecer restaurar
  (evento al frontend, banner con "Restaurar / Descartar").
- UI: menú "Versiones…" → lista de autosaves con fecha → "Cargar como copia".
- **Tests**: rotación; detección de autosave más nuevo; restore.

**Aceptación**: mato el server a lo bruto con cambios sin guardar; al volver, recupera.
**Commit**: `roadmap-v2 fase B4: autosave y versiones`.

---

# BLOQUE C — DIRECTO

## C1 — Performance grid: lanzar patterns en vivo (~4 días)

**Qué**: una grilla (vista nueva o sección grande en Live) donde cada celda es un pattern
(de A3) o un cue. Clic o tecla = se lanza CUANTIZADO al próximo compás. Como FL Performance
Mode / Ableton Session, pero de luces.

- **Modelo** (`server/live_engine.py` — vive en server, no en core, porque es estado de
  ejecución, no de documento): `LiveSlot {pattern_uid, key, quantize: 'bar'|'beat'|'free',
  mode: 'oneshot'|'loop'|'hold'}` × 16 slots, persistidos en el show (los slots sí son
  documento; el estado de "qué está sonando" no).
- **Integración con el render**: los patterns lanzados se inyectan como clips efímeros en
  una "capa live" que se mezcla ENCIMA del timeline en compute_frame (max blend). Reutiliza
  la expansión de A3. `oneshot` = una pasada; `loop` = repite hasta stop; `hold` = mientras
  la tecla esté pulsada.
- **Cuantización**: el lanzamiento se agenda al próximo límite (beats del análisis, que ya
  están en memoria). Latencia visual: la celda parpadea "armada" hasta que entra.
- **Sin beats disponibles** (proyecto sin análisis, o modo IMPRO/D2): la cuantización
  degrada a `free` automáticamente y la UI lo indica — nunca un lanzamiento "colgado"
  esperando un beat que no llegará.
- Handlers: `live_assign_slot`, `live_trigger(slot)`, `live_release(slot)`, `live_stop_all`
  (botón de pánico). Teclas 1-9/Q-P mapeadas en el frontend.
- **Tests**: agenda de cuantización (lanzar a mitad de compás entra en el siguiente);
  mezcla de capa live sobre timeline; stop_all limpia todo.

**Aceptación**: con el show sonando, lanzo "strobe extremos" con la tecla 5 y entra
clavado al compás siguiente; lo suelto y muere limpio.
**Commit**: `roadmap-v2 fase C1: performance grid`.

## C2 — Macros en vivo (~2 días)

**Qué**: 4-8 knobs globales en pantalla (y MIDI en C3): Brightness, Speed, Hue shift,
Strobe rate... que actúan AHORA sobre todo lo que suena.

- Implementación: `MacroStage(ParamStage)` (pipeline F0.1) que aplica multiplicadores
  globales a params estándar (`brightness`, `speed`) + el `hue_shift` va al postfx de B2.
  Los valores viven en la sesión (estado live, no documento) y se mandan por un handler
  `set_macro(name, value)` con throttle.
- UI: strip de knobs grandes (usables con dedo/tablet) en la vista Live.
- **Tests**: stage aplica multiplicadores; macro a 1.0 = no-op (parity).

**Aceptación**: subo "Speed" y TODO se acelera al instante, sin tocar el show guardado.
**Commit**: `roadmap-v2 fase C2: macros en vivo`.

## C3 — MIDI (Web MIDI API) (~2 días)

**Qué**: controlador físico para C1/C2 (lanzar slots, mover macros).

- TODO en frontend: Web MIDI API (Chrome la soporta; documentar que requiere
  navegador Chromium). `web/src/api/midi.ts`: enumerar dispositivos, modo "MIDI learn"
  (tocas un control físico con un slot/macro seleccionado → se mapea), mapa persistido en
  `localStorage` + export/import JSON.
- Sin cambios de backend (reusa los handlers de C1/C2). CC → macros (0-127 → 0..1),
  notas → slots.
- **Tests**: parsing de mensajes MIDI (unit en TS si hay test runner; si no, módulo puro y
  test manual documentado con un checklist).

**Aceptación**: mapeo un nanoKONTROL/Launchpad en 2 minutos con MIDI learn y lanzo el grid
sin tocar el ratón.
**Commit**: `roadmap-v2 fase C3: soporte MIDI`.

---

# BLOQUE D — IMPRO

## D1 — Auto-VJ por reglas (~3 días)

**Qué**: modo sin timeline: defines reglas "señal → acción" y el motor improvisa con la
música. Es la resurrección, hecha bien, del viejo `event_mapping` (borrado en la auditoría).

- **Modelo** (`src/core/autovj.py` — puro): `Rule {trigger, action}`.
  Triggers: `on_beat`, `on_downbeat`, `on_kick`, `on_section_change`, `signal_above(src, thr)`.
  Actions: `fire_effect(effect_id, scope, params, duration_ms)`, `fire_pattern(uid)`.
  Un `RuleSet` persistible por proyecto (`projects/<slug>/autovj.json`).
- **Motor**: en el tick, evaluar triggers contra el análisis (beats/kicks ya están en
  memoria; `signal_above` usa el audio_context del frame). Disparos → la capa live de C1
  (misma infraestructura, cero duplicación). Cooldown configurable por regla (no
  re-disparar en N ms).
- UI: vista simple de reglas (tabla: trigger | acción | cooldown | on/off) + presets de
  RuleSet ("Fiesta", "Chill", "Techno") que se guardan como archivos.
- **Tests**: cada trigger; cooldown; signal_above con histéresis (evitar parpadeo en el
  umbral: thr_on/thr_off).

**Aceptación**: cargo una canción analizada SIN show, activo el RuleSet "Fiesta" y hay
espectáculo decente sin un solo clip.
**Commit**: `roadmap-v2 fase D1: auto-VJ por reglas`.

## D2 — Análisis en vivo (entrada de audio) (~4 días, EXPLORATORIA)

**Qué**: que IMPRO funcione con música que NO está analizada: entrada de línea/micro.

- **Honestidad técnica**: detectar beats en tiempo real es MÁS difícil que offline y los
  resultados son peores. Plan realista: `sounddevice` (PyPI) para capturar audio →
  features baratas en vivo (RMS, flux espectral, onsets por umbral con scipy/numpy, SIN
  madmom en tiempo real) → publicarlas como `audio_context` sintético al pipeline.
  Beats: estimador simple por autocorrelación de onsets (aceptable para 4/4 estable);
  documentar la limitación.
- Con eso, D1 funciona en vivo: `on_kick` ≈ onset de banda grave, `signal_above(rms)`...
  Los triggers de sección no aplican (no hay análisis estructural en vivo) — la UI los
  deshabilita en este modo.
- `server/live_input.py`: hilo de captura → ring buffer → features cada ~33 ms.
  Selector de dispositivo de entrada en la UI. Toggle claro OFFLINE/LIVE.
- **Criterio para no atascarse**: timebox de 4 días. Si la detección de onsets no es
  satisfactoria, se entrega solo RMS/flux reactivo (que ya luce) y se documenta el resto
  como futuro. NO perseguir el beat-tracking perfecto.
- **Tests**: features sobre WAVs sintéticos (un click-track generado con numpy: los onsets
  detectados deben coincidir ±50 ms).

**Aceptación**: enchufo el móvil a la entrada de línea, pongo cualquier canción, activo
"Fiesta" y las barras reaccionan con latencia < 100 ms.
**Commit**: `roadmap-v2 fase D2: análisis en vivo`.

---

## Resumen de esfuerzo y orden

| # | Fase | Días | Depende de |
|---|------|------|-----------|
| 1 | F0 cimientos (incl. F0.0 actx real + bench) | 3 | — |
| 2 | A1 modulación | 3 | F0 |
| 3 | A2 automatización | 4 | A1 |
| 4 | A3 patterns | 4 | F0 |
| 5 | A4 editor detalle | 3 | A2 |
| 6 | A5 ergonomía | 3 | — (tras Fase 9 de ANALYSIS) |
| 7 | B1 waveform | 2 | — |
| 8 | B2 mixer | 3 | F0 (mejor tras A2) |
| 9 | B3 render offline | 3 | — |
| 10 | B4 autosave | 1 | — |
| 11 | C1 performance grid | 4 | A3 |
| 12 | C2 macros | 2 | F0, B2 |
| 13 | C3 MIDI | 2 | C1, C2 |
| 14 | D1 auto-VJ | 3 | C1 |
| 15 | D2 análisis en vivo | 4 (timebox) | D1 |

**Total ≈ 44 días** de trabajo efectivo. **Carril de quick-wins**: B1 (waveform) y A5.1
(drag&drop del banco) no dependen de nada salvo F0 — si hay dos personas, una puede
entregarlos en paralelo a A1 para que el usuario vea valor la primera semana.

Hitos de demo (enseñables al usuario):
tras A1 ("las luces respiran con la música"), tras A3 ("compongo con bloques"),
tras B3 ("el show va sobre raíles"), tras C1 ("toco las luces como un instrumento"),
tras D1 ("impro sin preparar nada").

## Asignación de modelos por fase (optimización de coste, 2026-06-12)

Precios API por M tokens: **Opus 4.8** $5/$25 · **Sonnet 4.6** $3/$15 · **Haiku 4.5** $1/$5.
El criterio NO es "líneas de código" sino **riesgo × ambigüedad**: contratos que otros
copiarán, concurrencia y semántica sutil → modelo grande; recetas cerradas con criterio de
aceptación claro → modelo pequeño. Este ROADMAP ya hace el trabajo caro (la spec); el
modelo barato solo tiene que seguirla.

| Fase | Modelo | Por qué |
|------|--------|---------|
| F0 cimientos | **Opus 4.8** | Define los contratos que TODO el equipo copia; parity byte-exacto; equivocarse aquí cuesta 14 fases |
| A1 modulación | Sonnet 4.6 | Bien especificada tras rev. v2.1; core puro + handler + UI según receta |
| A2 automatización | Sonnet 4.6 | Backend mecánico; el SVG interactivo es laborioso pero está pautado |
| A3 patterns | **Opus 4.8** | Semántica sutil: expansión/cache/invalidación, undo, clips efímeros no editables |
| A4 piano-roll lite | Sonnet 4.6 | 80% frontend sobre la base de A2 |
| A5 ergonomía | **Haiku 4.5** (ítems 1-4, 6, 7) / Sonnet (5 y 8) | Mini-recetas cerradas con aceptación manual; el zoom centrado (5) y duplicate_range (8) tienen matemática/edge cases |
| B1 waveform | **Haiku 4.5** | Receta cerrada: bucketing + canvas + cache |
| B2 mixer | Sonnet 4.6 | Numpy vectorizado + parity + orden del pipeline |
| B3 render offline | **Opus 4.8** | Concurrencia (executor, copia congelada, invalidación) — donde los bugs son carísimos |
| B4 autosave | **Haiku 4.5** | Rotación de archivos + banner; trivial y bien acotada |
| C1 performance grid | **Opus 4.8** | Timing en vivo, cuantización, mezcla de capa live — el corazón del DIRECTO |
| C2 macros | Sonnet 4.6 | Stage simple, pero toca el pipeline compartido |
| C3 MIDI | Sonnet 4.6 | Web MIDI tiene quirks de permisos/dispositivos; módulo autocontenido |
| D1 auto-VJ | Sonnet 4.6 | Motor de reglas pautado; reusa la capa live de C1 |
| D2 análisis en vivo | **Opus 4.8** | Exploratoria: tiempo real, threading, criterio de timebox |

Reparto resultante: Opus 5 fases (~17 días), Sonnet 7 (~19 días), Haiku 3+ (~8 días).
Frente a "todo con Opus", el ahorro estimado en tokens es del ~45-55%.

### Reglas de uso (importantes)

1. **Cómo elegir modelo en Claude Code**: `claude --model opus|sonnet|haiku` al arrancar,
   o `/model` dentro de la sesión. Una fase = una sesión con SU modelo.
2. **Patrón "barato implementa, caro revisa"**: toda fase hecha con Haiku termina con una
   sesión corta de Sonnet/Opus haciendo code review del diff (`git diff main` + checklist
   de cierre) ANTES del commit. Coste mínimo, atrapa lo que el pequeño no ve.
3. **Regla de escalado — no insistir**: si el modelo falla el mismo test 2 veces seguidas
   o da vueltas sin avanzar ~30 min, SUBE de modelo y reintenta. Iterar en bucle con un
   modelo barato sale más caro (tokens + tiempo) que empezar con uno mejor.
4. **Nunca bajar de modelo para**: tocar el pipeline de F0, migraciones de schema,
   o cualquier cosa del camino del frame con test de parity.
5. Truco de coste extra: las sesiones de fases pequeñas no necesitan releer todo el
   ROADMAP — basta "lee §Reglas del juego, §Invariantes y TU fase".

## Checklist de cierre de CADA fase (copiar en el PR)

```
[ ] Suite pytest verde (sin saltarse tests)
[ ] Tests nuevos del módulo escritos y pasando
[ ] Test de parity si la fase toca el camino del frame
[ ] npx tsc --noEmit limpio + cd web && npm run build (si toca web)
[ ] show.json viejo carga sin pérdida (si toca persistencia)
[ ] Sin imports prohibidos (core no importa server/web/fastapi)
[ ] Handlers nuevos documentados en docs/dev/handlers.md
[ ] ROADMAP.md: fase marcada APLICADA con fecha y notas
[ ] CLAUDE.md actualizado si cambia arquitectura o comandos
[ ] Un commit con mensaje "roadmap-v2 fase <ID>: <resumen>"
[ ] Probado A MANO el criterio de aceptación (no solo los tests)
```
