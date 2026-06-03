"""
test_channel_effects.py — Tests para el catálogo ChannelEffect (v1.7 Fase 8).

Cubre:
  - ChannelEffectLibrary: registro, get, by_category, compatible_with_profile
  - Un test por categoría (position/color/intensity/optical/strobe)
  - Invariantes: clamp 0-255, required_channels en output, render determinista
  - Integración con Clip.category y timeline_model
"""
import math
import pytest

from src.core.channel_effects import (
    ChannelEffectLibrary, ChannelEffect, CATEGORIES,
    ChanCircle, ChanFigure8, ChanSway, ChanBeatSnap, ChanPanSweep,
    ChanRainbow, ChanColorFade, ChanColorFlash, ChanWarmCold, ChanColorStrobe,
    ChanPulse, ChanBump, ChanFadeIn, ChanBreath, ChanDimFlash,
    ChanGoboSpin, ChanGoboStep, ChanZoomPulse, ChanFrostPulse,
    ChanStrobeSimple, ChanStrobeRamp, ChanStrobeBeat, ChanStrobeBurst,
    ChanStrobeRandom,
)
from src.core.timeline_model import Clip


# ════════════════════════════════════════════════════════════════
# Fixtures de pytest
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def lib():
    return ChannelEffectLibrary()


@pytest.fixture
def audio_ctx_loud():
    """Contexto de audio con RMS alto (simula beat fuerte)."""
    return {'rms': 0.9, 'flux': 0.8, 'energy': 0.81}


@pytest.fixture
def audio_ctx_silent():
    """Contexto de audio silencioso."""
    return {'rms': 0.0, 'flux': 0.0, 'energy': 0.0}


def _all_in_range(d: dict) -> bool:
    """Verifica que todos los valores están en [0, 255]."""
    return all(isinstance(v, int) and 0 <= v <= 255 for v in d.values())


# ════════════════════════════════════════════════════════════════
# Librería global
# ════════════════════════════════════════════════════════════════

class TestChannelEffectLibrary:
    def test_all_effects_loaded(self, lib):
        assert len(lib.all()) == 24

    def test_get_known(self, lib):
        e = lib.get('pos_circle')
        assert e is not None
        assert e.effect_id == 'pos_circle'

    def test_get_unknown_returns_none(self, lib):
        assert lib.get('no_existe_xxx') is None

    def test_categories_covered(self, lib):
        covered = {e.category for e in lib.all()}
        assert covered == set(CATEGORIES)

    def test_by_category_position(self, lib):
        pos = lib.by_category('position')
        assert len(pos) == 5
        assert all(e.category == 'position' for e in pos)

    def test_by_category_color(self, lib):
        col = lib.by_category('color')
        assert len(col) == 5

    def test_by_category_intensity(self, lib):
        assert len(lib.by_category('intensity')) == 5

    def test_by_category_optical(self, lib):
        assert len(lib.by_category('optical')) == 4

    def test_by_category_strobe(self, lib):
        assert len(lib.by_category('strobe')) == 5

    def test_describe_all(self, lib):
        descs = lib.describe_all()
        assert len(descs) == 24
        required_keys = {'effect_id', 'name', 'category', 'required_channels',
                         'optional_channels', 'default_params'}
        for d in descs:
            assert required_keys == d.keys()

    def test_describe_single(self, lib):
        d = lib.describe('col_rainbow')
        assert d['effect_id'] == 'col_rainbow'
        assert d['category'] == 'color'
        assert 'r' in d['required_channels']

    def test_compatible_with_profile_wash(self, lib):
        """Simula un perfil con canales pan, tilt, dim, r, g, b."""
        class FakeProfile:
            channel_map = {'pan': 0, 'tilt': 2, 'dim': 4, 'r': 9, 'g': 10, 'b': 11}
        compatible = lib.compatible_with_profile(FakeProfile())
        ids = {e.effect_id for e in compatible}
        assert 'pos_circle' in ids
        assert 'col_rainbow' in ids
        assert 'dim_pulse' in ids
        # Gobo spin no debe estar (necesita gobo_rotation)
        assert 'opt_gobo_spin' not in ids

    def test_compatible_with_strobe_only(self, lib):
        """Perfil solo con intensity — solo efectos strobe que pidan intensity."""
        class FakeProfile:
            channel_map = {'intensity': 0, 'speed': 1}
        compatible = lib.compatible_with_profile(FakeProfile())
        assert all(e.category == 'strobe' for e in compatible)


# ════════════════════════════════════════════════════════════════
# Invariantes globales: clamp y required_channels en output
# ════════════════════════════════════════════════════════════════

class TestInvariants:
    def test_all_effects_clamp_output(self, lib):
        """Todos los efectos devuelven valores 0-255."""
        ctx = {'rms': 0.5}
        for e in lib.all():
            result = e.render(t=1.0, audio_context=ctx, params=None)
            assert _all_in_range(result), \
                f"{e.effect_id} produjo valores fuera de rango: {result}"

    def test_all_effects_include_required_channels(self, lib):
        """El resultado incluye al menos los required_channels."""
        ctx = {'rms': 0.5}
        for e in lib.all():
            result = e.render(t=1.0, audio_context=ctx, params=None)
            for ch in e.required_channels:
                assert ch in result, \
                    f"{e.effect_id}: falta canal requerido '{ch}' en {result}"

    def test_render_with_none_audio_context(self, lib):
        """Todos los efectos funcionan sin audio_context."""
        for e in lib.all():
            result = e.render(t=2.0, audio_context=None, params=None)
            assert isinstance(result, dict)
            assert _all_in_range(result)

    def test_render_with_none_params(self, lib):
        """Todos los efectos usan default_params cuando params=None."""
        for e in lib.all():
            result = e.render(t=0.5, audio_context=None, params=None)
            assert isinstance(result, dict)

    def test_render_deterministic_at_t0(self, lib):
        """Efectos sin estado interno son deterministas en t=0."""
        ctx = {'rms': 0.0}
        stateless = [e for e in lib.all()
                     if e.effect_id not in ('col_flash', 'dim_flash', 'str_beat')]
        for e in stateless:
            r1 = e.render(t=0.0, audio_context=ctx, params=None)
            r2 = e.render(t=0.0, audio_context=ctx, params=None)
            assert r1 == r2, f"{e.effect_id}: no es determinista"


# ════════════════════════════════════════════════════════════════
# POSITION (un test por efecto)
# ════════════════════════════════════════════════════════════════

class TestPositionEffects:
    def test_circle_moves(self):
        e = ChanCircle()
        r0 = e.render(t=0.0, audio_context=None, params=None)
        r1 = e.render(t=0.5, audio_context=None, params=None)
        # Pan o tilt deben cambiar entre t=0 y t=0.5
        assert r0 != r1

    def test_circle_center_param(self):
        e = ChanCircle()
        # Con radius=0 debería quedarse fijo en center
        r = e.render(t=1.0, audio_context=None, params={'radius': 0.0, 'center_pan': 0.5, 'center_tilt': 0.5})
        assert r['pan'] == 127 or r['pan'] == 128  # 0.5 * 255

    def test_figure8_different_from_circle(self):
        e_c = ChanCircle()
        e_f = ChanFigure8()
        params = {'speed': 0.3, 'radius': 0.25, 'center_pan': 0.5, 'center_tilt': 0.5}
        r_c = e_c.render(t=0.33, audio_context=None, params=params)
        r_f = e_f.render(t=0.33, audio_context=None, params=params)
        # Pan puede ser igual pero tilt debe diferir (ocho vs círculo)
        assert r_c['tilt'] != r_f['tilt']

    def test_sway_only_pan_changes(self):
        e = ChanSway()
        r0 = e.render(t=0.0, audio_context=None, params=None)
        r1 = e.render(t=1.0, audio_context=None, params=None)
        # Tilt no cambia (mismo center_tilt)
        assert r0['tilt'] == r1['tilt']

    def test_beat_snap_different_slots(self):
        e = ChanBeatSnap()
        params = {'bpm': 120.0, 'beat_div': 1.0, 'range': 0.35,
                  'center_pan': 0.5, 'center_tilt': 0.5}
        r0 = e.render(t=0.0, audio_context=None, params=params)
        r1 = e.render(t=0.5, audio_context=None, params=params)  # siguiente beat
        # Debe haber cambiado (aleatoriamente diferente slot)
        assert r0 != r1

    def test_pan_sweep_full_range(self):
        e = ChanPanSweep()
        params = {'speed': 0.5, 'from_pan': 0.0, 'to_pan': 1.0, 'center_tilt': 0.5}
        values = [e.render(t=t, audio_context=None, params=params)['pan']
                  for t in [0.0, 0.25, 0.5, 0.75, 1.0]]
        # Debe haber variación de pan
        assert max(values) > min(values)


# ════════════════════════════════════════════════════════════════
# COLOR
# ════════════════════════════════════════════════════════════════

class TestColorEffects:
    def test_rainbow_cycles(self):
        e = ChanRainbow()
        r0 = e.render(t=0.0, audio_context=None, params={'speed': 1.0})
        r1 = e.render(t=0.33, audio_context=None, params={'speed': 1.0})
        assert r0 != r1

    def test_color_fade_endpoints(self):
        e = ChanColorFade()
        # En t=0 sin fase, sin=0 → frac=0.5 (punto medio del seno)
        # Lo que importa es que varía
        r0 = e.render(t=0.0, audio_context=None, params={'speed': 1.0, 'color_a': '#ff0000', 'color_b': '#0000ff'})
        r2 = e.render(t=0.5, audio_context=None, params={'speed': 1.0, 'color_a': '#ff0000', 'color_b': '#0000ff'})
        # Debe cambiar
        assert r0 != r2

    def test_color_flash_triggered_by_rms(self):
        e = ChanColorFlash()
        loud = {'rms': 1.0}
        silent = {'rms': 0.0}
        # En silencio con timeout largo → apagado
        r_silent = e.render(t=100.0, audio_context=silent, params={'threshold': 0.5, 'decay': 10.0})
        # Justo después de un flash
        e2 = ChanColorFlash()
        e2.render(t=0.0, audio_context=loud, params={'threshold': 0.5, 'decay': 10.0})
        r_flash = e2.render(t=0.0, audio_context=loud, params={'threshold': 0.5, 'decay': 10.0})
        assert r_flash['r'] > r_silent['r']

    def test_warm_cold_oscillates(self):
        e = ChanWarmCold()
        results = [e.render(t=t, audio_context=None, params={'speed': 0.5})
                   for t in [0.0, 0.5, 1.0, 1.5]]
        reds = [r['r'] for r in results]
        assert max(reds) > min(reds)

    def test_color_strobe_binary(self):
        e = ChanColorStrobe()
        params = {'freq_hz': 10.0, 'color': '#ffffff', 'duty': 0.5}
        # Debe haber tanto frames ON como OFF
        on_count = sum(
            1 for t in [i * 0.01 for i in range(20)]
            if e.render(t=t, audio_context=None, params=params)['r'] > 0
        )
        assert 0 < on_count < 20


# ════════════════════════════════════════════════════════════════
# INTENSITY
# ════════════════════════════════════════════════════════════════

class TestIntensityEffects:
    def test_pulse_range(self):
        e = ChanPulse()
        params = {'speed': 1.0, 'min_dim': 0.0, 'max_dim': 1.0}
        values = [e.render(t=t, audio_context=None, params=params)['dim']
                  for t in [i * 0.1 for i in range(20)]]
        assert min(values) >= 0
        assert max(values) <= 255
        assert max(values) > min(values)

    def test_bump_scales_with_rms(self):
        e = ChanBump()
        loud  = {'rms': 1.0}
        quiet = {'rms': 0.0}
        r_loud  = e.render(t=1.0, audio_context=loud,  params={'gain': 1.5, 'base_dim': 0.0})
        r_quiet = e.render(t=1.0, audio_context=quiet, params={'gain': 1.5, 'base_dim': 0.0})
        assert r_loud['dim'] > r_quiet['dim']

    def test_fade_in_increases(self):
        e = ChanFadeIn()
        params = {'fade_time': 2.0, 'target_dim': 1.0}
        v0 = e.render(t=0.0, audio_context=None, params=params)['dim']
        v1 = e.render(t=1.0, audio_context=None, params=params)['dim']
        v2 = e.render(t=2.0, audio_context=None, params=params)['dim']
        assert v0 <= v1 <= v2

    def test_breath_is_non_negative(self):
        e = ChanBreath()
        for t in [i * 0.1 for i in range(50)]:
            r = e.render(t=t, audio_context=None, params=None)
            assert r['dim'] >= 0

    def test_dim_flash_decays(self):
        e = ChanDimFlash()
        params = {'threshold': 0.5, 'decay': 5.0, 'base_dim': 0.0}
        loud = {'rms': 1.0}
        # Dispara el flash
        e.render(t=0.0, audio_context=loud, params=params)
        r_early = e.render(t=0.1, audio_context={'rms': 0.0}, params=params)
        r_late  = e.render(t=2.0, audio_context={'rms': 0.0}, params=params)
        assert r_early['dim'] > r_late['dim']


# ════════════════════════════════════════════════════════════════
# OPTICAL
# ════════════════════════════════════════════════════════════════

class TestOpticalEffects:
    def test_gobo_spin_advances(self):
        e = ChanGoboSpin()
        r0 = e.render(t=0.0, audio_context=None, params={'speed': 1.0})
        r1 = e.render(t=0.5, audio_context=None, params={'speed': 1.0})
        assert r0['gobo_rotation'] != r1['gobo_rotation']

    def test_gobo_spin_wraps(self):
        e = ChanGoboSpin()
        # No sale de 0-255
        for t in [0.0, 1.0, 100.0]:
            r = e.render(t=t, audio_context=None, params={'speed': 2.0})
            assert 0 <= r['gobo_rotation'] <= 255

    def test_gobo_step_steps(self):
        e = ChanGoboStep()
        params = {'step_time': 1.0, 'num_steps': 4, 'start_pos': 0}
        v0 = e.render(t=0.0, audio_context=None, params=params)['gobo_wheel']
        v1 = e.render(t=1.1, audio_context=None, params=params)['gobo_wheel']
        assert v0 != v1

    def test_zoom_pulse_range(self):
        e = ChanZoomPulse()
        params = {'speed': 0.5, 'min_zoom': 0.0, 'max_zoom': 1.0}
        values = [e.render(t=t, audio_context=None, params=params)['zoom']
                  for t in [i * 0.1 for i in range(30)]]
        assert max(values) > min(values)

    def test_frost_pulse_range(self):
        e = ChanFrostPulse()
        values = [e.render(t=t, audio_context=None, params=None)['frost']
                  for t in [i * 0.1 for i in range(30)]]
        assert max(values) >= 0
        assert max(values) <= 255


# ════════════════════════════════════════════════════════════════
# STROBE
# ════════════════════════════════════════════════════════════════

class TestStrobeEffects:
    def test_strobe_simple_binary(self):
        e = ChanStrobeSimple()
        params = {'freq_hz': 10.0, 'duty': 0.5, 'brightness': 1.0}
        frames = [e.render(t=i * 0.02, audio_context=None, params=params)['intensity']
                  for i in range(50)]
        assert 0 in frames
        assert any(f > 0 for f in frames)

    def test_strobe_ramp_accelerates(self):
        e = ChanStrobeRamp()
        params = {'start_hz': 1.0, 'end_hz': 20.0, 'ramp_time': 2.0, 'brightness': 1.0}
        # Cuenta transiciones en el primer segundo vs el último
        def count_transitions(t_start, t_end, steps=100):
            prev = None
            transitions = 0
            for i in range(steps):
                t = t_start + (t_end - t_start) * i / steps
                v = e.render(t=t, audio_context=None, params=params)['intensity']
                on = v > 0
                if prev is not None and on != prev:
                    transitions += 1
                prev = on
            return transitions

        # Crear una nueva instancia para que no haya estado compartido
        e2 = ChanStrobeRamp()
        early = count_transitions(0.0, 0.5)
        late  = count_transitions(1.5, 2.0)
        assert late >= early  # más transiciones hacia el final

    def test_strobe_beat_reacts_to_audio(self):
        e = ChanStrobeBeat()
        params = {'threshold': 0.5, 'decay': 8.0, 'brightness': 1.0}
        loud = {'rms': 1.0}
        # Primero dispara el beat
        e.render(t=0.0, audio_context=loud, params=params)
        r_near = e.render(t=0.05, audio_context={'rms': 0.0}, params=params)
        r_far  = e.render(t=2.0,  audio_context={'rms': 0.0}, params=params)
        assert r_near['intensity'] > r_far['intensity']

    def test_strobe_burst_ends(self):
        e = ChanStrobeBurst()
        params = {'pulses': 4, 'burst_time': 0.5, 'brightness': 1.0}
        # Después del burst debe estar apagado
        r_after = e.render(t=1.0, audio_context=None, params=params)
        assert r_after['intensity'] == 0

    def test_strobe_random_varies(self):
        e = ChanStrobeRandom()
        params = {'avg_hz': 10.0, 'brightness': 1.0}
        frames = [e.render(t=i * 0.05, audio_context=None, params=params)['intensity']
                  for i in range(40)]
        assert 0 in frames
        assert any(f > 0 for f in frames)


# ════════════════════════════════════════════════════════════════
# Clip.category (Fase 5 timeline_model)
# ════════════════════════════════════════════════════════════════

class TestClipCategory:
    def test_default_category_is_pixel(self):
        c = Clip(track=0, start_ms=0, end_ms=1000, effect_id=5)
        assert c.category == 'pixel'
        assert c.channel_effect_id is None

    def test_channel_clip_creation(self):
        c = Clip(
            track=-1, start_ms=0, end_ms=5000, effect_id=0,
            scope='fixture:mover_wash_L_back',
            category='position',
            channel_effect_id='pos_circle',
            params={'speed': 0.5, 'radius': 0.3},
        )
        assert c.category == 'position'
        assert c.channel_effect_id == 'pos_circle'

    def test_clip_to_dict_roundtrip(self):
        c = Clip(
            track=-1, start_ms=1000, end_ms=6000, effect_id=0,
            scope='fixture:mover_wash_R_back',
            category='color',
            channel_effect_id='col_rainbow',
            params={'speed': 0.3},
        )
        d = c.to_dict()
        c2 = Clip.from_dict(d)
        assert c2.category == 'color'
        assert c2.channel_effect_id == 'col_rainbow'
        assert c2.scope == 'fixture:mover_wash_R_back'

    def test_legacy_clips_keep_pixel_category(self):
        """Clips sin 'category' en el JSON cargan como 'pixel'."""
        d = {
            'track': 3, 'start_ms': 0, 'end_ms': 2000, 'effect_id': 12,
            'scope': 'per_bar', 'params': {}, 'label': '', 'color': '#3a7acc',
            'layer': 0, 'locked': False, 'muted': False,
            # Sin 'category' ni 'channel_effect_id'
        }
        c = Clip.from_dict(d)
        assert c.category == 'pixel'
        assert c.channel_effect_id is None
