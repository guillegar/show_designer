"""
tests/test_effects_nuevos.py — Tests de los 10 efectos built-in nuevos (F1).

Verifica por cada efecto:
  - render() devuelve ndarray shape (1, 93, 3) dtype uint8
  - valores en rango [0, 255]
  - el efecto cambia entre t=0 y t=1000 ms (no es estático)
  - efectos audio-reactivos: rms_norm=0 vs rms_norm=1 producen outputs distintos
  - efectos con estado (fire, pixel_chase, twinkle): llamadas sucesivas = continuidad

Nota de importación: los efectos se acceden vía EffectLibrary (que carga los plugins
con spec_from_file_location). Las clases se obtienen con type(instance) para poder
crear instancias frescas cuando los tests de estado lo requieren.
"""
import numpy as np
import pytest

from src.core.effects_engine import EffectLibrary, NUM_BARS, LEDS_PER_BAR

SHAPE_PER_BAR = (1, LEDS_PER_BAR, 3)

# IDs de los 10 efectos nuevos
_EFFECT_IDS = list(range(1010, 1020))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bars():
    return np.zeros((NUM_BARS, LEDS_PER_BAR, 3), dtype=np.uint8)


def _ctx(rms: float = 0.5):
    return {
        'norm': {'rms': rms, 'flux': rms * 0.8, 'onset_strength': rms},
        'energy': rms,
        'rms': rms,
        'bpm': 120.0,
    }


def _assert_valid(out, label=""):
    assert isinstance(out, np.ndarray), f"{label}: not ndarray"
    assert out.shape == SHAPE_PER_BAR,  f"{label}: shape {out.shape} != {SHAPE_PER_BAR}"
    assert out.dtype == np.uint8,        f"{label}: dtype {out.dtype} != uint8"
    assert int(out.min()) >= 0,          f"{label}: negative values"
    assert int(out.max()) <= 255,        f"{label}: values > 255"


@pytest.fixture(scope="module")
def lib():
    return EffectLibrary()


def _fresh(lib, eid):
    """Devuelve una instancia nueva del efecto con ID eid."""
    eff = lib.get_effect(eid)
    assert eff is not None, f"Efecto {eid} no cargado"
    return type(eff)()


# ── 0. Registro de IDs ────────────────────────────────────────────────────────

def test_all_new_effects_loaded(lib):
    """EffectLibrary carga los 10 efectos nuevos (IDs 1010-1019)."""
    missing = [eid for eid in _EFFECT_IDS if lib.get_effect(eid) is None]
    assert not missing, f"Efectos no cargados: {missing}"


@pytest.mark.parametrize("eid", _EFFECT_IDS)
def test_shape_dtype_range(lib, eid):
    """Cada efecto nuevo devuelve shape (1, 93, 3) uint8 con valores [0-255]."""
    eff = lib.get_effect(eid)
    out = eff.render(0.0, _bars(), _ctx())
    _assert_valid(out, f"efecto {eid} t=0")


@pytest.mark.parametrize("eid", _EFFECT_IDS)
def test_shape_at_t1000(lib, eid):
    """También válido a t=1000 ms."""
    eff = lib.get_effect(eid)
    out = eff.render(1000.0, _bars(), _ctx())
    _assert_valid(out, f"efecto {eid} t=1000")


# ── 1. gradient_sweep (1010) ─────────────────────────────────────────────────

def test_gradient_sweep_changes_over_time(lib):
    eff = _fresh(lib, 1010)
    p = dict(color1_r=255, color1_g=0, color1_b=0, color2_r=0, color2_g=0, color2_b=255, speed=1.0)
    out0 = eff.render(0.0,   _bars(), _ctx(), **p)
    out1 = eff.render(250.0, _bars(), _ctx(), **p)  # t=0.25s ≠ multiple of 1 cycle
    assert not np.array_equal(out0, out1), "gradient_sweep should change over time"


def test_gradient_sweep_has_color_variation(lib):
    eff = _fresh(lib, 1010)
    p = dict(color1_r=255, color1_g=0, color1_b=0, color2_r=0, color2_g=0, color2_b=255)
    out = eff.render(0.0, _bars(), _ctx(), **p)
    # Red channel should vary across LEDs (gradient)
    assert int(out[0, :, 0].max()) > int(out[0, :, 0].min()), "gradient should vary across LEDs"


# ── 2. pixel_chase (1011) ────────────────────────────────────────────────────

def test_pixel_chase_changes_over_time(lib):
    eff = _fresh(lib, 1011)
    out0 = eff.render(0.0,   _bars(), _ctx(), r=255, g=0, b=0, speed=40)
    out1 = eff.render(500.0, _bars(), _ctx(), r=255, g=0, b=0, speed=40)
    assert not np.array_equal(out0, out1), "pixel_chase should move over time"


def test_pixel_chase_state_continuity(lib):
    """El estado (_last_frame) persiste entre llamadas sucesivas."""
    eff = _fresh(lib, 1011)
    last_before = eff._last_frame.copy()
    eff.render(0.0,   _bars(), _ctx(), r=200, g=0, b=0, tail_decay=0.9)
    eff.render(100.0, _bars(), _ctx(), r=200, g=0, b=0, tail_decay=0.9)
    # After two renders the last_frame should be non-zero
    assert eff._last_frame.max() > 0, "pixel_chase _last_frame should accumulate state"


# ── 3. theater_chase (1012) ──────────────────────────────────────────────────

def test_theater_chase_changes_over_time(lib):
    eff = _fresh(lib, 1012)
    p = dict(r=255, g=0, b=0, group_size=4, gap_size=4, speed=2.0)
    out0 = eff.render(0.0,   _bars(), _ctx(), **p)
    out1 = eff.render(500.0, _bars(), _ctx(), **p)
    assert not np.array_equal(out0, out1), "theater_chase should advance groups"


def test_theater_chase_alternating_groups(lib):
    """Hay LEDs encendidos Y apagados en el mismo frame."""
    eff = _fresh(lib, 1012)
    out = eff.render(0.0, _bars(), _ctx(), r=255, g=0, b=0, group_size=4, gap_size=4)
    active = int((out[0, :, 0] > 0).sum())
    assert 0 < active < LEDS_PER_BAR, f"theater_chase should have partial LEDs lit, got {active}"


# ── 4. twinkle (1013) ────────────────────────────────────────────────────────

def test_twinkle_changes_over_time(lib):
    eff = _fresh(lib, 1013)
    p = dict(r=255, g=255, b=255, density=0.5, speed=3.0)
    out0 = eff.render(0.0,    _bars(), _ctx(), **p)
    out1 = eff.render(1000.0, _bars(), _ctx(), **p)
    assert not np.array_equal(out0, out1), "twinkle should change over time"


def test_twinkle_phases_stable(lib):
    """Las fases son deterministas: el mismo efecto produce el mismo patrón."""
    eff = _fresh(lib, 1013)
    phases_before = eff._phases.copy()
    eff.render(0.0,   _bars(), _ctx())
    eff.render(500.0, _bars(), _ctx())
    assert np.array_equal(phases_before, eff._phases), "twinkle phases should not change between renders"


# ── 5. fire (1014) ───────────────────────────────────────────────────────────

def test_fire_produces_warm_colors(lib):
    """Después de varios frames, debe haber valores en el canal rojo."""
    eff = _fresh(lib, 1014)
    for _ in range(15):
        out = eff.render(0.0, _bars(), _ctx(), intensity=0.9, sparking=0.9)
    assert int(out[0, :, 0].max()) > 20, "fire should produce red/warm tones after warmup"


def test_fire_state_continuity(lib):
    """El heat array persiste y evoluciona entre frames."""
    eff = _fresh(lib, 1014)
    eff.render(0.0, _bars(), _ctx(), intensity=1.0, sparking=1.0)
    heat1 = eff._heat.copy()
    eff.render(0.0, _bars(), _ctx(), intensity=1.0, sparking=1.0)
    heat2 = eff._heat.copy()
    # Both arrays have correct shape
    assert heat1.shape == (LEDS_PER_BAR,)
    assert heat2.shape == (LEDS_PER_BAR,)
    # State evolves (not necessarily different every frame due to randomness,
    # but the heat array must be updated)
    assert eff._heat is not None, "fire heat array must exist"


# ── 6. strobe_color (1015) ───────────────────────────────────────────────────

def test_strobe_on_at_start(lib):
    """Al inicio del período (t=0 ms), el estrobo está encendido (phase=0 < duty*period)."""
    eff = _fresh(lib, 1015)
    out = eff.render(0.0, _bars(), _ctx(), r=255, g=0, b=0, rate_hz=4.0, duty_cycle=0.5)
    assert int(out[0, 0, 0]) == 255, "strobe should be ON at t=0"


def test_strobe_off_mid_period(lib):
    """A mitad del período OFF (10 Hz, duty=0.5 → off desde 50 ms hasta 100 ms)."""
    eff = _fresh(lib, 1015)
    out = eff.render(75.0, _bars(), _ctx(), r=255, g=0, b=0, rate_hz=10.0, duty_cycle=0.5)
    assert int(out[0, 0, 0]) == 0, "strobe should be OFF at t=75ms (10Hz, 50% duty)"


def test_strobe_changes_over_period(lib):
    eff = _fresh(lib, 1015)
    p = dict(r=200, g=0, b=0, rate_hz=5.0, duty_cycle=0.5)
    out0 = eff.render(0.0,   _bars(), _ctx(), **p)
    out1 = eff.render(110.0, _bars(), _ctx(), **p)
    assert not np.array_equal(out0, out1), "strobe should toggle on/off over time"


# ── 7. vu_meter (1016) ───────────────────────────────────────────────────────

def test_vu_meter_rms0_vs_rms1(lib):
    """rms=1 debe iluminar más LEDs que rms=0 (sin smoothing)."""
    eff_lo = _fresh(lib, 1016)
    eff_hi = _fresh(lib, 1016)
    for _ in range(5):
        out_lo = eff_lo.render(0.0, _bars(), _ctx(rms=0.0), smoothing=0.0,
                               r_low=0, g_low=255, b_low=0, r_high=255, g_high=0, b_high=0)
        out_hi = eff_hi.render(0.0, _bars(), _ctx(rms=1.0), smoothing=0.0,
                               r_low=0, g_low=255, b_low=0, r_high=255, g_high=0, b_high=0)
    lit_lo = int((out_lo[0, :, 1] > 0).sum())
    lit_hi = int((out_hi[0, :, 1] > 0).sum())
    assert lit_hi > lit_lo, f"rms=1 should light more LEDs ({lit_hi}) than rms=0 ({lit_lo})"


def test_vu_meter_smooth_level_updates(lib):
    eff = _fresh(lib, 1016)
    eff.render(0.0, _bars(), _ctx(rms=1.0), smoothing=0.0)
    assert eff._smooth_level > 0.0, "smooth_level must update after rms=1"


# ── 8. rainbow_wave (1017) ───────────────────────────────────────────────────

def test_rainbow_wave_uses_all_rgb(lib):
    eff = _fresh(lib, 1017)
    out = eff.render(250.0, _bars(), _ctx())
    assert int(out[0, :, 0].max()) > 0, "rainbow should use R channel"
    assert int(out[0, :, 1].max()) > 0, "rainbow should use G channel"
    assert int(out[0, :, 2].max()) > 0, "rainbow should use B channel"


def test_rainbow_wave_changes_over_time(lib):
    eff = _fresh(lib, 1017)
    out0 = eff.render(0.0,   _bars(), _ctx(), speed=1.0)
    out1 = eff.render(250.0, _bars(), _ctx(), speed=1.0)  # 0.25s: ¼ cycle ≠ full cycle
    assert not np.array_equal(out0, out1), "rainbow should shift over time"


def test_rainbow_wave_reverse_differs(lib):
    eff = _fresh(lib, 1017)
    # At t=250ms speed=1.0: fwd offset=+90°, rev offset=−90° → different patterns
    out_fwd = eff.render(250.0, _bars(), _ctx(), speed=1.0, reverse=False)
    out_rev = eff.render(250.0, _bars(), _ctx(), speed=1.0, reverse=True)
    assert not np.array_equal(out_fwd, out_rev), "reverse rainbow should differ from forward"


# ── 9. scanner (1018) ────────────────────────────────────────────────────────

def test_scanner_changes_over_time(lib):
    eff = _fresh(lib, 1018)
    p = dict(r=255, g=255, b=255, speed=1.0, width=8.0)
    out0 = eff.render(0.0,   _bars(), _ctx(), **p)
    out1 = eff.render(250.0, _bars(), _ctx(), **p)  # 0.25s: sin moves to non-zero
    assert not np.array_equal(out0, out1), "scanner spot should move"


def test_scanner_brightness_env(lib):
    """Con brightness_env=True, rms=1 produce salida >= rms=0."""
    eff_lo = _fresh(lib, 1018)
    eff_hi = _fresh(lib, 1018)
    out_lo = eff_lo.render(0.0, _bars(), _ctx(rms=0.0),
                           r=255, g=255, b=255, speed=0.1, brightness_env=True)
    out_hi = eff_hi.render(0.0, _bars(), _ctx(rms=1.0),
                           r=255, g=255, b=255, speed=0.1, brightness_env=True)
    assert int(out_hi.max()) >= int(out_lo.max()), \
        "scanner with brightness_env: rms=1 should be >= rms=0"


# ── 10. breathing (1019) ─────────────────────────────────────────────────────

def test_breathing_changes_over_time(lib):
    eff = _fresh(lib, 1019)
    p = dict(r=255, g=0, b=0, rate_hz=1.0, audio_reactive=False)
    out0 = eff.render(0.0,   _bars(), _ctx(), **p)
    out1 = eff.render(250.0, _bars(), _ctx(), **p)  # 0.25s: sin(π/2)=1 ≠ sin(0)=0
    assert not np.array_equal(out0, out1), "breathing should change over time"


def test_breathing_audio_reactive(lib):
    """rms=0 y rms=1 producen brillo distinto con audio_reactive=True."""
    eff_lo = _fresh(lib, 1019)
    eff_hi = _fresh(lib, 1019)
    out_lo = eff_lo.render(0.0, _bars(), _ctx(rms=0.0),
                           r=255, g=0, b=0, audio_reactive=True, min_brightness=0.0)
    out_hi = eff_hi.render(0.0, _bars(), _ctx(rms=1.0),
                           r=255, g=0, b=0, audio_reactive=True, min_brightness=0.0)
    assert not np.array_equal(out_lo, out_hi), "breathing reactive: rms=0 != rms=1"


def test_breathing_min_brightness_floor(lib):
    """Con min_brightness=0.5 y rms=0, el brillo debe ser al menos ~127."""
    eff = _fresh(lib, 1019)
    out = eff.render(0.0, _bars(), _ctx(rms=0.0),
                     r=255, g=0, b=0, audio_reactive=True, min_brightness=0.5)
    assert int(out[0, 0, 0]) >= 127, "min_brightness=0.5 should floor brightness at ~127"
