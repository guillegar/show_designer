"""
handlers/cues.py — E1 sistema de cues profesional (add/update/reorder/go/fade) (ADR-005).
"""
from __future__ import annotations

from server.validators import ValidationError, require_int

# ── E1 — Sistema de Cues profesional (ROADMAP v3) ────────────────────────────

def _h_add_cue(session, params):
    """add_cue(t_ms, name?, number?, fade_in_ms?, hold_ms?) → {ok, cue}

    Añade una CueEntry a la CueList. El number se auto-asigna si no se indica.
    La lista queda ordenada por number tras la inserción.
    """
    from uuid import uuid4

    from src.core.timeline_model import CueEntry
    try:
        t_ms = require_int(params, "t_ms", min_val=0)
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    entries = session.timeline.cue_list.entries
    number = float(params.get("number", len(entries) + 1))
    hold_ms = int(params.get("hold_ms", -1))
    auto_follow = bool(params.get("auto_follow", hold_ms >= 0))
    entry = CueEntry(
        uid=uuid4().hex[:12],
        number=number,
        name=str(params.get("name", f"Cue {number:g}")),
        t_ms=t_ms,
        fade_in_ms=int(params.get("fade_in_ms", 0)),
        hold_ms=hold_ms,
        auto_follow=auto_follow,
    )
    session.snapshot()
    entries.append(entry)
    entries.sort(key=lambda e: e.number)
    session.notify_changed("cues")
    return {"ok": True, "cue": entry.to_dict()}


def _h_delete_cue(session, params):
    """delete_cue(uid) → {ok}

    Borra una CueEntry. NO borra el CuePoint homónimo (son entidades separadas).
    """
    uid = params.get("uid")
    if not uid:
        return {"ok": False, "error": "uid requerido"}
    entries = session.timeline.cue_list.entries
    before = len(entries)
    session.snapshot()
    session.timeline.cue_list.entries = [e for e in entries if e.uid != uid]
    if len(session.timeline.cue_list.entries) == before:
        return {"ok": False, "error": "cue no encontrado"}
    if session.timeline.cue_list.active_uid == uid:
        session.timeline.cue_list.active_uid = None
    session.notify_changed("cues")
    return {"ok": True}


def _h_update_cue(session, params):
    """update_cue(uid, name?, t_ms?, number?, fade_in_ms?, hold_ms?) → {ok, cue}

    Actualiza campos de una CueEntry existente (los campos no indicados no cambian).
    """
    uid = params.get("uid")
    if not uid:
        return {"ok": False, "error": "uid requerido"}
    entry = next((e for e in session.timeline.cue_list.entries if e.uid == uid), None)
    if entry is None:
        return {"ok": False, "error": "cue no encontrado"}
    session.snapshot()
    if "name" in params:
        entry.name = str(params["name"])
    if "t_ms" in params:
        entry.t_ms = int(params["t_ms"])
    if "number" in params:
        entry.number = float(params["number"])
    if "fade_in_ms" in params:
        entry.fade_in_ms = int(params["fade_in_ms"])
    if "hold_ms" in params:
        entry.hold_ms = int(params["hold_ms"])
    if "auto_follow" in params:
        entry.auto_follow = bool(params["auto_follow"])
    session.notify_changed("cues")
    return {"ok": True, "cue": entry.to_dict()}


def _h_reorder_cues(session, params):
    """reorder_cues() → {ok, cues}

    Reordena la CueList por el campo number (llamar tras editar numbers).
    """
    session.timeline.cue_list.entries.sort(key=lambda e: e.number)
    session.notify_changed("cues")
    return {"ok": True, "cues": [e.to_dict() for e in session.timeline.cue_list.entries]}


def _h_list_cues(session, params):
    """list_cues() → {ok, cues: [...], active_uid: str|None}"""
    cue_list = session.timeline.cue_list
    return {
        "ok": True,
        "cues": [e.to_dict() for e in cue_list.entries],
        "active_uid": cue_list.active_uid,
    }


def _h_go_cue(session, params):
    """go_cue(uid) → {ok, cue}

    Salta al cue: seek al t_ms, inicia fade si fade_in_ms > 0, programa
    auto-follow si cue.auto_follow=True. Emite cue_changed al stream.
    """
    uid = params.get("uid")
    if not uid:
        return {"ok": False, "error": "uid requerido"}
    cue = session.go_cue(uid)
    if cue is None:
        return {"ok": False, "error": "cue no encontrado"}
    return {"ok": True, "cue": cue.to_dict()}


def _h_go_next_cue(session, params):
    """go_next_cue() → {ok, cue: CueEntry|None}

    Avanza al siguiente cue por número. Si ya es el último: {ok, cue: None}.
    """
    cue = session.go_next_cue()
    return {"ok": True, "cue": cue.to_dict() if cue else None}


def _h_go_prev_cue(session, params):
    """go_prev_cue() → {ok, cue: CueEntry|None}

    Retrocede al cue anterior por número. Si ya es el primero: {ok, cue: None}.
    """
    cue = session.go_prev_cue()
    return {"ok": True, "cue": cue.to_dict() if cue else None}


def _h_get_cue_state(session, params):
    """get_cue_state() → {ok, active_uid, fade_pct: 0..1, next_uid} (O(1))"""
    return {"ok": True, **session.get_cue_state()}

HANDLERS = {
    "add_cue": _h_add_cue,
    "delete_cue": _h_delete_cue,
    "update_cue": _h_update_cue,
    "reorder_cues": _h_reorder_cues,
    "list_cues": _h_list_cues,
    "go_cue": _h_go_cue,
    "go_next_cue": _h_go_next_cue,
    "go_prev_cue": _h_go_prev_cue,
    "get_cue_state": _h_get_cue_state,
}
