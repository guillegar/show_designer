"""
test_postfx.py — Tests de la cadena de post-procesado (Fase B2, ROADMAP v2).

Cubre:
    - apply_track_chain: brightness 0.5 atenúa a la mitad
    - gamma != 1 cambia valores (array sintético)
    - hue_shift != 0 rota el hue (color puro)
    - white_limit clampea blancos
    - no-op parity: fast path devuelve la MISMA referencia, byte-exacto
    - apply_master: blackout_fade=0 → negro; blackout_fade=1 → no cambia
    - persistencia: set_track_chain → save → load → valores preservados
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.postfx import apply_master, apply_track_chain  # noqa: E402

# ── Helpers ──────────────────────────────────────────────────────────────────

def make_bar(r: int, g: int, b: int, n_leds: int = 93) -> np.ndarray:
    bar = np.zeros((n_leds, 3), dtype=np.uint8)
    bar[:, 0] = r; bar[:, 1] = g; bar[:, 2] = b
    return bar


def make_frame(r: int, g: int, b: int,
               n_bars: int = 10, n_leds: int = 93) -> np.ndarray:
    frame = np.zeros((n_bars, n_leds, 3), dtype=np.uint8)
    frame[:, :, 0] = r; frame[:, :, 1] = g; frame[:, :, 2] = b
    return frame


# ── apply_track_chain ────────────────────────────────────────────────────────

class TestApplyTrackChain:

    def test_brightness_half_attenuates(self):
        """brightness=0.5 debe atenuar cada canal a la mitad (±1 por redondeo)."""
        bar = make_bar(200, 100, 50)
        out = apply_track_chain(bar, {'brightness': 0.5})
        assert abs(float(out[:, 0].mean()) - 100.0) <= 1.0
        assert abs(float(out[:, 1].mean()) - 50.0) <= 1.0
        assert abs(float(out[:, 2].mean()) - 25.0) <= 1.0

    def test_brightness_zero_black(self):
        bar = make_bar(200, 100, 50)
        out = apply_track_chain(bar, {'brightness': 0.0})
        assert out.sum() == 0

    def test_gamma_greater_than_one_brightens_mids(self):
        """gamma=2 → f^0.5: las semigrises se acercan a 255 (más claro)."""
        bar = make_bar(128, 128, 128)
        out = apply_track_chain(bar, {'gamma': 2.0})
        assert float(out[:, 0].mean()) > 128.0

    def test_gamma_less_than_one_darkens_mids(self):
        """gamma=0.5 → f^2: las semigrises se acercan a 0 (más oscuro)."""
        bar = make_bar(128, 128, 128)
        out = apply_track_chain(bar, {'gamma': 0.5})
        assert float(out[:, 0].mean()) < 128.0

    def test_gamma_one_is_identity(self):
        """gamma=1 NO cambia valores (f^1 = f)."""
        bar = make_bar(128, 128, 128)
        out = apply_track_chain(bar, {'gamma': 1.0})
        # No es fast path porque brightness/hue_shift/white_limit siguen siendo identity,
        # pero gamma=1 en _apply_chain_ops no llama power → mismo resultado numérico.
        np.testing.assert_array_equal(out, bar)

    def test_hue_shift_pure_red_120_becomes_green(self):
        """rojo puro (255,0,0) + hue_shift=120° → verde puro (0,255,0)."""
        bar = make_bar(255, 0, 0)
        out = apply_track_chain(bar, {'hue_shift': 120.0})
        # Canal verde ~255, rojo y azul ~0 (tolerancia ±2 por float32→uint8)
        assert float(out[:, 1].mean()) > 250
        assert float(out[:, 0].mean()) < 5
        assert float(out[:, 2].mean()) < 5

    def test_hue_shift_360_is_noop(self):
        """Giro de 360° ≡ 0° → valores idénticos (tolerancia rounding float32)."""
        bar = make_bar(180, 80, 40)
        out = apply_track_chain(bar, {'hue_shift': 360.0})
        np.testing.assert_allclose(out.astype(float), bar.astype(float), atol=2)

    def test_white_limit_clamps_whites(self):
        """white_limit=0.5 → ningún canal supera ~128."""
        bar = make_bar(255, 255, 255)
        out = apply_track_chain(bar, {'white_limit': 0.5})
        assert int(out.max()) <= 128

    def test_noop_parity_exact_reference(self):
        """brightness=1, gamma=1, hue_shift=0, white_limit=1 → fast path: misma referencia."""
        rng = np.random.default_rng(42)
        bar = rng.integers(0, 256, (93, 3), dtype=np.uint8)
        chain = {'brightness': 1.0, 'gamma': 1.0, 'hue_shift': 0.0, 'white_limit': 1.0}
        out = apply_track_chain(bar, chain)
        assert out is bar, "fast path debe devolver la misma referencia"

    def test_noop_empty_chain(self):
        """chain={} usa todos los defaults identidad → misma referencia."""
        rng = np.random.default_rng(7)
        bar = rng.integers(0, 256, (93, 3), dtype=np.uint8)
        out = apply_track_chain(bar, {})
        assert out is bar

    def test_output_shape_preserved(self):
        bar = make_bar(100, 150, 200, n_leds=93)
        out = apply_track_chain(bar, {'brightness': 0.8})
        assert out.shape == bar.shape
        assert out.dtype == np.uint8


# ── apply_master ─────────────────────────────────────────────────────────────

class TestApplyMaster:

    def test_blackout_fade_zero_is_black(self):
        """blackout_fade=0 → frame completamente negro."""
        frame = make_frame(200, 100, 50)
        out = apply_master(frame, {'blackout_fade': 0.0})
        assert out.sum() == 0

    def test_blackout_fade_one_noop_reference(self):
        """blackout_fade=1, sin otros cambios → fast path: misma referencia."""
        frame = make_frame(200, 100, 50)
        out = apply_master(frame, {'blackout_fade': 1.0})
        assert out is frame

    def test_blackout_fade_half_halves_brightness(self):
        frame = make_frame(200, 200, 200)
        out = apply_master(frame, {'blackout_fade': 0.5})
        assert abs(float(out[:, :, 0].mean()) - 100.0) <= 1.0

    def test_master_brightness_applies_globally(self):
        frame = make_frame(200, 100, 50)
        out = apply_master(frame, {'brightness': 0.5})
        assert abs(float(out[:, :, 0].mean()) - 100.0) <= 1.0

    def test_noop_parity_exact(self):
        """Todos los parámetros identidad → fast path: misma referencia."""
        rng = np.random.default_rng(99)
        frame = rng.integers(0, 256, (10, 93, 3), dtype=np.uint8)
        master = {'brightness': 1.0, 'gamma': 1.0,
                  'hue_shift': 0.0, 'white_limit': 1.0, 'blackout_fade': 1.0}
        out = apply_master(frame, master)
        assert out is frame

    def test_noop_empty_master(self):
        rng = np.random.default_rng(13)
        frame = rng.integers(0, 256, (10, 93, 3), dtype=np.uint8)
        out = apply_master(frame, {})
        assert out is frame

    def test_output_shape_preserved(self):
        frame = make_frame(100, 150, 200)
        out = apply_master(frame, {'blackout_fade': 0.8})
        assert out.shape == frame.shape
        assert out.dtype == np.uint8


# ── Persistencia: set_track_chain → save → load → valores preservados ────────

class TestPersistencia:

    def test_track_chain_roundtrip_via_timeline(self, tmp_path):
        """set_track_chain altera timeline.mixer; save + load preserva los valores."""
        from src.core.timeline_model import Timeline

        tl = Timeline()
        # Simular lo que hace _h_set_track_chain
        if "tracks" not in tl.mixer:
            tl.mixer["tracks"] = {}
        tl.mixer["tracks"]["3"] = {"brightness": 0.7, "gamma": 1.5,
                                    "hue_shift": -45.0, "white_limit": 0.9}
        tl.mixer["master"] = {"brightness": 0.8, "blackout_fade": 0.6}

        save_path = tmp_path / "show_b2_test.json"
        tl.save(save_path)

        tl2 = Timeline.load(save_path)
        assert tl2.mixer["tracks"]["3"]["brightness"] == pytest.approx(0.7)
        assert tl2.mixer["tracks"]["3"]["gamma"] == pytest.approx(1.5)
        assert tl2.mixer["tracks"]["3"]["hue_shift"] == pytest.approx(-45.0)
        assert tl2.mixer["master"]["blackout_fade"] == pytest.approx(0.6)

    def test_empty_mixer_roundtrip(self, tmp_path):
        """Un show sin mixer guardado carga sin error y mixer es un dict vacío."""
        from src.core.timeline_model import Timeline

        tl = Timeline()
        save_path = tmp_path / "show_empty_mixer.json"
        tl.save(save_path)

        tl2 = Timeline.load(save_path)
        assert isinstance(tl2.mixer, dict)
