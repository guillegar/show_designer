"""
test_perf_parity.py — ANALYSIS Fase 5 (rendimiento, hallazgos 12 y 14).

Las optimizaciones deben ser PARITY-EXACTAS: mismos resultados que la versión
O(n)/np.interp, solo más rápidas. Aquí se comparan contra una referencia ingenua.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Hallazgo 12: get_active_events con bisect == barrido lineal ──────────────

def test_get_active_events_bisect_parity():
    import random

    from src.core.effects_engine import EffectLibrary
    from src.core.show_engine import TimelineScheduler

    lib = EffectLibrary()
    sched = TimelineScheduler()
    random.seed(42)
    for _ in range(600):
        sched.add_beat_events([random.uniform(0.0, 300.0)],
                              effect_id=random.choice([0, 2, 10, 50, 1000]))

    def brute(t):
        out = []
        for e in sched.events:
            eff = lib.get_effect(e.effect_id)
            if eff and e.is_active(t, eff.duration_ms):
                out.append(e)
        return out

    for t in [-1.0, 0.0, 1.5, 50.0, 150.123, 200.0, 299.999, 305.0]:
        fast = sched.get_active_events(t, lib)
        ref = brute(t)
        assert {id(e) for e in fast} == {id(e) for e in ref}, f"mismatch en t={t}"


def test_get_active_events_empty():
    from src.core.effects_engine import EffectLibrary
    from src.core.show_engine import TimelineScheduler
    sched = TimelineScheduler()
    assert sched.get_active_events(10.0, EffectLibrary()) == []


# ── Hallazgo 14: get_audio_context (searchsorted) == np.interp por coeficiente ─

def test_get_audio_context_parity():
    from src.analysis.analyzer_service import default_service
    svc = default_service()
    svc._load_timeseries()
    ts = svc._timeseries
    if not ts or 'times' not in ts:
        pytest.skip("proyecto sin timeseries")
    ts_times = ts['times']

    def ref_ctx(t):
        out = {}
        for name in ('rms', 'centroid', 'flux', 'zcr', 'rolloff', 'bandwidth', 'flatness'):
            if name in ts and ts[name].ndim == 1:
                out[name] = float(np.interp(t, ts_times, ts[name], left=0.0, right=0.0))
        for name in ('mfcc', 'chroma', 'tonnetz', 'contrast', 'mel_bands'):
            if name in ts and ts[name].ndim == 2:
                arr = ts[name]
                out[name] = np.array(
                    [np.interp(t, ts_times, arr[i], left=0.0, right=0.0)
                     for i in range(arr.shape[0])], dtype=np.float32)
        return out

    t_last = float(ts_times[-1])
    for t in [-2.0, 0.0, 5.5, 72.3, 150.0, t_last, t_last + 10.0]:
        got = svc.get_audio_context(t)
        ref = ref_ctx(t)
        for k, v in ref.items():
            assert np.allclose(np.asarray(got[k], dtype=float),
                               np.asarray(v, dtype=float),
                               rtol=1e-4, atol=1e-5), f"{k} difiere en t={t}"
