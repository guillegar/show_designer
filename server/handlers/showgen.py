"""
handlers/showgen.py — M2 generación automática de show + M3 historial de gestos (ADR-005).
"""
from __future__ import annotations

from server.validators import require_int

# ── M2 — Generación automática de show ───────────────────────────────────────

def _h_generate_show(session, params):
    """generate_show(style?, density?, replace?) → {ok, clips_created: int}.

    Genera clips automáticamente desde el análisis de audio. Sin IA externa.
    Toma snapshot antes de mutar (deshaciable con Ctrl+Z) — I1.
    Corre en executor si los datos son voluminosos — I6.
    """
    from server.show_generator import STYLES, generate_show

    style = params.get("style", "club")
    if style not in STYLES:
        return {"ok": False, "error": f"style debe ser uno de {STYLES}"}
    density = float(params.get("density", 0.5))
    density = max(0.0, min(1.0, density))
    replace = bool(params.get("replace", False))

    # Obtener datos de análisis
    analysis = getattr(session, "analysis", None)
    if analysis is None:
        return {"ok": False, "error": "No hay análisis disponible para este show"}

    try:
        beats = analysis.list_beats()
        downbeats = analysis.list_downbeats()
        sections = analysis.list_sections()
    except Exception as e:
        return {"ok": False, "error": f"Error leyendo análisis: {e}"}

    if not beats and not downbeats:
        return {"ok": False, "error": "El análisis no tiene beats detectados"}

    bpm = getattr(session, "bpm", None) or 120.0

    # I1: snapshot para undo
    try:
        session.snapshot()
    except Exception:
        pass

    # Limpiar timeline si replace=True
    if replace:
        session.timeline.clips.clear()

    # Generar clips
    new_clips = generate_show(beats, downbeats, sections, style, density, bpm)

    # Añadir clips al timeline
    from src.core.timeline_model import Clip
    for cd in new_clips:
        clip = Clip(
            track=cd["track"],
            start_ms=cd["start_ms"],
            end_ms=cd["end_ms"],
            effect_id=cd["effect_id"],
            scope=cd.get("scope", "per_bar"),
            params=cd.get("params", {}),
            color=cd.get("color", "#3a7acc"),
            label=cd.get("label", "GEN"),
            layer=cd.get("layer", 0),
            uid=cd.get("uid") or None,
        )
        if cd.get("uid"):
            clip.uid = cd["uid"]
        session.timeline.clips.append(clip)

    session.invalidate_caches()
    return {"ok": True, "clips_created": len(new_clips)}


# ── M3 — Historial de gestos y replay ────────────────────────────────────────

def _h_list_gesture_history(session, params):
    """list_gesture_history(last?: int) → {ok, gestures: [...]}."""
    gl = getattr(session, "_gesture_log", None)
    if gl is None:
        return {"ok": True, "gestures": []}
    last = int(params.get("last", 200))
    return {"ok": True, "gestures": gl.list(last)}


def _h_replay_gesture(session, params):
    """replay_gesture(idx: int) → resultado del handler re-ejecutado."""
    idx = require_int(params, "idx")
    gl = getattr(session, "_gesture_log", None)
    if gl is None:
        return {"ok": False, "error": "GestureLog no disponible"}
    entry = gl.get(idx)
    if entry is None:
        return {"ok": False, "error": f"Gesto {idx} no encontrado"}
    handler_name = entry["handler"]
    handler_params = entry.get("params") or {}
    # Import perezoso del registro COMPLETO del dispatcher (core + dominios
    # mergeados): en import-time sería circular; en request-time ya está cargado.
    from server.dispatcher import _LOCAL as _all_handlers
    if handler_name in _all_handlers:
        try:
            return _all_handlers[handler_name](session, handler_params)
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": f"Handler {handler_name!r} no re-ejecutable"}


def _h_clear_gesture_history(session, params):
    """clear_gesture_history() → {ok}."""
    gl = getattr(session, "_gesture_log", None)
    if gl is not None:
        gl.clear()
    return {"ok": True}


HANDLERS = {
    "generate_show": _h_generate_show,
    "list_gesture_history": _h_list_gesture_history,
    "replay_gesture": _h_replay_gesture,
    "clear_gesture_history": _h_clear_gesture_history,
}
