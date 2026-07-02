"""
handlers/waveform.py — B1: forma de onda del audio para el timeline (ADR-005).

El cálculo (librosa.load, ~2-5 s) NUNCA corre en el event loop: si no hay cache
se lanza en un executor y el resultado llega por el evento 'waveform_ready'.
"""
from __future__ import annotations

# ── B1 — Waveform en el timeline ─────────────────────────────────────────────

_WAVEFORM_N_BUCKETS = 8000


def _compute_waveform(audio_path, n=_WAVEFORM_N_BUCKETS, bpm=120.0):
    """Cálculo puro y pesado de la forma de onda (librosa.load + min/max/rms por
    cubo). BLOQUEANTE (~2-5 s) → debe correr en un executor, NUNCA en el event
    loop. Devuelve el dict de datos, o None si librosa no está disponible."""
    try:
        import librosa as _librosa
        import numpy as _np
    except ImportError:
        return None

    y, sr = _librosa.load(str(audio_path), sr=None, mono=True)
    total = len(y)
    chunk = max(1, total // n)

    peaks_max, peaks_min, rms_vals = [], [], []
    for i in range(n):
        s = i * chunk
        e = s + chunk if i < n - 1 else total
        block = y[s:e]
        if len(block) == 0:
            peaks_max.append(0.0)
            peaks_min.append(0.0)
            rms_vals.append(0.0)
        else:
            peaks_max.append(round(float(_np.max(block)), 5))
            peaks_min.append(round(float(_np.min(block)), 5))
            rms_vals.append(round(float(_np.sqrt(_np.mean(block ** 2))), 5))

    return {
        "peaks_max": peaks_max,
        "peaks_min": peaks_min,
        "rms": rms_vals,
        "n_buckets": n,
        "duration_sec": round(float(total / sr), 3),
        "bpm": float(bpm),
    }


def _ensure_waveform_cached(session):
    """Garantiza que <analysis_dir>/waveform.json existe y devuelve sus datos.

    Es la parte BLOQUEANTE (pensada para correr en un executor). Idempotente: si
    el cache ya está, lo lee; si no, calcula y lo escribe atómicamente
    (.tmp → replace). Devuelve el dict de datos, o None (sin librosa o sin audio).
    """
    import json as _json
    from pathlib import Path as _Path

    analysis_dir = session.analysis.analysis_dir
    cache_path = analysis_dir / "waveform.json"
    if cache_path.is_file():
        try:
            return _json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass  # cache corrupto → recomputar

    audio_path = _Path(session.project.audio_path)
    if not audio_path.is_file():
        return None

    data = _compute_waveform(audio_path, _WAVEFORM_N_BUCKETS,
                             float(getattr(session, "bpm", 120)))
    if data is None:
        return None

    analysis_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(_json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(cache_path)
    return data


def _h_get_waveform(session, params):
    """Forma de onda del audio en _WAVEFORM_N_BUCKETS cubos.

    El cálculo (librosa.load) tarda ~2-5 s y `dispatcher.handle` corre en el hilo
    del event loop (el MISMO del tick): bloquearlo congela el show en vivo. Por
    eso: si el cache existe se devuelve al instante; si no, se lanza el cálculo en
    un executor y se devuelve {status:'computing'} — el frontend recibe el evento
    'waveform_ready' por el stream y vuelve a pedirlo (ya cache hit). En contextos
    SIN event loop (tests / compat MCP síncrona) se calcula inline.
    """
    import asyncio
    import json as _json

    analysis_dir = session.analysis.analysis_dir
    cache_path = analysis_dir / "waveform.json"
    if cache_path.is_file():
        try:
            return {"ok": True, **_json.loads(cache_path.read_text(encoding="utf-8"))}
        except Exception:
            pass  # cache corrupto → recomputar abajo

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        # Sin event loop (tests / compat MCP síncrona): calcular inline.
        data = _ensure_waveform_cached(session)
        if data is None:
            return {"ok": False, "error": "librosa no disponible o audio no encontrado"}
        return {"ok": True, **data}

    # Contexto web: NO bloquear el loop. Calcular en background y avisar por stream.
    if getattr(session, "_waveform_computing", False):
        return {"ok": True, "status": "computing"}
    session._waveform_computing = True
    hub = getattr(session, "hub", None)

    def _job():
        try:
            data = _ensure_waveform_cached(session)
        finally:
            session._waveform_computing = False
        if data is not None and hub is not None:
            try:
                asyncio.run_coroutine_threadsafe(
                    hub.broadcast_json({"type": "waveform_ready"}), loop)
            except Exception:
                pass

    loop.run_in_executor(None, _job)
    return {"ok": True, "status": "computing"}

HANDLERS = {
    "get_waveform": _h_get_waveform,
}
