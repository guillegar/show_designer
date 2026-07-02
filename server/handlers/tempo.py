"""
handlers/tempo.py — G2 sync de tempo (Link/MIDI clock) + M1 tap BPM y detección de tonalidad (ADR-005).
"""
from __future__ import annotations

import asyncio

from server.validators import require_key

# ── G2 — Sync de tempo (Ableton Link / MIDI Clock) ──────────────────────────

def _h_tempo_sync_get_state(session, params):
    """tempo_sync_get_state() → {mode, bpm, beat_phase, midi_device, synced}"""
    ts = getattr(session, "tempo_sync", None)
    if ts is None:
        return {"mode": "off", "bpm": 0.0, "beat_phase": 0.0,
                "midi_device": None, "synced": False}
    return ts.get_state()


def _h_tempo_sync_set_mode(session, params):
    """tempo_sync_set_mode(mode, device?) — mode ∈ {"off","link","midi_clock"}.

    Activa/desactiva la sincronización de tempo. Si mode="midi_clock", device
    es el nombre del puerto MIDI (string). Si omitido, mido elige el primero disponible.
    """
    mode = require_key(params, "mode")
    device = params.get("device")
    ts = getattr(session, "tempo_sync", None)
    if ts is None:
        return {"ok": False, "error": "TempoSyncService no disponible"}
    asyncio.create_task(ts.start(mode, device))
    return {"ok": True, "state": ts.get_state()}


def _h_tempo_sync_list_midi_ports(session, params):
    """tempo_sync_list_midi_ports() → {ok, ports: [str]}

    Lista los puertos MIDI disponibles para MIDI Clock.
    """
    try:
        import mido  # type: ignore
        ports = mido.get_input_names()
    except ImportError:
        ports = []
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "ports": list(ports)}


# ── M1 — Tap BPM + key detection ─────────────────────────────────────────────

def _h_tap_bpm(session, params):
    """tap_bpm() → {bpm, taps, ready}.
    Registra un tap de tempo; tras 4+ taps calcula BPM por mediana.
    """
    import time as _time
    ts = getattr(session, "tempo_sync", None)
    if ts is None:
        return {"ok": False, "error": "TempoSyncService no disponible"}
    result = ts.tap(_time.perf_counter())
    result["ok"] = True
    return result


def _h_get_key_info(session, params):
    """get_key_info() → {ok, status, key?, mode?, confidence?}.
    Si ya calculado → devuelve desde caché. Si no → lanza en executor
    y devuelve {status: 'computing'}. El resultado llegará como evento del stream.
    """
    cache = getattr(session, "_key_cache", None)
    if cache is not None:
        return {"ok": True, "status": "ready", **cache}

    # Lanzar detección en executor (no bloquea el event loop)
    import concurrent.futures

    audio_path = getattr(session, "audio_path", None) or ""
    if not audio_path:
        return {"ok": False, "error": "No hay audio cargado"}

    loop = asyncio.get_event_loop()
    hub = getattr(session, "hub", None)

    def _detect_and_cache():
        from server.key_detector import detect_key
        result = detect_key(audio_path)
        session._key_cache = result
        if hub is not None:
            import asyncio as _aio
            try:
                _aio.run_coroutine_threadsafe(
                    hub.broadcast_json({"type": "key_detected", **result}),
                    loop,
                )
            except Exception:
                pass

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    loop.run_in_executor(executor, _detect_and_cache)
    return {"ok": True, "status": "computing"}


HANDLERS = {
    "tempo_sync_get_state": _h_tempo_sync_get_state,
    "tempo_sync_set_mode": _h_tempo_sync_set_mode,
    "tempo_sync_list_midi_ports": _h_tempo_sync_list_midi_ports,
    "tap_bpm": _h_tap_bpm,
    "get_key_info": _h_get_key_info,
}
