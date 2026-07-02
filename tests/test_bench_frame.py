"""
test_bench_frame.py — ROADMAP v2, F0.5: presupuesto de rendimiento del frame (I5).

`compute_frame(t)` debe mantenerse bajo presupuesto en la escena de referencia.
Toda fase que toque el camino del frame corre este bench antes y después;
una regresión >20% bloquea el merge (comparar a mano los números impresos).

Escena de referencia: 30 clips ACTIVOS simultáneos (realista: El Taser tiene
~10-30 activos a la vez). Presupuesto: p95 < 33 ms = un frame a 30 FPS.
Se imprime también la escena de estrés (100 clips) como número de comparación
entre fases — el guardián REAL es la regresión >20%, no el absoluto (el
absoluto depende del hardware donde corre la suite).

Medido al crear este bench (F0, VM de CI): 30 clips p50≈20 ms · 100 clips
p50≈72 ms · coste del actx real (F0.0): 0.004 ms/frame (despreciable).

Ejecutar solo el bench:  pytest tests/test_bench_frame.py -v -s -m bench
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.timeline_model import Clip, Timeline  # noqa: E402

# Windows Python es ~2× más lento que Linux CI en cómputo puro (GIL + scheduler).
# El guardián REAL es la regresión >20% entre fases, no el absoluto de plataforma.
BUDGET_P95_MS = 33.0 if sys.platform != "win32" else 100.0
N_ITER = 200


def _build_scene(n_active: int, duration_ms: int = 60_000) -> Timeline:
    """n_active clips ACTIVOS en t=30s, repartidos en 10 pistas × capas."""
    tl = Timeline(duration_ms=duration_ms)
    effect_ids = [0, 1, 3, 10, 11, 13, 20, 21, 30, 31]  # variados del catálogo
    for i in range(n_active):
        tl.add(Clip(
            track=i % 10,
            start_ms=0,
            end_ms=duration_ms,
            effect_id=effect_ids[i % len(effect_ids)],
            scope='per_bar',
            layer=(i // 10) % 3,
            params={},
        ))
    return tl


def _measure(session, n_iter=N_ITER, t_probe=30.0):
    session.compute_frame(t_probe)  # warm-up (índice + librerías)
    samples = []
    for _ in range(n_iter):
        t0 = time.perf_counter()
        session.compute_frame(t_probe)
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return samples[len(samples) // 2], samples[int(len(samples) * 0.95)]


@pytest.mark.bench
def test_compute_frame_p95_bajo_presupuesto():
    from server.session import ShowSession
    session = ShowSession()
    original_tl = session.timeline
    try:
        # Escena de referencia (30 activos) — la que tiene presupuesto
        session.timeline = _build_scene(30)
        session.invalidate_clip_index()
        p50, p95 = _measure(session)
        # Escena de estrés (100 activos) — solo número de comparación entre fases
        session.timeline = _build_scene(100)
        session.invalidate_clip_index()
        s50, _ = _measure(session, n_iter=60)
        print(f"\n[bench] 30 clips: p50={p50:.2f} ms  p95={p95:.2f} ms "
              f"(presupuesto p95 < {BUDGET_P95_MS} ms) | estrés 100 clips: p50={s50:.2f} ms")
        assert p95 < BUDGET_P95_MS, (
            f"compute_frame p95={p95:.2f} ms supera el presupuesto de "
            f"{BUDGET_P95_MS} ms (I5). ¿Qué se añadió al camino del frame?")
    finally:
        session.timeline = original_tl
        session.invalidate_clip_index()
