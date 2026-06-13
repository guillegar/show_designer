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
