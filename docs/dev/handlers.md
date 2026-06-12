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
