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
