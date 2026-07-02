"""
handlers/clips_edit.py — edición de clips (efecto/preset/duplicar/partir) + A5 rangos + A4 micro-eventos (ADR-005).
"""
from __future__ import annotations

from server.validators import ValidationError, require_int, require_key


def _h_set_clip_effect(session, params):
    """Cambia el efecto (effect_id) de un clip pixel. No existe en el bridge."""
    try:
        clip_id = require_key(params, "clip_id")
        effect_id = require_int(params, "effect_id", min_val=0)
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    c = session.find_clip_by_id(clip_id)
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    # Validar params opcionales contra el schema del efecto destino
    extra_params = params.get("params")
    if extra_params:
        lib = getattr(session, "library", None)
        effect = lib.get_effect(effect_id) if lib else None
        schema = getattr(effect, "PARAM_SCHEMA", {}) if effect else {}
        try:
            from server.validators import validate_params_against_schema
            validate_params_against_schema(extra_params, schema)
        except ValidationError as e:
            return {"ok": False, "error": str(e)}
        c.params = dict(extra_params)
    c.effect_id = effect_id
    if params.get("label") is not None:
        c.label = params["label"]
    session.invalidate_caches()
    return {"ok": True}


def _h_set_clip_preset(session, params):
    """Aplica un preset (pixel o canal) a un clip EXISTENTE, conservando su
    posición (start/end/track/layer). Espeja la asignación de _h_add_preset_clip.
    Permite 'pintar' presets con click en modo draw."""
    try:
        clip_id = require_key(params, "clip_id")
        preset_id = require_key(params, "preset_id")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    c = session.find_clip_by_id(clip_id)
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    p = session.presets.get(preset_id)
    if p is None:
        return {"ok": False, "error": "preset no encontrado"}
    # Validar params del preset contra el schema del efecto destino
    if p.params and p.kind != "channel":
        lib = getattr(session, "library", None)
        effect = lib.get_effect(p.base_effect_id) if lib else None
        schema = getattr(effect, "PARAM_SCHEMA", {}) if effect else {}
        try:
            from server.validators import validate_params_against_schema
            validate_params_against_schema(p.params, schema)
        except ValidationError as e:
            return {"ok": False, "error": f"preset params inválidos: {e}"}
    c.params = dict(p.params)
    c.color = p.color
    c.label = p.name
    c.preset_id = p.preset_id
    if getattr(p, "param_links", None):
        c.param_links = list(p.param_links)
    if p.kind == "channel":
        c.category = p.category
        c.channel_effect_id = p.channel_effect_id
    else:
        c.effect_id = p.base_effect_id
        c.category = "pixel"
        c.channel_effect_id = None
    session.invalidate_caches()
    return {"ok": True, "clip": c.to_dict()}


def _h_duplicate_clip(session, params):
    """Duplica un clip (mismo efecto/params), desplazado o en otra capa/track."""
    from core.timeline_model import Clip
    c = session.find_clip_by_id(params["clip_id"])
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    dur = c.end_ms - c.start_ms
    start = int(params.get("start_ms", c.start_ms + dur))
    nc = Clip(
        track=int(params.get("track", c.track)),
        start_ms=start, end_ms=start + dur,
        effect_id=c.effect_id, scope=c.scope, color=c.color,
        layer=int(params.get("layer", c.layer)), label=c.label,
        muted=c.muted, params=dict(c.params or {}),
        category=getattr(c, "category", "pixel"),
        channel_effect_id=getattr(c, "channel_effect_id", None),
    )
    session.timeline.add(nc)
    session.invalidate_caches()
    return {"ok": True, "clip": nc.to_dict()}


def _h_split_clip(session, params):
    """Parte un clip en dos en t_ms (cursor)."""
    from core.timeline_model import Clip
    c = session.find_clip_by_id(params["clip_id"])
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    t_ms = int(params["t_ms"])
    if not (c.start_ms < t_ms < c.end_ms):
        return {"ok": False, "error": "el cursor no está dentro del clip"}
    orig_end = c.end_ms
    c.end_ms = t_ms
    nc = Clip(
        track=c.track, start_ms=t_ms, end_ms=orig_end,
        effect_id=c.effect_id, scope=c.scope, color=c.color,
        layer=c.layer, label=c.label, muted=c.muted, params=dict(c.params or {}),
        category=getattr(c, "category", "pixel"),
        channel_effect_id=getattr(c, "channel_effect_id", None),
    )
    session.timeline.add(nc)
    session.invalidate_caches()
    return {"ok": True}


# ── A5 — Ergonomía: duplicar sección ────────────────────────────────────────

def _h_duplicate_range(session, params):
    """Copia todos los clips cuyo start_ms ∈ [t0_ms, t1_ms) al offset dest_ms.

    El desplazamiento aplicado es `dest_ms - t0_ms`. Los clips con start_ms en
    [t0_ms, t1_ms) se duplican con nuevos UIDs; los originales no se tocan.
    Llama snapshot() antes de mutar (invariante I1).
    """
    from src.core.timeline_model import Clip
    t0_ms = require_int(params, "t0_ms")
    t1_ms = require_int(params, "t1_ms")
    dest_ms = require_int(params, "dest_ms")
    if t0_ms >= t1_ms:
        return {"ok": False, "error": "t0_ms debe ser menor que t1_ms"}

    session.snapshot()
    offset = dest_ms - t0_ms
    new_clips = []
    for c in list(session.timeline.clips):
        if t0_ms <= c.start_ms < t1_ms:
            nc = Clip(
                track=c.track,
                start_ms=c.start_ms + offset,
                end_ms=c.end_ms + offset,
                effect_id=c.effect_id,
                scope=c.scope,
                color=c.color,
                layer=c.layer,
                label=c.label,
                muted=c.muted,
                params=dict(c.params or {}),
                category=getattr(c, "category", "pixel"),
                channel_effect_id=getattr(c, "channel_effect_id", None),
                param_links=list(getattr(c, "param_links", []) or []),
            )
            new_clips.append(nc)
    for nc in new_clips:
        session.timeline.add(nc)
    session.invalidate_caches()
    return {"ok": True, "clips": [c.to_dict() for c in new_clips]}


def _h_delete_range(session, params):
    """delete_range(start_ms: int, end_ms: int) → {ok, deleted: int}.

    Borra todos los clips que se solapan con el intervalo [start_ms, end_ms).
    Un clip se solapa si su rango (start_ms, end_ms) intersecta el intervalo
    especificado — condición: clip.start_ms < end_ms AND clip.end_ms > start_ms.
    Llama snapshot() antes de mutar (invariante I1). Usado por la vista Arranger (I4).
    """
    start_ms = require_int(params, "start_ms")
    end_ms = require_int(params, "end_ms")
    if start_ms >= end_ms:
        return {"ok": False, "error": "start_ms debe ser menor que end_ms"}
    session.snapshot()
    before = len(session.timeline.clips)
    session.timeline.clips = [
        c for c in session.timeline.clips
        if not (c.start_ms < end_ms and c.end_ms > start_ms)
    ]
    deleted = before - len(session.timeline.clips)
    session.invalidate_caches()
    return {"ok": True, "deleted": deleted}


# ── A4 — Micro-eventos ──────────────────────────────────────────────────────

def _h_add_micro_event(session, params):
    """Añade un micro-evento al clip. Devuelve el clip actualizado (I3)."""
    from src.core.micro_events import MicroEvent
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    t_ms_rel = int(params.get("t_ms_rel", 0))
    duration_ms = int(params.get("duration_ms", 100))
    if duration_ms < 1:
        return {"ok": False, "error": "duration_ms debe ser >= 1"}
    ev = MicroEvent(
        t_ms_rel=max(0, t_ms_rel),
        duration_ms=duration_ms,
        params_override=dict(params.get("params_override") or {}),
    )
    session.snapshot()
    clip.events = list(clip.events) + [ev.to_dict()]
    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


def _h_delete_micro_event(session, params):
    """Elimina un micro-evento del clip por event_uid."""
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    event_uid = require_key(params, "event_uid")
    before = len(clip.events)
    session.snapshot()
    clip.events = [e for e in clip.events if e.get("uid") != event_uid]
    if len(clip.events) == before:
        return {"ok": False, "error": "event_uid no encontrado"}
    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


def _h_update_micro_event(session, params):
    """Actualiza campos de un micro-evento (t_ms_rel, duration_ms, params_override)."""
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    event_uid = require_key(params, "event_uid")
    ev_list = list(clip.events)
    idx = next((i for i, e in enumerate(ev_list) if e.get("uid") == event_uid), None)
    if idx is None:
        return {"ok": False, "error": "event_uid no encontrado"}
    ev = dict(ev_list[idx])
    if "t_ms_rel" in params:
        ev["t_ms_rel"] = max(0, int(params["t_ms_rel"]))
    if "duration_ms" in params:
        dur = int(params["duration_ms"])
        if dur < 1:
            return {"ok": False, "error": "duration_ms debe ser >= 1"}
        ev["duration_ms"] = dur
    if "params_override" in params:
        ev["params_override"] = dict(params["params_override"])
    session.snapshot()
    ev_list[idx] = ev
    clip.events = ev_list
    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


HANDLERS = {
    "set_clip_effect": _h_set_clip_effect,
    "set_clip_preset": _h_set_clip_preset,
    "duplicate_clip": _h_duplicate_clip,
    "split_clip": _h_split_clip,
    "duplicate_range": _h_duplicate_range,
    "delete_range": _h_delete_range,
    "add_micro_event": _h_add_micro_event,
    "delete_micro_event": _h_delete_micro_event,
    "update_micro_event": _h_update_micro_event,
}
# La declaración de mutador vive junto al handler (ADR-005):
TIMELINE_MUTATORS = {
    "set_clip_effect", "set_clip_preset", "duplicate_clip", "split_clip", "delete_range",
}
