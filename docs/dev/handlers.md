# Cómo añadir un handler JSON-RPC (receta, F0.3)

Los handlers son el ÚNICO camino por el que la web (y Claude vía MCP) mutan el modelo.
Esta receta es la que se copia — no inventes variantes.

## Dónde vive cada cosa

- `src/mcp/mcp_bridge.py` — handlers "clásicos" (63). NO cambian de firma jamás
  (contrato público: los usa Claude). Solo se AÑADE.
- `server/dispatcher.py` — handlers web-only (`_h_<nombre>` + registro en `LOCAL_HANDLERS`).
  Aquí van los nuevos del ROADMAP v2.
- `server/validators.py` — validación de params (`require_int`, `require_key`,
  `require_order`, `ValidationError`). Úsala SIEMPRE; un handler no hace `int(params[...])`
  a pelo.

## Receta (handler web-only nuevo)

1. Escribe la función en `dispatcher.py`:

```python
def _h_set_clip_param_links(session, params):
    """set_clip_param_links(clip_id, links) — ejemplo de la fase A1."""
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    # ... validar y mutar ...
    session.invalidate_caches()        # invalida índice + notifica al stream
    return {"ok": True, "clip": clip.to_dict()}   # ← invariante I3: devuelve la entidad
```

2. Regístrala en el dict de handlers locales del dispatcher.
3. Reglas:
   - **I3**: devuelve SIEMPRE la entidad mutada (la UI parchea el store de forma
     optimista; el refetch es solo reconciliación).
   - Si muta clips → `session.invalidate_caches()`. Si muta el rig → está en
     `_RIG_MUTATORS` (regenera `rig_layout.json`).
   - Si la mutación debe poder deshacerse → el FRONTEND llama a `snapshot` tras
     el commit del gesto (no el handler: un drag son N llamadas y un solo snapshot).
   - Errores: `{"ok": False, "error": "mensaje claro"}` — nunca excepciones sin capturar.
4. Test en `tests/test_dispatcher.py` (o archivo de tu fase): caso feliz + params
   inválidos + entidad inexistente.
5. Frontend: añade el tipo en `web/src/api/types.ts` y llama con
   `control.call("set_clip_param_links", {...})`. El evento `model_changed` del stream
   dispara la reconciliación.

## Nomenclatura

`<verbo>_<sustantivo>`: `set_`, `add_`, `delete_`, `list_`, `move_`. Listas devuelven
`{"ok": True, "<plural>": [...]}`.

---

## Catálogo de handlers A1–A3 (dispatcher.py)

### A1 — Modulación

| Handler | Params | Devuelve |
|---------|--------|----------|
| `set_clip_param_links` | `clip_id`, `links: [{param, source, gain, offset, curve, min_v, max_v}]` | `{ok, clip}` |
| `list_modulation_sources` | — | `{ok, sources: [{key, label, description}]}` |

### A2 — Automatización

| Handler | Params | Devuelve |
|---------|--------|----------|
| `add_automation_lane` | `target` (ej. `"clip:<uid>:brightness"`), `uid?` | `{ok, lane}` |
| `delete_automation_lane` | `uid` | `{ok}` |
| `set_automation_points` | `uid`, `points: [{t_ms, value, shape}]` | `{ok, lane}` |
| `list_automation_lanes` | — | `{ok, lanes: [...]}` |

Targets: `"clip:<uid>:<param>"` | `"track:<n>:<param>"` | `"master:<param>"`.

### A3 — Patterns

Los handlers de patterns llaman `session.snapshot()` internamente (NO están en
`_TIMELINE_MUTATORS`; si lo estuvieran, se haría un doble snapshot).

| Handler | Params | Devuelve |
|---------|--------|----------|
| `create_pattern_from_clips` | `clip_ids: [str]`, `name?: str`, `color?: str` | `{ok, pattern, instance}` |
| `add_pattern_instance` | `pattern_uid: str`, `start_ms: int`, `track_offset?: int` | `{ok, instance}` |
| `move_pattern_instance` | `instance_uid: str`, `new_start_ms?: int`, `new_track_offset?: int` | `{ok, instance}` |
| `delete_pattern_instance` | `instance_uid: str` | `{ok}` |
| `update_pattern` | `pattern_uid: str`, `name?: str`, `color?: str`, `clips?: [clip_dict]` | `{ok, pattern}` |
| `delete_pattern` | `pattern_uid: str` | `{ok, deleted_instances: int}` |
| `list_patterns` | — | `{ok, patterns: [...]}` |
| `list_pattern_instances` | — | `{ok, instances: [...]}` |
| `dissolve_instance` | `instance_uid: str` | `{ok, clips: [...]}` |

**`create_pattern_from_clips`**: calcula tiempos/tracks relativos (start_ref = mín start_ms,
track_ref = mín track), crea el Pattern con clips relativos, borra los clips originales de
`timeline.clips`, y crea la PatternInstance en start_ref/track_ref.

**`dissolve_instance`**: convierte la instancia en clips reales (UIDs nuevos, posiciones
absolutas) en `timeline.clips` y la elimina de `timeline.pattern_instances`.

**`delete_pattern`**: borra el pattern Y todas sus instancias (invariante I2 cascada).

**Clips efímeros** (expansión en render): tienen `uid = f"{inst.uid}::{clip.uid}"`. NO
aparecen en `list_clips`. La expansión se cachea con `_pattern_rev`; se invalida al mutar
patterns o instancias mediante `session.invalidate_pattern_cache()`.

### A4 — Micro-eventos

Los handlers de micro-eventos llaman `session.snapshot()` internamente (misma razón que A3).
Devuelven el clip completo (invariante I3) para que el frontend actualice el store optimistamente.

| Handler | Params | Devuelve |
|---------|--------|----------|
| `add_micro_event` | `clip_id: str`, `t_ms_rel: int`, `duration_ms?: int (def 100)`, `params_override?: dict` | `{ok, clip}` |
| `delete_micro_event` | `clip_id: str`, `event_uid: str` | `{ok, clip}` |
| `update_micro_event` | `clip_id: str`, `event_uid: str`, `t_ms_rel?: int`, `duration_ms?: int`, `params_override?: dict` | `{ok, clip}` |

**Micro-evento**: override puntual de `params_override` activo durante `duration_ms` ms
(default 100ms ≈ 3 frames @30FPS) a partir de `t_ms_rel` desde `clip.start_ms`.
`MicroEventStage` es el 3er stage del pipeline (orden: modulación→automatización→micro-eventos).
Fast path: si `clip.events == []`, devuelve `params` sin copiar (cero allocs).
Los `events` van en `clip.to_dict()`, por lo que el undo por snapshot (I1) los cubre automáticamente.

### A5 — Ergonomía de composición

| Handler | Params | Devuelve |
|---------|--------|----------|
| `duplicate_range` | `t0_ms: int`, `t1_ms: int`, `dest_ms: int` | `{ok, clips: [...]}` |

**`duplicate_range`**: copia todos los clips con `start_ms ∈ [t0_ms, t1_ms)` al offset `dest_ms`.
El desplazamiento aplicado es `dest_ms - t0_ms`; los clips originales no se tocan; los duplicados
reciben UIDs nuevos. Llama `snapshot()` antes de mutar (I1). Los clips nuevos se añaden a
`timeline.clips`; devuelve la lista de nuevos clips (I3).

---

### B1 — Waveform en el timeline

| Handler | Params | Devuelve |
|---------|--------|----------|
| `get_waveform` | — | `{ok, peaks_max, peaks_min, rms, n_buckets, duration_sec, bpm}` |

Devuelve la forma de onda del audio del show en `n_buckets=8000` cubos (min/max/rms por cubo).
La primera llamada tarda ~2-5 s (librosa carga el audio); las siguientes son instantáneas
porque el resultado se cachea en `<analysis_dir>/waveform.json` (escritura atómica).

Devuelve `{ok: False, error}` si librosa no está disponible o el audio no se encuentra.

### B2 — Mixer: cadena por pista + master

El mixer vive en `timeline.mixer` (contenedor v3, persistido en show.json, incluido en undo).
El postfx se aplica al final de `compute_frame`, ANTES del envío (orden fijo del pipeline:
`timeline_render → [capa live C1] → apply_track_chain × pista → apply_master`).

**Throttle obligatorio en el cliente**: los sliders disparan eventos onChange continuamente.
Implementar en la UI con un ref de timestamp: si `Date.now() - lastSent < 50 ms`, no enviar.
Sólo enviar en mouseUp si el usuario fue más rápido que el throttle.

| Handler | Params | Devuelve |
|---------|--------|----------|
| `set_track_chain` | `track: int (0..9)`, `chain: {brightness?:0..1, gamma?:0.5..2.2, hue_shift?:-180..180, white_limit?:0..1}` | `{ok, track, chain}` |
| `set_master` | `master: {brightness?:0..1, gamma?:0.5..2.2, hue_shift?:-180..180, white_limit?:0..1, blackout_fade?:0..1}` | `{ok, master}` |
| `get_mixer` | — | `{ok, mixer: {tracks: {}, master: {}}}` |

**`blackout_fade`**: animable con una lane de A2 (target `'master:blackout_fade'`) para
fades de salida de show profesionales — sale gratis porque la cadena de automatización
ya evalúa este target en `AutomationStage`.

**Cadena aplicada** (en `src/core/postfx.py`, puro numpy):
1. `apply_track_chain(frame[track], chain)` — por cada pista con chain configurada
2. `apply_master(frame, master)` — al frame completo (NUM_BARS×LEDS×3)

Fast path: si todos los parámetros son identidad (brightness=1, gamma=1, hue_shift=0,
white_limit=1, blackout_fade=1), se devuelve la referencia original sin copiar (cero allocs, I4).

### B3 — Render offline + playback baked

| Handler | Params | Devuelve |
|---------|--------|----------|
| `render_offline` | — | `{ok, message}` inmediato |
| `get_render_status` | — | `{ok, status, pct, hash, n_frames?, duration_s?}` |
| `toggle_baked` | `enabled: bool` | `{ok, baked: bool}` |

**`render_offline`**: lanza el render del timeline completo en background (executor thread pool,
I4 — no bloquea el tick). El progreso se emite como `{type:'render_progress', pct:float}` en el
stream. Devuelve inmediatamente; solo un render simultáneo (devuelve error si ya hay uno en curso).

**`get_render_status`**: comprueba si hay un render en curso o un `render.npz` válido en disco.
`status`: `'rendering'` | `'ready'` (hash MD5 del timeline coincide con el npz) | `'idle'`.

**`toggle_baked`**: cuando `enabled=True`, carga los frames bakeados desde `render.npz` en memoria
(`session.baked_frames`). Si no hay render válido (hash no coincide), devuelve error. Cuando
`enabled=False`, descarga los frames y vuelve al modo live.

El modo baked aplica igualmente los postfx/master (B2) sobre el frame bakeado, por lo que
los sliders del mixer siguen funcionando sin relanzar el render.

### B4 — Autosave + versiones de show

| Handler | Params | Devuelve |
|---------|--------|----------|
| `list_autosaves` | — | `{ok, autosaves: [{filename, ts, size_kb}]}` desc por fecha |
| `restore_autosave` | `filename: str` (solo nombre, sin rutas) | `{ok, filename}` |
| `discard_autosave_prompt` | — | `{ok}` — solo cierra el banner en el frontend |

Autosave automático: cada `LUCES_AUTOSAVE_INTERVAL` s (default 60), guardado atómico en
`projects/<slug>/autosave/show_<ts>.json`. Máximo 20 archivos rotatorios.

Al arrancar, si hay un autosave más reciente que `show.json`, el frontend muestra un banner
(evento `{type:'autosave_available'}`). El usuario elige cargar o descartar.

**`restore_autosave`**: valida que `filename` sea un nombre simple (sin separadores de
directorio, `show_*.json`) para prevenir path traversal. Carga el autosave como timeline
activo preservando `duration_ms` del show actual.

### C1 — Performance grid: lanzar patterns en vivo

| Handler | Params | Devuelve |
|---------|--------|----------|
| `live_assign_slot` | `slot_idx: int (0..15)`, `pattern_uid?: str`, `key?: str`, `quantize?: str`, `mode?: str` | `{ok, slot}` |
| `live_trigger` | `slot_idx: int (0..15)` | `{ok, slot, armed_at_ms}` |
| `live_release` | `slot_idx: int (0..15)` | `{ok, slot}` |
| `live_stop_all` | — | `{ok}` |
| `get_live_state` | — | `{ok, slots, active, armed}` |

Grid de 16 slots (4×4). Cada slot asocia un pattern a una tecla del teclado, modo de
lanzamiento y cuantización.

**`quantize`**: `'bar'` (espera siguiente compás — requiere downbeats), `'beat'` (espera
siguiente beat), `'free'` (activa inmediatamente). Si se pide `'bar'` sin downbeats disponibles,
degrada automáticamente a `'free'` (`armed_at_ms` = t actual).

**`mode`**: `'toggle'` (lanzar/parar en el mismo botón), `'hold'` (solo activo mientras se
mantiene pulsado), `'oneshot'` (termina al final del pattern).

Emite `{type:'live_state_changed'}` al stream tras cualquier cambio de estado.
El estado de los slots se persiste en `show.json` (`live_slots`). Cubre I1 (undo por snapshot).

**Slot 15 reservado**: D1 AutoVJ usa el slot 15 para `fire_pattern`. No asignar manualmente.

### I1 — Grabación en vivo de macros

| Handler | Params | Devuelve |
|---------|--------|----------|
| `start_record` | — | `{ok, recording: true}` |
| `stop_record` | — | `{ok, recording: false, lanes_created: int, lane_uids: [str]}` |
| `get_record_state` | — | `{ok, recording: bool, elapsed_ms: float, points_captured: int}` |

**`start_record`**: activa la grabación. Limpia el buffer de puntos anterior y registra
`_record_start_ms = session._current_t_ms`. Durante la grabación, `compute_frame` captura
el valor actual de cada macro si difiere del default, con throttle de 50ms.

**`stop_record`**: para la grabación y convierte los puntos capturados en `AutomationLane`s
en `session.timeline.automation` con target `"master:<macro_name>"` y `shape="linear"`.
Los t_ms de los puntos son relativos al inicio de la grabación. Llama `snapshot()` antes de
crear las lanes (undo cubre la operación — I1). Idempotente: sin grabación activa devuelve
`lanes_created: 0`.

**`get_record_state`**: estado actual de la grabación (polling, útil si no se quiere depender
del evento de stream). `elapsed_ms` es el tiempo de la grabación en curso.

**Stream event** `record_state`: `{type, recording: bool, elapsed_ms, points}` — emitido
cada ~500ms mientras `_recording=True`. El frontend actualiza el contador de puntos capturados.

**Normalización de valores** (para AutomationLane, rango 0..1):
- `brightness_mul` (0..2): `value / 2.0`
- `speed_mul` (0..4): `value / 4.0`
- `hue_shift` (-180..180): `(value + 180) / 360.0`
- `strobe_rate` (0..30): `value / 30.0`

**Undo (I1)**: `automation` ahora forma parte del `get_extra`/`restore_extra` del
`UndoManager`. Llamar a `undo()` tras `stop_record` elimina las lanes creadas.

---

### I2 — Marcadores de timeline con nombre, color y categoría

| Handler | Params | Devuelve |
|---------|--------|----------|
| `list_markers` | `category?: str` | `{ok, markers: [Marker]}` |
| `add_marker` | `time_ms: int`, `name?: str`, `color?: str`, `category?: str` | `{ok, marker: Marker}` |
| `delete_marker` | `time_ms: int` | `{ok, deleted: int}` |
| `update_marker` | `t_ms: int`, `name?: str`, `color?: str`, `category?: str` | `{ok, marker: Marker}` |

**`Marker`** — objeto serializado:
```json
{ "t_ms": 1000, "time_ms": 1000, "name": "Intro", "color": "#ff0000", "category": "intro" }
```
`time_ms` es un alias de `t_ms` para compatibilidad con el frontend.

**Categorías válidas**: `intro` | `verso` | `estribillo` | `bridge` | `outro` | `custom`.
Cualquier valor desconocido se normaliza a `"custom"`.

**`list_markers`**: si se pasa `category`, devuelve solo los marcadores de esa categoría.
Sin `category` (o `category=null`), devuelve todos ordenados por `t_ms`.

**`add_marker`**: si ya existe un marcador en `time_ms`, lo reemplaza. Devuelve el marcador
creado (invariante I3).

**`update_marker`**: identifica el marcador por `t_ms` y actualiza solo los campos enviados.
El dispatcher llama `snapshot()` antes (undo — invariante I1).

**Persistencia**: `session.timeline.markers` se serializa en `show.json`. Migración tolerante:
shows sin el campo `markers` cargan con lista vacía.

**Undo (I1)**: `markers` forma parte de `get_extra`/`restore_extra` del `UndoManager`.
Llamar a `undo()` tras `add_marker` o `update_marker` restaura el estado anterior.

---

### C2 — Macros en vivo

| Handler | Params | Devuelve |
|---------|--------|----------|
| `set_macro` | `name: str`, `value: float` | `{ok, macros: dict}` |

Las macros son controles globales en tiempo real (estado de sesión, **no persisten** en show.json).
Throttle recomendado en el cliente: ≤ 20 llamadas/s.

| Macro | Rango | Efecto |
|-------|-------|--------|
| `brightness_mul` | 0.0 .. 2.0 | Multiplica el brillo global del frame |
| `speed_mul` | 0.0 .. 4.0 | Factor de velocidad de efectos (MacroStage) |
| `hue_shift` | -180.0 .. 180.0 | Rotación de tono global (sumado al master antes de apply_master) |
| `strobe_rate` | 0.0 .. 30.0 | Hz de estroboscópico global (aplicado al final de compute_frame) |

Las macros son el 4º stage del param_pipeline (`MacroStage`). Fast path: sin coste si
`brightness_mul==1.0` y `speed_mul==1.0`. El strobe se aplica SIEMPRE al final de
`compute_frame` (tanto en modo live como en modo baked), por lo que funciona sobre el render offline.

C3 (MIDI) es 100 % frontend: no añade handlers de backend. El mapeo MIDI se guarda en
`localStorage` bajo la clave `show_designer_midi_map` (independiente del show.json).

### D1 — Auto-VJ por reglas

El motor AutoVJ vive en `session.autovj_engine: AutoVJEngine` (estado live, no en show.json).
Se evalúa en `compute_frame` ANTES de `live_engine.compute_live_frame`. Los patterns efímeros
de `fire_effect` se pasan junto con `timeline.patterns` a `compute_live_frame` (capa C1
sin duplicar infraestructura).

Persistencia: `projects/<slug>/autovj.json` (guardado atómico, no parte de show.json).
Se carga automáticamente al arrancar la sesión si el archivo existe. Los presets integrados
(FIESTA/CHILL/TECHNO) viven en código (`src/core/autovj.py`) y no se persisten en disco.

| Handler | Params | Devuelve |
|---------|--------|----------|
| `autovj_get_state` | — | `{ok, ruleset\|null, presets:[{uid,name,rules}]}` |
| `autovj_set_ruleset` | `ruleset: dict\|null` | `{ok, ruleset\|null}` (null = desactivar) |
| `autovj_activate_preset` | `preset_uid: str` ("preset_fiesta"\|"preset_chill"\|"preset_techno") | `{ok, ruleset}` |
| `autovj_update_rule` | `rule_uid: str`, `enabled?: bool`, `cooldown_ms?: int`, `trigger?: str`, `action?: str` | `{ok, rule}` |
| `autovj_save` | — | `{ok, path, saved: bool}` |
| `autovj_load` | — | `{ok, ruleset\|null}` |

**Triggers disponibles:**
- `"on_beat"` — ±20ms de cualquier beat del análisis
- `"on_downbeat"` — ±20ms de cualquier downbeat
- `"on_kick"` — `actx['norm'].get('kick', norm.get('onset_strength', 0)) > 0.6` (proxy)
- `"on_section_change"` — transición entre secciones (no dispara en el primer frame)
- `"signal_above:<src>:<thr>"` — flanco ascendente sobre umbral, histéresis thr_off=thr×0.8

**Actions disponibles:**
- `"fire_effect:<effect_id>:<scope>:<duration_ms>"` — crea pattern efímero + slot en live._active
- `"fire_pattern:<pattern_uid>"` — activa slot con ese pattern (usa slot 15 si no hay ninguno asignado)

**Slot reservado**: el slot 15 de LiveEngine es el destino por defecto de `fire_pattern` cuando
ningún slot del grid tiene el pattern_uid. No lo asignes manualmente en la UI del performance grid.

### D2 — Análisis en vivo

`session.live_input: LiveInput | None` + `session._live_mode: bool`.
Cuando `_live_mode=True`, `_get_audio_context` usa las features del ring buffer en vez del
análisis offline, y D1 AutoVJ recibe `live_input` como fuente de beats/downbeats.

`section_at` devuelve siempre `None` en modo live (sin análisis estructural). Los triggers
`on_section_change` no disparan. Los más fiables en live son `signal_above:rms` y `on_kick`
(proxy de onset transiente).

| Handler | Params | Devuelve |
|---------|--------|----------|
| `live_input_list_devices` | — | `{ok, devices:[{index, name, channels, default_sr}]}` |
| `live_input_start` | `device_index?: int` (default = dispositivo del SO) | `{ok, device_index, bpm}` |
| `live_input_stop` | — | `{ok}` |
| `live_input_get_state` | — | `{ok, active, live_mode, bpm?, duration_s}` |

**Flujo típico**: `live_input_start` → activa captura + `_live_mode=True` → D1 reacciona a la música
en tiempo real → `live_input_stop` → vuelve al análisis offline (si existe).

**Pipeline interno** (hilo de audio, 23ms por bloque):
- RMS + flux espectral (rfft)
- Onset: `RMS > 1.5 × EMA_RMS` y cooldown ≥ 150ms
- BPM: mediana de IOI + EMA α=0.8 → beats sintéticos con fase del último onset
- Historial: `deque(maxlen≈30s)` — sin crecimiento indefinido

---

## E2 — OSC bridge

UDP IN (puerto 8001) + emitter OUT (puerto 8002). `server/osc_bridge.py` — instanciado en
`web.py`, referenciado desde `session.osc_bridge`. Config en `output_targets.json["osc"]`.
Se degrada limpiamente si python-osc no está instalado (`available: false` en get_state).

| Handler | Params | Devuelve |
|---------|--------|----------|
| `osc_get_state` | — | `{ok, enabled, available, active, port_in, port_out, clients_out, recv_log}` |
| `osc_set_config` | `port_in?, port_out?, enabled?, clients_out:[{ip,port}]` | `{ok, ...estado}` — guarda en output_targets.json; reinicia servidor IN si cambió puerto/enabled |

**OSC IN** (mensajes que el servidor escucha):
- `/show/go_cue <número\|uid>` — go_cue() por número decimal o uid; sin args = go_next_cue
- `/show/goto_t <ms>` — seek del audio al instante t_ms
- `/macro/brightness <0..1>` — brightness_mul = v×2
- `/macro/strobe <hz>` — strobe_rate (0..30 Hz)
- `/live/trigger <idx>` — live_engine.trigger(idx)
- `/live/stop_all` — live_engine.stop_all()

**OSC OUT** (throttled ≤ 10 Hz, solo si hay clients_out):
`/show/t_ms` · `/show/section` · `/show/beat` · `/show/rms`

---

## E1 — Sistema de Cues profesional

Lista de cues accionable (`CueList` en `Timeline.cue_list`, schema v4). Runtime en `session.py`
(`_cue_fade_*`, `_cue_auto_follow_task`). Fade aplicado al frame en `compute_frame` (ambas rutas).
Auto-follow: `asyncio.create_task` + `asyncio.sleep` (I4).

| Handler | Params | Devuelve |
|---------|--------|----------|
| `add_cue` | `name: str, t_ms: int, fade_in_ms: int = 0, hold_ms: int = -1, auto_follow: bool = False, number?: float` | `{ok, uid, number, name, t_ms, fade_in_ms, hold_ms, auto_follow}` |
| `delete_cue` | `uid: str` | `{ok}` |
| `update_cue` | `uid: str, **fields` (name, t_ms, fade_in_ms, hold_ms, auto_follow, number) | `{ok, entry}` |
| `reorder_cues` | — | `{ok, entries}` (lista ordenada por number) |
| `list_cues` | — | `{ok, entries: [...], active_uid}` |
| `go_cue` | `uid: str` | `{ok, active_uid, t_ms}` — seek + fade + auto_follow |
| `go_next_cue` | — | `{ok, active_uid}` o `{ok, active_uid: null}` si no hay siguiente |
| `go_prev_cue` | — | `{ok, active_uid}` o `{ok, active_uid: null}` si no hay anterior |
| `get_cue_state` | — | `{ok, active_uid, next_uid, fade_pct}` — O(1) |

**Stream event** `cue_changed`: `{type, active_uid, fade_pct, next_uid}` — throttled al >1 % de
cambio de fade (evita flood). Solo emitido mientras hay fade activo (`_cue_fade_start_ms is not None`).

**Undo (I1)**: `cue_list` entra en `get_extra`/`restore_extra` del UndoManager desde el día 1.
**CueEntry vs CuePoint**: son entidades separadas. Borrar una `CueEntry` NO afecta los `CuePoint`
pasivos del timeline (marcadores de sección/estructurales).

---

## F2 — Plugin UI auto-generada

| Handler | Params | Devuelve |
|---------|--------|----------|
| `get_effect_schema` | `effect_id: int` | `{ok, schema: dict}` — PARAM_SCHEMA del efecto |

**`get_effect_schema`**: devuelve el `PARAM_SCHEMA` de la clase del efecto indicado.
Schema vacío `{}` si el efecto no tiene schema (efectos legacy). Usado por `ClipInspector.tsx`
al abrir el inspector, cacheado por `effect_id` en el componente (no en el store).

**Integración de validación**: `set_clip_effect` y `set_clip_preset` llaman internamente a
`validate_params_against_schema(params, schema)` (en `server/validators.py`). Si los params
están fuera de rango o contienen enums inválidos, devuelven `{ok: false, error}` sin mutar.

Véase también `docs/dev/plugin-sdk.md` para la convención de PARAM_SCHEMA y los tipos de
control que genera la UI.

---

## F3 — Biblioteca de presets curados

### Cambios en handlers existentes

**`list_presets`** — acepta ahora un parámetro opcional `effect_id: int`:
- Sin `effect_id`: devuelve todos los presets (comportamiento anterior, sin breaking change).
- Con `effect_id`: devuelve solo los presets pixel con `base_effect_id == effect_id`.

```json
// Petición filtrada
{"method": "list_presets", "params": {"effect_id": 1014}}
// Respuesta
{"presets": [{"preset_id": "...", "name": "Hoguera", "base_effect_id": 1014, ...}, ...]}
```

**`set_clip_preset`** — ahora también propaga `param_links` del preset al clip:
- Si `EffectPreset.param_links` es no vacío, se copia a `Clip.param_links`.
- Permite presets con modulación A1 preconfigurada (ej. "Pulso Ámbar": `rate_hz ← rms`).

### Nuevo campo en `EffectPreset`

`param_links: List[dict]` — lista de enlaces A1 preconfigurados. Mismo formato que
`Clip.param_links` (ver `set_clip_param_links`). Por defecto vacío `[]` (backwards-compat:
los presets existentes sin este campo se cargan sin error).

### Banco global — 30 presets nuevos

3 presets curados por cada efecto F1 (IDs 1010-1019), añadidos automáticamente al arrancar
si no estaban en `presets.json`. Nombres evocadores (no técnicos). Los presets de
`vu_meter` y `breathing` (audio_reactive) están pre-conectados a la señal RMS.

---

## F4 — Live preview en el inspector

| Handler | Params | Devuelve |
|---------|--------|----------|
| `preview_effect_frame` | `effect_id: int, params?: dict, t_ms?: float` | `{ok, frame_b64?: str, width?: int, height?: int}` o `{ok, frame_raw?: list}` |

**`preview_effect_frame`**: renderiza un frame del efecto (sin estado de sesión, sin tocar el
timeline). Crea un `bars_state` sintético de ceros, llama a `effect.render(t_ms, ...)` y
devuelve el resultado como PNG base64 (scale 2× con Pillow).

- Sin `params`: usa los defaults del efecto.
- `t_ms` (ms desde inicio de clip, default 0): permite previsualizar distintos momentos.
- Fallback `LUCES_NO_PILLOW=1`: devuelve `frame_raw` (lista Python, sin dependencia de Pillow).
- Efecto no encontrado → `{ok: false, error}`. Tiempo < 50 ms (síncrono, sin executor).
- Registrado en `_LOCAL` (no disponible vía MCP bridge).

---

## G1 — sACN (E1.31) como protocolo adicional

No hay handlers nuevos — G1 es puramente en el OutputRouter. Para configurar sACN añadir una
entrada en `output_targets.json`:

```json
{
  "1": {"type": "sacn", "ip": "192.168.1.50"},
  "2": {"type": "sacn", "ip": "239.255.0.1", "multicast": true}
}
```

Campos:
- `type`: `"sacn"`
- `ip`: destino (IP unicast o grupo multicast)
- `port`: default 5568
- `multicast`: `false` (unicast) o `true` (multicast E1.31 group)

`SacnNodeTarget` (en `src/io/outputs/router.py`): instancia un `sacn.sACNsender` único,
activa universos de forma lazy (`activate_output(universe)` solo la primera vez que se envía),
y hace `sender.stop()` en `close()`. Compatible con `OutputRouter.close()` al shutdown del server.

Requisito PyPI: `sacn>=1.6` (ya en `requirements.txt`).

---

## G2 — Ableton Link / MIDI Clock sync de tempo

| Handler | Params | Devuelve |
|---------|--------|----------|
| `tempo_sync_get_state` | — | `{mode, bpm, beat_phase, midi_device, synced}` |
| `tempo_sync_set_mode` | `mode: str, device?: str` | `{ok, state}` |
| `tempo_sync_list_midi_ports` | — | `{ok, ports: [str]}` |

**`tempo_sync_set_mode`**: cambia el modo de sincronización de tempo. `mode` ∈ `"off"` / `"link"` / `"midi_clock"`. Para `"midi_clock"`, `device` es el nombre del puerto MIDI (si se omite, usa el primero disponible).

- El servicio corre en hilo de fondo; las librerías (`pylinkbpm`, `mido`) son imports opcionales con fallback limpio si no están instaladas.
- Cuando `bpm > 0`, `session._get_audio_context()` sobreescribe el BPM del análisis con el BPM del sync. Esto hace que D1 (Auto-VJ) cuantice en el beat correcto del DJ.
- Stream: los mensajes `{type:"state"}` incluyen el campo `tempo_sync` con el estado actual.
- `TempoSyncService` vive en `server/tempo_sync.py`; `_calc_bpm(pulse_times_s)` es una función pura testeable.

---

## G4 — Salida DMX USB directa (ENTTEC Open DMX)

| Handler | Params | Devuelve |
|---------|--------|----------|
| `list_dmx_ports` | — | `{ok, ports: [str]}` — puertos COM/ttyUSB disponibles |
| `set_output_target` | `universe, type, port?, ip?, multicast?` | `{ok, universe, target}` |

**`list_dmx_ports`**: envuelve `serial.tools.list_ports.comports()`. Devuelve `[]` si `pyserial` no instalado.

**`set_output_target`**: actualiza `output_targets.json` (escritura atómica tmp→replace) para el universo indicado y recarga el `OutputRouter` en la sesión sin reiniciar el servidor. Soporta cualquier `type`: `wled`, `artnet_node`, `sacn`, `dmx_usb`, `sim_only`.

Framing ENTTEC Open DMX USB (en `DmxUsbTarget.send()`):
1. `serial.send_break(0.001)` — BREAK ≥88µs
2. `serial.write(b'\x00' + bytes(dmx_512))` — START CODE 0x00 + 512 bytes a 250 kbaud 8N2

`DmxUsbTarget` (en `src/io/outputs/router.py`): import lazy de `serial`, error de puerto → log + `_ser=None` + send no-op. `list_ports()` classmethod. Requisito: `pyserial>=3.5` (en `requirements.txt`).

---

## G3 — Moving heads: pan/tilt en el timeline

`PanTiltWaveEffect` en `src/core/channel_effects.py`. Un clip puede tener `channel_effects:
List[ChannelEffectConfig]` (lista de sub-efectos); `_render_clip_channels` los renderiza con
política de mezcla `LAST_WINS` (el clip de layer más alto manda). Documentada en ADR-004.

| Handler | Params | Devuelve |
|---------|--------|----------|
| `list_channel_effects` | — | `{ok, effects: [{effect_id, name, PARAM_SCHEMA}]}` |
| `set_clip_channel_effect` | `clip_id: str`, `channel_effect: {type, params...}` | `{ok, clip}` |
| `delete_clip_channel_effect` | `clip_id: str`, `channel_name: str` | `{ok, clip}` |
| `get_fixture_pan_tilt` | `fixture_id: str` | `{ok, pan, tilt}` — posición actual en [0,1] |

**`PanTiltWaveEffect` modos**: `circle` (eje elíptico), `fig8` (lemniscata), `bounce_pan`
(oscilación solo en pan), `bounce_tilt` (oscilación solo en tilt). Parámetros: `pan_center`,
`tilt_center`, `pan_range`, `tilt_range`, `speed` (Hz), `mode`.

**Persistencia**: `channel_effects` se serializa en `Clip.to_dict/from_dict` → cubierto por
undo/snapshot (I1). Política LTP: si dos clips activos en instantes distintos tocan el mismo
canal del mismo fixture, el de layer más alto gana (LAST_WINS, ADR-004).

**Frontend**: tab "Movimiento" en `ClipInspector` con SVG preview 2D de la trayectoria del
spot (círculo/figura 8) y sliders de speed/range generados desde `PARAM_SCHEMA` (F2).

---

## H1 — SDK de plugins público

Sin handlers nuevos. H1 es documentación + harness de testing.

- **`docs/dev/plugin-sdk.md`**: guía completa para crear un efecto custom — subclasear `Effect`,
  definir `PARAM_SCHEMA` (convenciones F2), shape correcta, ID en rango 1000+, colocar en
  `plugins/effects/` (detección automática al arrancar).
- **`tests/plugin_test_harness.py`**: `assert_valid_plugin_effect(effect, params)` — verifica
  shape, dtype, rango [0,255], inmutabilidad de `bars_state`, coherencia de `PARAM_SCHEMA`.
  Los tests de F1 lo usan; los 4 plugins existentes también lo pasan.
- **`plugins/effects/plugin_template.py`**: plantilla comentada con todos los campos obligatorios.

**Uso del harness desde un test externo**:
```python
from tests.plugin_test_harness import assert_valid_plugin_effect
from plugins.effects.my_effect import MyEffect
assert_valid_plugin_effect(MyEffect(), params={"speed": 1.0})
```

---

## H2 — Instalador Windows

Sin handlers nuevos. H2 es infraestructura de build.

- **`showdesigner.spec`**: spec de PyInstaller (`--onedir`), empaqueta `web/dist`, `plugins`,
  `gdtf_profiles`.
- **`scripts/build_installer.ps1`**: 1) `npm run build` → `web/dist/`; 2) `pyinstaller
  showdesigner.spec`; 3) `iscc ShowDesigner.iss` (opcional — requiere Inno Setup 6).
- **`ShowDesigner.iss`**: script Inno Setup para generar `ShowDesigner_setup.exe`.
- **`Luces.bat`** actualizado: detecta `ShowDesigner.exe` (modo `sys.frozen`) vs `venv311`
  (modo desarrollo) y usa el comando correcto.

**Limitaciones documentadas**: `sounddevice` requiere VC++ Redistributable. FFmpeg (E3)
no se incluye — debe estar en PATH. `llvmlite` de librosa añade ~100 MB al dist.

---

## H3 — Multi-show quick-switch

| Handler | Params | Devuelve |
|---------|--------|----------|
| `list_projects` | — | `{ok, projects: [{slug, name, duration_s}], current: str}` |
| `switch_project` | `slug: str` | `{ok}` inmediato — el cambio ocurre en background |

**`switch_project`**: lanza `ShowSession.switch_project(slug)` como tarea async. Secuencia:
1. Para el autosave en curso; 2. `autosave_now()` del proyecto actual; 3. Carga nueva timeline/
audio/analysis; 4. Resetea estado runtime (`baked_frames=None`, `live_stop_all()`, cues, live
engine); 5. Emite `{type:"project_changed", slug, name}` al stream.

**Stream event** `project_changed`: los clientes React hacen `refreshAll()` al recibirlo
(clips, patterns, cues, mixer, live state). El `RenderPanel` se resetea (el baked del
proyecto anterior es inválido para el nuevo). Spinner "Cargando proyecto X…" en el topbar
mientras el evento no llega.

**Frontend**: `ProjectSwitcher` dropdown en el topbar (solo visible si hay >1 proyecto
en `projects/`). El dropdown llama a `switch_project(slug)` y activa el spinner.

**Switch a slug inexistente**: devuelve `{ok: False, error}` sin dejar la sesión en estado
parcial (la sesión no se toca si el slug no existe).

---

## H4 — Rendimiento a escala

Sin handlers nuevos. H4 añade paginación a `list_clips` y benchmarks.

**Paginación de `list_clips`** (registrado en `_LOCAL` con prioridad sobre el bridge):

| Handler | Params | Devuelve |
|---------|--------|----------|
| `list_clips` | `offset?: int (def 0)`, `limit?: int (def 0 = todos)` | `{ok, clips: [...], total: int, count: int, next_offset: int\|null}` |

- `offset`/`limit` = 0: devuelve todos los clips (comportamiento anterior — sin breaking change).
- `limit > 0`: devuelve hasta `limit` clips desde `offset`, con `next_offset` para la página siguiente.
- El orden es estable (índice de inserción en `timeline.clips`).

**Protocolo diff (`model_changed_v2`)**: H4 prepara la infraestructura para que el stream
emita `{type:'model_changed_v2', changed:[clip_dict], deleted:[uid]}` en lugar de triggering
un refetch completo. Los clientes legacy (`model_changed` sin diff) siguen funcionando.

**Benchmarks** (`tests/test_bench_scale.py`, marcados `@pytest.mark.bench`):
- `to_dict` 5000 clips < 200 ms
- `from_dict` 5000 clips < 200 ms
- `list_clips` handler 5000 clips < 500 ms
- `compute_frame` p95 < 60 ms con 200 clips activos
- Sin leaks > 1 MB tras 100 frames (`tracemalloc`)
