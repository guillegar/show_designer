"""
handlers/clips_bulk.py — Timeline v2 Fase B: mutaciones de clips en lote (ADR-005).

Un handler bulk = una llamada al dispatcher = UN snapshot de undo (I1) y un solo
bump de rev, en vez de N round-trips secuenciales desde el frontend (mover un
grupo de 40 clips eran 40 RPC + 40 snapshots). `move_range` sustituye al combo
no-atómico duplicate_range + delete_range del Arranger.
"""
from __future__ import annotations

from server.validators import ValidationError, require_int, require_key


def _h_bulk_move_clips(session, params):
    """bulk_move_clips(moves: [{clip_id, new_start_ms?, new_end_ms?, new_track?,
    new_layer?}]) → {ok, moved, skipped_locked}.

    Valida TODOS los clip_ids antes de mutar (atómico: o se aplican todos los
    válidos o error limpio). Los clips bloqueados se saltan y se reportan.
    Misma semántica por-clip que move_clip (duración preservada si solo llega
    new_start_ms; end clamp a start+50; layer >= 0).
    """
    moves = params.get("moves")
    if not isinstance(moves, list) or not moves:
        return {"ok": False, "error": "moves debe ser una lista no vacía"}

    resolved = []
    for m in moves:
        clip_id = m.get("clip_id")
        if clip_id is None:
            return {"ok": False, "error": "cada move necesita clip_id"}
        c = session.find_clip_by_id(clip_id)
        if c is None:
            return {"ok": False, "error": f"clip_id no encontrado: {clip_id}"}
        resolved.append((c, m))

    moved, skipped_locked = 0, []
    for c, m in resolved:
        if c.locked:
            skipped_locked.append(c.uid)
            continue
        dur = c.end_ms - c.start_ms
        if "new_start_ms" in m and m["new_start_ms"] is not None:
            c.start_ms = max(0, int(m["new_start_ms"]))
            c.end_ms = c.start_ms + dur
        if "new_end_ms" in m and m["new_end_ms"] is not None:
            c.end_ms = max(c.start_ms + 50, int(m["new_end_ms"]))
        if "new_track" in m and m["new_track"] is not None:
            c.track = int(m["new_track"])
        if "new_layer" in m and m["new_layer"] is not None:
            c.layer = max(0, int(m["new_layer"]))
        moved += 1
    session.invalidate_caches()
    return {"ok": True, "moved": moved, "skipped_locked": skipped_locked}


def _h_bulk_delete_clips(session, params):
    """bulk_delete_clips(clip_ids: [str]) → {ok, deleted, skipped_locked}.

    Los ids inexistentes se ignoran (idempotente); los bloqueados se saltan.
    """
    clip_ids = params.get("clip_ids")
    if not isinstance(clip_ids, list) or not clip_ids:
        return {"ok": False, "error": "clip_ids debe ser una lista no vacía"}
    wanted = {str(i) for i in clip_ids}
    skipped_locked = [c.uid for c in session.timeline.clips
                      if c.uid in wanted and c.locked]
    locked = set(skipped_locked)
    before = len(session.timeline.clips)
    session.timeline.clips = [
        c for c in session.timeline.clips
        if c.uid not in wanted or c.uid in locked
    ]
    deleted = before - len(session.timeline.clips)
    session.invalidate_caches()
    return {"ok": True, "deleted": deleted, "skipped_locked": skipped_locked}


def _h_bulk_add_clips(session, params):
    """bulk_add_clips(clips: [{track, start_ms, end_ms, effect_id, scope?,
    color?, label?, layer?, params?}]) → {ok, clips} (con uids nuevos).

    Valida todos los items antes de crear nada (atómico). Usado por el paste
    múltiple del timeline.
    """
    from src.core.timeline_model import Clip

    items = params.get("clips")
    if not isinstance(items, list) or not items:
        return {"ok": False, "error": "clips debe ser una lista no vacía"}

    specs = []
    for i, d in enumerate(items):
        try:
            track = require_int(d, "track")
            start_ms = require_int(d, "start_ms", min_val=0)
            end_ms = require_int(d, "end_ms")
            effect_id = require_int(d, "effect_id", min_val=0)
        except ValidationError as e:
            return {"ok": False, "error": f"clips[{i}]: {e}"}
        if end_ms <= start_ms:
            return {"ok": False, "error": f"clips[{i}]: end_ms debe ser > start_ms"}
        specs.append((track, start_ms, end_ms, effect_id, d))

    created = []
    for track, start_ms, end_ms, effect_id, d in specs:
        nc = Clip(
            track=track, start_ms=start_ms, end_ms=end_ms,
            effect_id=effect_id,
            scope=str(d.get("scope", "per_bar")),
            color=str(d.get("color", "#3a7acc")),
            layer=max(0, int(d.get("layer", 0))),
            label=str(d.get("label", "")),
            params=dict(d.get("params") or {}),
        )
        session.timeline.add(nc)
        created.append(nc)
    session.invalidate_caches()
    return {"ok": True, "clips": [c.to_dict() for c in created]}


def _h_move_range(session, params):
    """move_range(t0_ms, t1_ms, dest_ms) → {ok, moved, deleted}.

    Versión ATÓMICA del combo duplicate_range + delete_range del Arranger
    (que podía dejar clips duplicados si la segunda llamada fallaba).
    Semántica idéntica al combo: se copian los clips con start_ms ∈ [t0, t1)
    desplazados dest−t0, y se eliminan los que SOLAPAN [t0, t1).
    """
    from src.core.timeline_model import Clip

    t0_ms = require_int(params, "t0_ms")
    t1_ms = require_int(params, "t1_ms")
    dest_ms = require_int(params, "dest_ms", min_val=0)
    if t0_ms >= t1_ms:
        return {"ok": False, "error": "t0_ms debe ser menor que t1_ms"}

    offset = dest_ms - t0_ms
    copies = []
    for c in session.timeline.clips:
        if t0_ms <= c.start_ms < t1_ms:
            copies.append(Clip(
                track=c.track,
                start_ms=c.start_ms + offset,
                end_ms=c.end_ms + offset,
                effect_id=c.effect_id, scope=c.scope, color=c.color,
                layer=c.layer, label=c.label, muted=c.muted,
                params=dict(c.params or {}),
                category=getattr(c, "category", "pixel"),
                channel_effect_id=getattr(c, "channel_effect_id", None),
                param_links=list(getattr(c, "param_links", []) or []),
            ))
    before = len(session.timeline.clips)
    session.timeline.clips = [
        c for c in session.timeline.clips
        if not (c.start_ms < t1_ms and c.end_ms > t0_ms)
    ]
    deleted = before - len(session.timeline.clips)
    for nc in copies:
        session.timeline.add(nc)
    session.invalidate_caches()
    return {"ok": True, "moved": len(copies), "deleted": deleted}


HANDLERS = {
    "bulk_move_clips": _h_bulk_move_clips,
    "bulk_delete_clips": _h_bulk_delete_clips,
    "bulk_add_clips": _h_bulk_add_clips,
    "move_range": _h_move_range,
}
# La declaración de mutador vive junto al handler (ADR-005). El dispatcher hace
# UN snapshot antes de cada llamada → el bulk entero es un solo paso de undo.
TIMELINE_MUTATORS = {
    "bulk_move_clips", "bulk_delete_clips", "bulk_add_clips", "move_range",
}
