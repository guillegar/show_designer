"""
test_offline_render.py — Fase B3: render offline + playback baked.

Tests:
    test_frozen_copy_independent    Mutar la copia congelada no afecta session.timeline
    test_render_produces_npz        Worker sobre escena sintética → npz correcto
    test_hash_invalidation          Mutar timeline pone baked_frames=None
    test_parity_baked_vs_live       Para N instantes: frame baked == compute_frame live
    test_render_meta_roundtrip      Meta JSON persiste fps, n_frames, hash
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.timeline_model import Timeline, Clip  # noqa: E402
from src.core.effects_engine import EffectLibrary, NUM_BARS, LEDS_PER_BAR  # noqa: E402
from server.offline_render import _render_worker, compute_timeline_hash  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_synthetic_timeline(n_clips: int = 5, duration_ms: int = 1000) -> Timeline:
    """Timeline sintético con n_clips solid_color en pistas 0..n-1."""
    tl = Timeline(duration_ms=duration_ms)
    from src.core.timeline_model import make_default_groups
    tl.groups = make_default_groups()
    for i in range(n_clips):
        tl.clips.append(Clip(
            track=i % NUM_BARS,
            start_ms=0,
            end_ms=duration_ms,
            effect_id=1004,  # solid_color
            scope='per_bar',
            params={'r': 100 + i * 10, 'g': 50, 'b': 200},
        ))
    return tl


_LIBRARY = None


def _get_library() -> EffectLibrary:
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = EffectLibrary()
    return _LIBRARY


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFrozenCopyIndependent:
    """La copia congelada es realmente independiente del original."""

    def test_clip_mutation_does_not_propagate(self):
        """Mutar un clip de la copia no afecta al timeline original."""
        tl = _make_synthetic_timeline(3)
        tl_dict = tl.to_dict()
        frozen = Timeline.from_dict(tl_dict)

        original_track = tl.clips[0].track
        frozen.clips[0].track = 9  # mutar la copia

        assert tl.clips[0].track == original_track, (
            "Mutar el clip de la copia congelada afectó al original")

    def test_clip_list_mutation_does_not_propagate(self):
        """Añadir un clip a la copia no afecta al timeline original."""
        tl = _make_synthetic_timeline(2)
        n_orig = len(tl.clips)
        frozen = Timeline.from_dict(tl.to_dict())

        extra = Clip(track=9, start_ms=0, end_ms=500, effect_id=0, scope='per_bar')
        frozen.clips.append(extra)

        assert len(tl.clips) == n_orig, (
            "Añadir un clip a la copia congelada afectó al original")


class TestRenderProducesNpz:
    """El worker crea el npz con la forma y dtype correctos."""

    def test_npz_exists_after_render(self, tmp_path):
        tl = _make_synthetic_timeline(5, duration_ms=1000)
        out = tmp_path / "render.npz"
        show_hash = compute_timeline_hash(tl.to_dict())

        _render_worker(tl, _get_library(), None, 30, 30, out, show_hash, None)

        assert out.is_file(), "render.npz no fue creado"

    def test_npz_shape_and_dtype(self, tmp_path):
        tl = _make_synthetic_timeline(5, duration_ms=1000)
        out = tmp_path / "render.npz"
        show_hash = compute_timeline_hash(tl.to_dict())

        _render_worker(tl, _get_library(), None, 30, 30, out, show_hash, None)

        data = np.load(str(out))
        frames = data['frames']
        assert frames.shape == (30, NUM_BARS, LEDS_PER_BAR, 3), (
            f"Shape inesperada: {frames.shape}")
        assert frames.dtype == np.uint8, f"dtype inesperado: {frames.dtype}"

    def test_npz_values_in_range(self, tmp_path):
        tl = _make_synthetic_timeline(5, duration_ms=1000)
        out = tmp_path / "render.npz"
        show_hash = compute_timeline_hash(tl.to_dict())

        _render_worker(tl, _get_library(), None, 30, 30, out, show_hash, None)

        frames = np.load(str(out))['frames']
        assert int(frames.min()) >= 0
        assert int(frames.max()) <= 255


class TestHashInvalidation:
    """Mutar el timeline invalida baked_frames en la sesión."""

    def test_invalidate_caches_clears_baked(self):
        from server.session import ShowSession

        sess = ShowSession()
        # Simular baked cargado
        sess.baked_frames = np.zeros((30, NUM_BARS, LEDS_PER_BAR, 3), dtype=np.uint8)
        sess.baked_hash = "testhash"

        sess.invalidate_caches()

        assert sess.baked_frames is None, "invalidate_caches no puso baked_frames=None"
        assert sess.baked_hash is None, "invalidate_caches no puso baked_hash=None"

    def test_invalidate_pattern_cache_clears_baked(self):
        from server.session import ShowSession

        sess = ShowSession()
        sess.baked_frames = np.zeros((30, NUM_BARS, LEDS_PER_BAR, 3), dtype=np.uint8)
        sess.baked_hash = "testhash"

        sess.invalidate_pattern_cache()

        assert sess.baked_frames is None
        assert sess.baked_hash is None


class TestParityBakedVsLive:
    """Para N instantes aleatorios, frame baked == compute_frame en vivo.

    Condiciones del test:
    - Timeline sintético sin mixer (identity postfx → no-op)
    - Sólo clips solid_color (deterministas, sin aleatoriedad)
    - baked_frames=None en la sesión (fuerza ruta live para la comparación)
    """

    def test_parity_n_random_frames(self, tmp_path):
        import random
        from server.session import ShowSession

        FPS = 30
        DURATION_MS = 1000
        N_FRAMES = 30

        tl = _make_synthetic_timeline(3, duration_ms=DURATION_MS)

        # Render a baked frames
        out = tmp_path / "render.npz"
        show_hash = compute_timeline_hash(tl.to_dict())
        _render_worker(tl, _get_library(), None, N_FRAMES, FPS, out, show_hash, None)
        baked = np.load(str(out))['frames']

        # Sesión en modo live (baked_frames = None)
        sess = ShowSession()
        sess.timeline = tl
        sess.baked_frames = None   # aseguramos modo live
        sess.baked_hash = None
        sess.invalidate_clip_index()  # reconstruir bucket index

        random.seed(42)
        sample_indices = random.sample(range(N_FRAMES), min(5, N_FRAMES))

        for frame_idx in sample_indices:
            t_s = frame_idx / FPS
            live_frame = sess.compute_frame(t_s)
            baked_frame = baked[frame_idx]
            np.testing.assert_array_equal(
                live_frame, baked_frame,
                err_msg=f"Paridad fallida en frame_idx={frame_idx}, t_s={t_s:.3f}"
            )


class TestRenderMetaRoundtrip:
    """render_meta.json persiste fps, n_frames y show_hash correctamente."""

    def test_meta_fields(self, tmp_path):
        import json

        tl = _make_synthetic_timeline(2, duration_ms=1000)
        out = tmp_path / "render.npz"
        expected_hash = compute_timeline_hash(tl.to_dict())
        FPS = 30
        N_FRAMES = 30

        _render_worker(tl, _get_library(), None, N_FRAMES, FPS, out, expected_hash, None)

        meta_path = tmp_path / "render_meta.json"
        assert meta_path.is_file(), "render_meta.json no fue creado"

        with open(meta_path, encoding='utf-8') as f:
            meta = json.load(f)

        assert meta["fps"] == FPS
        assert meta["n_frames"] == N_FRAMES
        assert meta["show_hash"] == expected_hash
        assert abs(meta["duration_s"] - N_FRAMES / FPS) < 0.01

    def test_hash_deterministic(self):
        """El mismo timeline siempre produce el mismo hash."""
        tl = _make_synthetic_timeline(4, duration_ms=2000)
        h1 = compute_timeline_hash(tl.to_dict())
        h2 = compute_timeline_hash(tl.to_dict())
        assert h1 == h2

    def test_different_clips_different_hash(self):
        """Timelines distintos producen hashes distintos."""
        tl1 = _make_synthetic_timeline(2, duration_ms=1000)
        tl2 = _make_synthetic_timeline(3, duration_ms=1000)
        assert compute_timeline_hash(tl1.to_dict()) != compute_timeline_hash(tl2.to_dict())
