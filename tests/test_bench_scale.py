"""
test_bench_scale.py — Benchmarks de rendimiento a escala (H4).

Invariante I5 (v3): el sistema debe manejar shows grandes sin degradación observable.
Objetivos:
  - Timeline.to_dict()   con 5000 clips < 200 ms
  - Timeline.from_dict() con 5000 clips < 200 ms
  - list_clips handler   con 5000 clips < 500 ms
  - compute_frame p95    con 200 clips activos < 60 ms
  - tracemalloc: sin leaks > 1 MB tras 100 frames

Todos marcados con @pytest.mark.bench para poder excluirlos si se quiere.
Se pueden correr con: pytest tests/test_bench_scale.py -v -m bench
"""
import sys
import time
import tracemalloc
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.core.timeline_model import Timeline, make_default_groups

pytestmark = pytest.mark.bench


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_large_timeline(n: int = 5000) -> Timeline:
    """Construye un Timeline sintético con n clips."""
    from src.core.timeline_model import Clip
    dur_ms = max(n * 600, 300_000)
    tl = Timeline(duration_ms=dur_ms, groups=make_default_groups())
    for i in range(n):
        tl.clips.append(Clip(
            uid=f"bench_{i:05d}",
            track=i % 10,
            layer=0,
            start_ms=i * 500,
            end_ms=i * 500 + 400,
            effect_id=1 + (i % 5),
            params={},
        ))
    return tl


# ── Benchmarks serializacion ───────────────────────────────────────────────────

def test_bench_to_dict_5000_clips():
    """Timeline.to_dict() con 5000 clips debe completar en < 200 ms."""
    tl = _make_large_timeline(5000)
    t0 = time.perf_counter()
    d = tl.to_dict()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert len(d["clips"]) == 5000
    assert elapsed_ms < 200, (
        f"to_dict() tardó {elapsed_ms:.1f} ms (máx 200 ms para 5000 clips)"
    )


def test_bench_from_dict_5000_clips():
    """Timeline.from_dict() con 5000 clips debe completar en < 200 ms."""
    tl = _make_large_timeline(5000)
    d = tl.to_dict()
    t0 = time.perf_counter()
    tl2 = Timeline.from_dict(d)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert len(tl2.clips) == 5000
    assert elapsed_ms < 200, (
        f"from_dict() tardó {elapsed_ms:.1f} ms (máx 200 ms para 5000 clips)"
    )


# ── Benchmark list_clips handler ───────────────────────────────────────────────

def test_bench_list_clips_handler_5000():
    """list_clips handler con 5000 clips debe responder en < 500 ms."""
    from server.dispatcher import Dispatcher

    tl = _make_large_timeline(5000)
    session = MagicMock()
    session.timeline = tl
    session._pattern_rev = 0
    session._pattern_expanded = []
    session._pattern_expanded_rev = -1

    disp = Dispatcher(session)
    t0 = time.perf_counter()
    resp = disp.handle({"method": "list_clips", "params": {}})
    elapsed_ms = (time.perf_counter() - t0) * 1000

    result = resp.get("result", resp)
    clips = result.get("clips", [])
    assert len(clips) == 5000, f"Esperados 5000 clips, devueltos {len(clips)}"
    assert elapsed_ms < 500, (
        f"list_clips tardó {elapsed_ms:.1f} ms (máx 500 ms para 5000 clips)"
    )


# ── Benchmark paginacion ──────────────────────────────────────────────────────

def test_bench_list_clips_pagination():
    """list_clips con offset/limit devuelve el slice correcto."""
    from server.dispatcher import Dispatcher

    tl = _make_large_timeline(2000)
    session = MagicMock()
    session.timeline = tl
    session._pattern_rev = 0
    session._pattern_expanded = []
    session._pattern_expanded_rev = -1

    disp = Dispatcher(session)

    resp = disp.handle({"method": "list_clips", "params": {"offset": 100, "limit": 50}})
    result = resp.get("result", resp)
    clips = result.get("clips", [])

    assert len(clips) == 50, f"Esperados 50 clips, devueltos {len(clips)}"
    assert result.get("total") == 2000
    assert result.get("next_offset") == 150


# ── Benchmark compute_frame ────────────────────────────────────────────────────

def test_bench_compute_frame_200_active_clips_p95():
    """compute_frame con 200 clips activos en el mismo instante debe p95 < 60 ms."""
    from server.session import ShowSession
    from src.core.timeline_model import Clip

    # Construye una sesión mínima sin audio ni analysis real
    session = object.__new__(ShowSession)
    from server.live_engine import LiveEngine
    from server.undo_manager import UndoManager
    from src.core.effects_engine import EffectLibrary
    from src.core.timeline_model import Timeline, make_default_groups

    session.library = EffectLibrary()
    session.channel_lib = None
    session.show_engine = MagicMock()
    session.show_engine.rig = None
    session.fixture_rig = None
    session.muted_tracks = set()
    session.solo_tracks = set()
    session.macros = {
        "brightness_mul": 1.0, "speed_mul": 1.0,
        "hue_shift": 0.0, "strobe_rate": 0.0,
    }
    from src.core.autovj import AutoVJEngine
    session.live_engine = LiveEngine()
    session.autovj_engine = AutoVJEngine()
    session._live_mode = False
    session.live_input = None
    session.baked_frames = None
    session.blackout_override = False
    session._identify = {}
    session._test_universes = {}
    session._cue_fade_start_ms = None
    session._cue_fade_duration_ms = 0.0
    session._cue_fade_from_master = 1.0
    session._pattern_rev = 0
    session._pattern_expanded = []
    session._pattern_expanded_rev = -1
    session._postfx_chains = {}
    session._recording = False  # I1: compute_frame -> _maybe_record_macros lo lee

    from src.core.automation import AutomationStage
    from src.core.micro_events import MicroEventStage
    from src.core.modulation import ModulationStage
    session.param_stages = [ModulationStage(), AutomationStage(), MicroEventStage()]

    session._cached_actx = {
        'rms': 0.5, 'energy': 0.5, 'flux': 0.3, 'centroid': 4000, 'zcr': 0.2,
        'mfcc': np.zeros(13, dtype=np.float32),
        'chroma': np.full(12, 0.5, dtype=np.float32),
        'tonnetz': np.zeros(6, dtype=np.float32),
        'contrast': np.full(7, 30, dtype=np.float32),
        'mel_bands': np.full(8, -25, dtype=np.float32),
    }
    session.tempo_sync = MagicMock()
    session.tempo_sync.bpm = 0.0
    session.audio = MagicMock()
    session.audio.get_current_time = MagicMock(return_value=30.0)

    tl = Timeline(duration_ms=600_000, groups=make_default_groups())
    # 200 clips que cubren t=30000 ms
    for i in range(200):
        tl.clips.append(Clip(
            uid=f"bench_{i:04d}", track=i % 10, layer=0,
            start_ms=25_000, end_ms=35_000,
            effect_id=1 + (i % 5), params={},
        ))
    session.timeline = tl
    session._clip_bucket_index = {}
    session._clip_bucket_index_n = -1

    # Análisis mínimo
    analysis = MagicMock()
    analysis.context_at.return_value = session._cached_actx
    session.analysis = analysis

    times_ms = []
    for _ in range(30):
        t0 = time.perf_counter()
        session.compute_frame(30.0)
        times_ms.append((time.perf_counter() - t0) * 1000)

    p95 = sorted(times_ms)[int(len(times_ms) * 0.95)]
    assert p95 < 60, (
        f"compute_frame p95={p95:.1f} ms con 200 clips activos (máx 60 ms)"
    )


# ── Benchmark tracemalloc (sin leaks) ─────────────────────────────────────────

def test_bench_no_memory_leak_100_frames():
    """Tras 100 llamadas a to_dict(), el incremento de memoria debe ser < 1 MB."""
    tl = _make_large_timeline(500)

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    for _ in range(100):
        _ = tl.to_dict()

    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snapshot_after.compare_to(snapshot_before, "lineno")
    total_diff_bytes = sum(s.size_diff for s in stats if s.size_diff > 0)
    total_diff_mb = total_diff_bytes / (1024 * 1024)

    assert total_diff_mb < 1.0, (
        f"Posible leak: {total_diff_mb:.2f} MB retenidos tras 100 to_dict() "
        f"(máx 1 MB)"
    )
