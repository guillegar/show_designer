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
