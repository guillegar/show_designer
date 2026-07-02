"""
handlers/presets.py — banco de presets de efectos (v1.10) (ADR-005).
"""
from __future__ import annotations

from server.validators import ValidationError, require_int, require_order


# ── Banco de presets (v1.10) ────────────────────────────────────────────────
def _h_list_presets(session, params):
    all_presets = session.presets.list()
    effect_id = params.get("effect_id")
    if effect_id is not None:
        try:
            eid = int(effect_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "effect_id debe ser entero"}
        all_presets = [p for p in all_presets if p.kind == "pixel" and p.base_effect_id == eid]
    return {"presets": [p.to_dict() for p in all_presets]}


def _h_create_preset(session, params):
    p = session.presets.create(
        name=params.get("name", "Preset"),
        params=params.get("params", {}),
        color=params.get("color", "#3a7acc"),
        scope=params.get("scope", "project"),
        kind=params.get("kind", "pixel"),
        base_effect_id=int(params.get("base_effect_id", 0)),
        channel_effect_id=params.get("channel_effect_id"),
    )
    session.notify_changed("presets")
    return {"ok": True, "preset": p.to_dict()}


def _h_update_preset(session, params):
    p = session.presets.update(
        params["preset_id"], name=params.get("name"), params=params.get("params"),
        color=params.get("color"), base_effect_id=params.get("base_effect_id"))
    if p is None:
        return {"ok": False, "error": "preset no encontrado"}
    # Enlace vivo: refrescar el snapshot (effect_id/params/color/label) de los
    # clips ligados, para que el fallback Qt y las etiquetas sigan al preset.
    n = 0
    for c in session.timeline.clips:
        if getattr(c, "preset_id", None) == p.preset_id:
            if p.kind == "channel":
                c.channel_effect_id = p.channel_effect_id
                c.category = p.category
            else:
                c.effect_id = p.base_effect_id
            c.params = dict(p.params)
            c.color = p.color
            c.label = p.name
            n += 1
    session.invalidate_caches()   # invalida cache de render → recompute
    session.notify_changed("presets")
    return {"ok": True, "preset": p.to_dict(), "clips_updated": n}


def _h_delete_preset(session, params):
    ok = session.presets.delete(params["preset_id"])
    session.notify_changed("presets")
    return {"ok": ok}


def _h_add_preset_clip(session, params):
    from core.timeline_model import Clip

    try:
        preset_id = params["preset_id"]
        start = require_int(params, "start_ms")
        end = require_int(params, "end_ms")
        require_order(start, end, "start_ms", "end_ms")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    p = session.presets.get(preset_id)
    if p is None:
        return {"ok": False, "error": "preset no encontrado"}

    if p.kind == "channel":
        fixture_id = params.get("fixture_id")
        if not fixture_id:
            return {"ok": False, "error": "falta fixture_id para un preset de canal"}
        clip = Clip(
            track=-1, start_ms=start, end_ms=end, effect_id=0,
            scope=f"fixture:{fixture_id}", params=dict(p.params),
            label=p.name, color=p.color, layer=int(params.get("layer", 0)),
            category=p.category, channel_effect_id=p.channel_effect_id,
            preset_id=p.preset_id,
        )
    else:
        clip = Clip(
            track=int(params.get("track", 0)), start_ms=start, end_ms=end,
            effect_id=p.base_effect_id, scope=params.get("scope", "per_bar"),
            params=dict(p.params), label=p.name, color=p.color,
            layer=int(params.get("layer", 0)), preset_id=p.preset_id,
        )
    session.timeline.add(clip)
    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


HANDLERS = {
    "list_presets": _h_list_presets,
    "create_preset": _h_create_preset,
    "update_preset": _h_update_preset,
    "delete_preset": _h_delete_preset,
    "add_preset_clip": _h_add_preset_clip,
}
TIMELINE_MUTATORS = {"add_preset_clip"}
