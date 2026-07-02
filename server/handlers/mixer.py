"""
handlers/mixer.py — B2: mixer master + cadena por pista (ADR-005).
"""
from __future__ import annotations

from server.validators import ValidationError, require_int

# ── B2 — Mixer: cadena por pista + master ────────────────────────────────────
# Throttle en el cliente: los sliders no deben disparar más de ~20 req/s
# (cada llamada < 50 ms). Implementar en la UI con un ref de timestamp:
#   if (Date.now() - lastSent) < 50 ms → no enviar; actualizar solo en mouseUp.

_MIXER_CHAIN_KEYS = {'brightness', 'gamma', 'hue_shift', 'white_limit'}
_MASTER_KEYS = _MIXER_CHAIN_KEYS | {'blackout_fade'}


def _h_set_track_chain(session, params):
    """set_track_chain(track, chain) — actualiza la cadena postfx de una pista.

    chain = {brightness?:0..1, gamma?:0.5..2.2, hue_shift?:-180..180,
             white_limit?:0..1}
    Devuelve {ok, track, chain} (invariante I3).
    Throttle en el cliente: máx ~20 req/s (< 50 ms entre llamadas).
    """
    try:
        track = require_int(params, "track", min_val=0)
        if track > 9:
            return {"ok": False, "error": "'track' debe ser 0..9"}
        chain_in = params.get("chain", {})
        if not isinstance(chain_in, dict):
            return {"ok": False, "error": "chain debe ser un dict"}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    mixer = session.timeline.mixer
    if "tracks" not in mixer:
        mixer["tracks"] = {}

    current = dict(mixer["tracks"].get(str(track), {}))
    current.update({k: float(v) for k, v in chain_in.items()
                    if k in _MIXER_CHAIN_KEYS})
    mixer["tracks"][str(track)] = current

    session.notify_changed("mixer")
    return {"ok": True, "track": track, "chain": current}


def _h_set_master(session, params):
    """set_master(master) — actualiza el strip master del mixer.

    master = {brightness?:0..1, gamma?:0.5..2.2, hue_shift?:-180..180,
               white_limit?:0..1, blackout_fade?:0..1}
    Devuelve {ok, master} (invariante I3).
    Throttle en el cliente: máx ~20 req/s (< 50 ms entre llamadas).
    El blackout_fade es animable con una lane de A2 (target 'master:blackout_fade').
    """
    master_in = params.get("master", params)
    if not isinstance(master_in, dict):
        return {"ok": False, "error": "master debe ser un dict"}

    mixer = session.timeline.mixer
    current = dict(mixer.get("master", {}))
    current.update({k: float(v) for k, v in master_in.items()
                    if k in _MASTER_KEYS})
    mixer["master"] = current

    session.notify_changed("mixer")
    return {"ok": True, "master": current}


def _h_get_mixer(session, params):
    """get_mixer() — devuelve el estado completo del mixer."""
    mixer = session.timeline.mixer
    return {
        "ok": True,
        "mixer": {
            "tracks": dict(mixer.get("tracks", {})),
            "master": dict(mixer.get("master", {})),
        },
    }


HANDLERS = {
    "set_track_chain": _h_set_track_chain,
    "set_master": _h_set_master,
    "get_mixer": _h_get_mixer,
}
