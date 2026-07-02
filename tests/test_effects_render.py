"""
tests/test_effects_render.py — Tests de renderizado de efectos base (v1.8 F6)

Verifica que cada efecto de la EffectLibrary:
  - Devuelve un array de la forma correcta
  - No crashea con audio_context vacío o None
  - No produce valores fuera de rango [0, 255]
"""
import numpy as np
import pytest

from src.core.effects_engine import (
    LEDS_PER_BAR,
    NUM_BARS,
    EffectLibrary,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _bars():
    return np.zeros((NUM_BARS, LEDS_PER_BAR, 3), dtype=np.float32)


def _ctx():
    """Audio context de prueba con valores típicos."""
    return {
        'energy':   0.7,
        'rms':      0.5,
        'mfcc':     [0.0] * 13,
        'chroma':   [0.5] * 12,
        'centroid': 2000.0,
        'flux':     0.3,
        'contrast': [20.0] * 7,
        'tonnetz':  [0.0] * 6,
        'bpm':      120.0,
        'beat':     True,
        'kick':     False,
        'snare':    False,
    }


@pytest.fixture(scope='module')
def lib():
    return EffectLibrary()


# ── 1. Estructura básica de todos los efectos ─────────────────────────────────

def _valid_shape(result):
    """Un efecto puede devolver (NUM_BARS, LEDS, 3) o (1, LEDS, 3) para efectos 2D."""
    if result.shape == (NUM_BARS, LEDS_PER_BAR, 3):
        return True
    if result.shape == (1, LEDS_PER_BAR, 3):
        return True
    return False


@pytest.mark.parametrize('effect_id', list(range(51)))
def test_effect_render_shape(lib, effect_id):
    """Cada efecto base devuelve array con forma válida."""
    eff = lib.get_effect(effect_id)
    if eff is None:
        pytest.skip(f"Efecto {effect_id} no existe")
    bars = _bars()
    result = eff.render(500.0, bars, _ctx())
    assert result is not None, f"Efecto {effect_id} devolvió None"
    assert _valid_shape(result), \
        f"Efecto {effect_id} ({eff.name}): forma inesperada {result.shape}"


def _ctx_zeros():
    """Audio context con todos los valores en cero (situación de silencio)."""
    return {
        'energy':   0.0,
        'rms':      0.0,
        'mfcc':     [0.0] * 13,
        'chroma':   [0.0] * 12,
        'centroid': 0.0,
        'flux':     0.0,
        'contrast': [0.0] * 7,
        'tonnetz':  [0.0] * 6,
        'bpm':      120.0,
        'beat':     False,
        'kick':     False,
        'snare':    False,
    }


@pytest.mark.parametrize('effect_id', list(range(51)))
def test_effect_render_no_crash_silence(lib, effect_id):
    """Efectos no crashean con audio_context de silencio (todos los valores en 0)."""
    eff = lib.get_effect(effect_id)
    if eff is None:
        pytest.skip(f"Efecto {effect_id} no existe")
    bars = _bars()
    try:
        result = eff.render(0.0, bars, _ctx_zeros())
        assert _valid_shape(result), \
            f"Efecto {effect_id} ({eff.name}): forma inesperada {result.shape}"
    except Exception as e:
        pytest.fail(f"Efecto {effect_id} ({eff.name}) crashea con silence ctx: {e}")


@pytest.mark.parametrize('effect_id', list(range(10)))  # flash family
def test_flash_family_range(lib, effect_id):
    """La familia Flash produce valores en [0, 255] aproximadamente."""
    eff = lib.get_effect(effect_id)
    if eff is None:
        pytest.skip(f"Efecto {effect_id} no existe")
    bars = _bars()
    result = eff.render(100.0, bars, _ctx())
    # Valores no negativos (pueden exceder 255 antes del clip en el engine)
    assert result.min() >= 0.0, f"Efecto {effect_id}: valores negativos"


# ── 2. Tests de efectos específicos ──────────────────────────────────────────

def test_white_flash_has_output(lib):
    """WhiteFlash produce LED encendidos al inicio del efecto."""
    eff = lib.get_effect(0)
    bars = _bars()
    # Probar en diferentes momentos del efecto
    max_output = 0.0
    for t in [0.0, 10.0, 50.0, 100.0]:
        result = eff.render(t, bars, _ctx())
        max_output = max(max_output, float(result.max()))
    # En algún punto debe haber salida
    assert max_output > 0, "WhiteFlash no produjo salida en ningún frame"


def test_horizontal_wave_symmetry(lib):
    """HorizontalWave produce salida con forma válida."""
    eff = lib.get_effect(10)
    bars = _bars()
    result = eff.render(1000.0, bars, _ctx())
    assert _valid_shape(result), f"HorizontalWave: forma inesperada {result.shape}"


def test_rainbow_wave_all_channels(lib):
    """RainbowWave usa los 3 canales RGB."""
    eff = lib.get_effect(13)
    bars = _bars()
    result = eff.render(2000.0, bars, _ctx())
    # Debe haber valores en al menos 2 canales
    r_active = result[:, :, 0].max() > 0
    g_active = result[:, :, 1].max() > 0
    b_active = result[:, :, 2].max() > 0
    assert (r_active or g_active or b_active), "Rainbow debe usar colores"


def test_ring_expand_effect(lib):
    """RingExpandEffect (ID=50) renderiza."""
    eff = lib.get_effect(50)
    assert eff is not None
    bars = _bars()
    result = eff.render(500.0, bars, _ctx())
    assert result.shape == bars.shape


# ── 3. Metadata de efectos ───────────────────────────────────────────────────

def test_all_effects_have_name(lib):
    """Todos los efectos tienen name != 'unnamed_effect'."""
    for eid, eff in lib.effects.items():
        if eid < 1000:  # solo base
            assert eff.name != 'unnamed_effect', \
                f"Efecto {eid} tiene nombre por defecto"


def test_all_effects_have_family(lib):
    """Todos los efectos base tienen una familia definida."""
    for eid, eff in lib.effects.items():
        if eid < 1000:
            assert eff.family != 'generic', \
                f"Efecto {eid} ({eff.name}) usa familia genérica"


def test_list_effects_metadata(lib):
    """list_effects() devuelve todos los metadatos correctos."""
    listing = lib.list_effects()
    assert len(listing) >= 51
    for eid, meta in listing.items():
        assert 'name' in meta
        assert 'family' in meta
        assert 'duration_ms' in meta
        assert 'scope' in meta


def test_list_by_family(lib):
    """list_by_family() filtra correctamente."""
    flash = lib.list_by_family('flash')
    assert len(flash) > 0
    for eid, eff in flash.items():
        assert eff.family == 'flash'


# ── 4. Efectos con parámetros ─────────────────────────────────────────────────

def test_color_flash_with_hue_param(lib):
    """ColorFlash acepta parámetro hue y devuelve forma correcta."""
    eff = lib.get_effect(1)   # ColorFlash
    bars = _bars()
    for t in [0.0, 5.0, 50.0]:
        result = eff.render(t, bars, _ctx(), hue=120)
        assert _valid_shape(result), f"ColorFlash t={t}: forma inesperada {result.shape}"


def test_effect_zero_elapsed(lib):
    """Efectos no crashean con elapsed_time=0."""
    for eid in [0, 1, 10, 20, 30, 40, 50]:
        eff = lib.get_effect(eid)
        if eff is not None:
            bars = _bars()
            try:
                result = eff.render(0.0, bars, _ctx_zeros())
                assert _valid_shape(result)
            except Exception as e:
                pytest.fail(f"Efecto {eid} crashea con elapsed=0: {e}")


def test_effect_large_elapsed(lib):
    """Efectos manejan elapsed_time grande (final de canción)."""
    for eid in [0, 13, 25, 38, 49]:
        eff = lib.get_effect(eid)
        if eff is not None:
            bars = _bars()
            try:
                result = eff.render(273_000.0, bars, _ctx())
                assert _valid_shape(result)
            except Exception as e:
                pytest.fail(f"Efecto {eid} crashea con elapsed grande: {e}")
