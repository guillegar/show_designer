"""
handlers/live.py — C1 performance grid + C2 macros en vivo + I1 grabación de macros (ADR-005).
"""
from __future__ import annotations

from server.validators import ValidationError, require_int

# ── C1 — Performance grid: lanzar patterns en vivo ──────────────────────────

def _live_emit(session, state: dict) -> None:
    """Emite {type:'live_state_changed'} al stream hub si está disponible."""
    import asyncio
    hub = getattr(session, "hub", None)
    if hub:
        try:
            asyncio.ensure_future(
                hub.broadcast_json({"type": "live_state_changed", **state})
            )
        except Exception:
            pass


def _h_live_assign_slot(session, params):
    """live_assign_slot(slot_idx, pattern_uid?, key?, quantize?, mode?) → {ok, slot}.

    Asigna o actualiza la configuración de un slot del performance grid.
    Limpia el slot en live_slots del timeline y toma snapshot para undo (I1).
    """
    try:
        slot_idx = require_int(params, "slot_idx", min_val=0)
        if slot_idx > 15:
            return {"ok": False, "error": "slot_idx debe ser 0..15"}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    pattern_uid = params.get("pattern_uid")
    key = params.get("key")
    quantize = params.get("quantize")
    mode = params.get("mode")

    # Validar que el pattern existe (si se pasa uno)
    if pattern_uid:
        if not any(p.get("uid") == pattern_uid for p in session.timeline.patterns):
            return {"ok": False, "error": "pattern_uid no encontrado"}

    session.snapshot()
    try:
        slot = session.live_engine.assign_slot(
            slot_idx,
            pattern_uid=pattern_uid,
            key=key,
            quantize=quantize,
            mode=mode,
        )
    except IndexError as e:
        return {"ok": False, "error": str(e)}

    session.timeline.live_slots = session.live_engine.slots_to_dicts()
    state = session.live_engine.get_state(session.analysis)
    _live_emit(session, state)
    return {"ok": True, "slot": slot.to_dict()}


def _h_live_trigger(session, params):
    """live_trigger(slot_idx) → {ok, slot, armed_at_ms}.

    Dispara un slot: lo arma hasta el próximo límite de cuantización.
    Si quantize='bar' pero no hay downbeats → degrada a 'free' (armed_at_ms = t_actual).
    """
    try:
        slot_idx = require_int(params, "slot_idx", min_val=0)
        if slot_idx > 15:
            return {"ok": False, "error": "slot_idx debe ser 0..15"}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    t_ms = float(params.get("t_ms", session.time * 1000))
    slot, t_armed = session.live_engine.trigger(slot_idx, t_ms, session.analysis)
    state = session.live_engine.get_state(session.analysis)
    _live_emit(session, state)
    return {"ok": True, "slot": slot.to_dict(), "armed_at_ms": t_armed}


def _h_live_release(session, params):
    """live_release(slot_idx) → {ok}.

    Detiene un slot. Solo relevante para mode='hold'; libera también los demás modos.
    """
    try:
        slot_idx = require_int(params, "slot_idx", min_val=0)
        if slot_idx > 15:
            return {"ok": False, "error": "slot_idx debe ser 0..15"}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    slot = session.live_engine.release(slot_idx)
    state = session.live_engine.get_state(session.analysis)
    _live_emit(session, state)
    return {"ok": True, "slot": slot.to_dict()}


def _h_live_stop_all(session, params):
    """live_stop_all() → {ok}.

    Botón de pánico: detiene todos los slots activos y armados.
    """
    session.live_engine.stop_all()
    state = session.live_engine.get_state(session.analysis)
    _live_emit(session, state)
    return {"ok": True}


def _h_get_live_state(session, params):
    """get_live_state() → {ok, slots, active, armed}.

    Estado completo de los 16 slots con flags active/armed/degraded.
    """
    state = session.live_engine.get_state(session.analysis)
    return {"ok": True, **state}


# C2 — Macros en vivo
_MACRO_RANGES: dict = {
    "brightness_mul": (0.0, 2.0),
    "speed_mul":      (0.0, 4.0),
    "hue_shift":      (-180.0, 180.0),
    "strobe_rate":    (0.0, 30.0),
}


def _h_set_macro(session, params):
    """set_macro(name, value) → {ok, macros}.

    Modifica una macro en vivo (estado de sesión, no del show.json).
    Throttle recomendado en el cliente: ≤ 20 llamadas/s.
    """
    name = params.get("name")
    if name not in _MACRO_RANGES:
        return {"ok": False, "error": f"Macro desconocida: {name!r}. "
                f"Válidas: {list(_MACRO_RANGES)}"}
    lo, hi = _MACRO_RANGES[name]
    try:
        value = float(params["value"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "value requerido (float)"}
    if not (lo <= value <= hi):
        return {"ok": False, "error": f"{name} debe estar en [{lo}, {hi}], recibido {value}"}
    session.macros[name] = value
    return {"ok": True, "macros": dict(session.macros)}


# ── I1 — Grabación en vivo de macros ────────────────────────────────────────

def _h_start_record(session, params):
    """start_record() → {ok, recording: True}.

    Activa la grabación de macros. Limpia puntos anteriores y registra el
    tiempo de inicio. Mientras graba, compute_frame captura cada cambio de
    macro con throttle 50ms.
    """
    session._recorded_lanes = {}
    session._record_last_ms = {}
    session._record_start_ms = float(session._current_t_ms)
    session._recording = True
    return {"ok": True, "recording": True}


def _h_stop_record(session, params):
    """stop_record() → {ok, recording: False, lanes_created: int, lane_uids: [str]}.

    Detiene la grabación y convierte los puntos capturados en AutomationLanes
    en session.timeline.automation. Es idempotente: llamar sin grabación activa
    devuelve lanes_created=0. Las lanes son undoables (I1).
    """
    if not session._recording and not session._recorded_lanes:
        return {"ok": True, "recording": False, "lanes_created": 0, "lane_uids": []}

    session._recording = False

    from uuid import uuid4

    from src.core.automation import AutomationLane

    start_ms = session._record_start_ms
    lane_uids = []

    # Snapshot ANTES de mutar → undo revierte las lanes creadas (I1)
    session.snapshot()

    for macro_name, points in session._recorded_lanes.items():
        if not points:
            continue
        target = f"master:{macro_name}"
        auto_points = [
            {"t_ms": int(pt["t_ms"] - start_ms), "value": float(pt["value"]), "shape": "linear"}
            for pt in points
        ]
        uid = uuid4().hex[:12]
        lane = AutomationLane(uid=uid, target=target, points=auto_points, enabled=True)
        session.timeline.automation.append(lane.to_dict())
        lane_uids.append(uid)

    session._recorded_lanes = {}
    session._record_last_ms = {}
    session.invalidate_caches()
    return {
        "ok": True,
        "recording": False,
        "lanes_created": len(lane_uids),
        "lane_uids": lane_uids,
    }


def _h_get_record_state(session, params):
    """get_record_state() → {ok, recording, elapsed_ms, points_captured}."""
    recording = getattr(session, '_recording', False)
    elapsed = (float(session._current_t_ms) - session._record_start_ms) if recording else 0.0
    points = sum(len(v) for v in getattr(session, '_recorded_lanes', {}).values())
    return {
        "ok": True,
        "recording": recording,
        "elapsed_ms": elapsed,
        "points_captured": points,
    }

HANDLERS = {
    "live_assign_slot": _h_live_assign_slot,
    "live_trigger": _h_live_trigger,
    "live_release": _h_live_release,
    "live_stop_all": _h_live_stop_all,
    "get_live_state": _h_get_live_state,
    "set_macro": _h_set_macro,
    "start_record": _h_start_record,
    "stop_record": _h_stop_record,
    "get_record_state": _h_get_record_state,
}
