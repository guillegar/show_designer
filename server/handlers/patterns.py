"""
handlers/patterns.py — A3 patterns reutilizables + instancias (snapshot propio por handler) (ADR-005).
"""
from __future__ import annotations

from server.validators import ValidationError, require_int, require_key


def _h_create_pattern_from_clips(session, params):
    """Agrupa clips seleccionados en un Pattern reutilizable.

    Borra los clips originales del timeline y crea una PatternInstance
    en su lugar con los tiempos/tracks relativos. Los handlers de undo
    incluyen patterns en el snapshot (invariante I1) antes de mutar.
    """
    try:
        clip_ids = require_key(params, "clip_ids")
        if not isinstance(clip_ids, list) or not clip_ids:
            return {"ok": False, "error": "clip_ids debe ser lista no vacía"}
        name = str(params.get("name", "Pattern"))
        color = str(params.get("color", "#8855cc"))
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    clips = [session.find_clip_by_id(cid) for cid in clip_ids]
    clips = [c for c in clips if c is not None]
    if not clips:
        return {"ok": False, "error": "Ningún clip_id encontrado"}

    from uuid import uuid4

    from src.core.timeline_model import Pattern, PatternInstance

    session.snapshot()

    start_ref = min(c.start_ms for c in clips)
    track_ref = min(c.track for c in clips)

    # Clips con tiempos/tracks relativos al origen del pattern
    relative_clips = []
    for c in clips:
        import copy
        rc = copy.copy(c)
        rc.start_ms = c.start_ms - start_ref
        rc.end_ms = c.end_ms - start_ref
        rc.track = c.track - track_ref
        relative_clips.append(rc)

    pat = Pattern(uid=uuid4().hex[:12], name=name, color=color, clips=relative_clips)
    session.timeline.patterns.append(pat.to_dict())

    # Borrar clips originales del timeline
    uid_set = {c.uid for c in clips}
    session.timeline.clips = [
        c for c in session.timeline.clips if c.uid not in uid_set
    ]

    inst = PatternInstance(
        uid=uuid4().hex[:12],
        pattern_uid=pat.uid,
        start_ms=start_ref,
        track_offset=track_ref,
    )
    session.timeline.pattern_instances.append(inst.to_dict())
    session.invalidate_pattern_cache()
    return {"ok": True, "pattern": pat.to_dict(), "instance": inst.to_dict()}


def _h_add_pattern_instance(session, params):
    """Añade una nueva instancia de un pattern en el timeline."""
    try:
        pattern_uid = require_key(params, "pattern_uid")
        start_ms = require_int(params, "start_ms", min_val=0)
        track_offset = int(params.get("track_offset", 0))
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    pat_d = next(
        (p for p in session.timeline.patterns if p.get("uid") == pattern_uid), None
    )
    if pat_d is None:
        return {"ok": False, "error": "pattern_uid no encontrado"}

    from uuid import uuid4

    from src.core.timeline_model import PatternInstance

    session.snapshot()

    inst = PatternInstance(
        uid=uuid4().hex[:12],
        pattern_uid=pattern_uid,
        start_ms=start_ms,
        track_offset=track_offset,
    )
    session.timeline.pattern_instances.append(inst.to_dict())
    session.invalidate_pattern_cache()
    return {"ok": True, "instance": inst.to_dict()}


def _h_move_pattern_instance(session, params):
    """Mueve (reposiciona) una PatternInstance. Retorna la instancia actualizada (I3)."""
    try:
        instance_uid = require_key(params, "instance_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    inst_d = next(
        (i for i in session.timeline.pattern_instances if i.get("uid") == instance_uid),
        None,
    )
    if inst_d is None:
        return {"ok": False, "error": "instance_uid no encontrado"}

    session.snapshot()

    if params.get("new_start_ms") is not None:
        inst_d["start_ms"] = max(0, int(params["new_start_ms"]))
    if params.get("new_track_offset") is not None:
        inst_d["track_offset"] = int(params["new_track_offset"])

    session.invalidate_pattern_cache()
    return {"ok": True, "instance": dict(inst_d)}


def _h_delete_pattern_instance(session, params):
    """Elimina una PatternInstance del timeline."""
    try:
        instance_uid = require_key(params, "instance_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    instances = [
        i for i in session.timeline.pattern_instances if i.get("uid") != instance_uid
    ]
    if len(instances) == len(session.timeline.pattern_instances):
        return {"ok": False, "error": "instance_uid no encontrado"}

    session.snapshot()
    session.timeline.pattern_instances = instances
    session.invalidate_pattern_cache()
    return {"ok": True}


def _h_update_pattern(session, params):
    """Actualiza nombre, color y/o clips de un Pattern.

    Pasar 'clips' (lista de clip dicts relativos) edita los clips del pattern,
    lo que propagará a todas sus instancias en el próximo frame (enlace vivo).
    """
    try:
        pattern_uid = require_key(params, "pattern_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    pat_d = next(
        (p for p in session.timeline.patterns if p.get("uid") == pattern_uid), None
    )
    if pat_d is None:
        return {"ok": False, "error": "pattern_uid no encontrado"}

    session.snapshot()

    if params.get("name") is not None:
        pat_d["name"] = str(params["name"])
    if params.get("color") is not None:
        pat_d["color"] = str(params["color"])
    if params.get("clips") is not None:
        from src.core.timeline_model import Pattern
        try:
            p = Pattern.from_dict({**pat_d, "clips": params["clips"]})
            pat_d["clips"] = [c.to_dict() for c in p.clips]
        except Exception as e:
            return {"ok": False, "error": f"clips inválidos: {e}"}

    session.invalidate_pattern_cache()
    return {"ok": True, "pattern": dict(pat_d)}


def _h_delete_pattern(session, params):
    """Elimina un Pattern y todas sus instancias (cascada I2)."""
    try:
        pattern_uid = require_key(params, "pattern_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    if not any(p.get("uid") == pattern_uid for p in session.timeline.patterns):
        return {"ok": False, "error": "pattern_uid no encontrado"}

    session.snapshot()

    session.timeline.patterns = [
        p for p in session.timeline.patterns if p.get("uid") != pattern_uid
    ]
    instances_before = len(session.timeline.pattern_instances)
    session.timeline.pattern_instances = [
        i for i in session.timeline.pattern_instances
        if i.get("pattern_uid") != pattern_uid
    ]
    deleted_instances = instances_before - len(session.timeline.pattern_instances)
    # I2: limpiar live_slots que referencien el pattern borrado
    changed = False
    for slot in session.live_engine.slots:
        if slot.pattern_uid == pattern_uid:
            slot.pattern_uid = None
            session.live_engine._active.pop(slot.uid, None)
            session.live_engine._armed.pop(slot.uid, None)
            changed = True
    if changed:
        session.timeline.live_slots = session.live_engine.slots_to_dicts()
    session.invalidate_pattern_cache()
    return {"ok": True, "deleted_instances": deleted_instances}


def _h_list_patterns(session, params):
    """Lista todos los patterns del banco."""
    return {"ok": True, "patterns": list(session.timeline.patterns)}


def _h_list_pattern_instances(session, params):
    """Lista todas las instancias de patterns en el timeline."""
    return {"ok": True, "instances": list(session.timeline.pattern_instances)}


def _h_dissolve_instance(session, params):
    """Convierte una PatternInstance en clips reales en el timeline.

    Los clips se crean con posiciones absolutas y se pueden editar
    individualmente a partir de ese momento.
    """
    try:
        instance_uid = require_key(params, "instance_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    inst_d = next(
        (i for i in session.timeline.pattern_instances if i.get("uid") == instance_uid),
        None,
    )
    if inst_d is None:
        return {"ok": False, "error": "instance_uid no encontrado"}

    from uuid import uuid4

    from src.core.timeline_model import Clip, Pattern, PatternInstance

    session.snapshot()

    inst = PatternInstance.from_dict(inst_d)
    pat_d = next(
        (p for p in session.timeline.patterns if p.get("uid") == inst.pattern_uid),
        None,
    )
    if pat_d is None:
        return {"ok": False, "error": "pattern del que depende la instancia no encontrado"}

    pat = Pattern.from_dict(pat_d)
    new_clips = []
    for clip in pat.clips:
        nc = Clip(
            track=max(0, min(9, clip.track + inst.track_offset)),
            start_ms=inst.start_ms + clip.start_ms,
            end_ms=inst.start_ms + clip.end_ms,
            effect_id=clip.effect_id,
            scope=clip.scope,
            params=dict(clip.params),
            color=clip.color,
            label=clip.label,
            layer=clip.layer,
            locked=clip.locked,
            muted=clip.muted,
            category=clip.category,
            channel_effect_id=clip.channel_effect_id,
            preset_id=clip.preset_id,
            uid=uuid4().hex[:12],  # uid NUEVO (clip real, editable)
            param_links=list(clip.param_links),
        )
        new_clips.append(nc)

    session.timeline.clips.extend(new_clips)
    session.timeline.pattern_instances = [
        i for i in session.timeline.pattern_instances if i.get("uid") != instance_uid
    ]
    session.invalidate_pattern_cache()
    session.invalidate_clip_index()
    return {"ok": True, "clips": [c.to_dict() for c in new_clips]}


HANDLERS = {
    "create_pattern_from_clips": _h_create_pattern_from_clips,
    "add_pattern_instance": _h_add_pattern_instance,
    "move_pattern_instance": _h_move_pattern_instance,
    "delete_pattern_instance": _h_delete_pattern_instance,
    "update_pattern": _h_update_pattern,
    "delete_pattern": _h_delete_pattern,
    "list_patterns": _h_list_patterns,
    "list_pattern_instances": _h_list_pattern_instances,
    "dissolve_instance": _h_dissolve_instance,
}
