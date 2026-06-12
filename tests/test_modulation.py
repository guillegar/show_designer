"""
test_modulation.py — Tests de A1 (modulación de parámetros por audio).
"""
import pytest
import numpy as np

from src.core.timeline_model import Clip
from src.core.modulation import ParamLink, ModulationStage, _read_signal_from_context, _apply_curve


class TestParamLink:
    """ParamLink serialización."""

    def test_to_dict(self):
        link = ParamLink(param="brightness", source="rms", gain=2.0, offset=0.1,
                        curve="exp", min_v=0.0, max_v=1.0)
        d = link.to_dict()
        assert d['param'] == "brightness"
        assert d['source'] == "rms"
        assert d['gain'] == 2.0

    def test_from_dict(self):
        d = {'param': 'speed', 'source': 'flux', 'gain': 1.5, 'offset': 0.0,
             'curve': 'log', 'min_v': 0.2, 'max_v': 0.9}
        link = ParamLink.from_dict(d)
        assert link.param == 'speed'
        assert link.source == 'flux'
        assert link.gain == 1.5

    def test_roundtrip(self):
        original = ParamLink(param="hue", source="mel_bands.3", gain=0.5, offset=180,
                            curve="linear", min_v=-180, max_v=180)
        d = original.to_dict()
        restored = ParamLink.from_dict(d)
        assert restored.param == original.param
        assert restored.source == original.source
        assert restored.gain == original.gain


class TestCurveTransformation:
    """Transformaciones de curva."""

    def test_linear(self):
        assert _apply_curve(0.5, 'linear') == pytest.approx(0.5)
        assert _apply_curve(0.0, 'linear') == pytest.approx(0.0)
        assert _apply_curve(1.0, 'linear') == pytest.approx(1.0)

    def test_exp(self):
        result = _apply_curve(0.5, 'exp')
        assert result == pytest.approx(0.25)  # 0.5^2

    def test_log(self):
        result = _apply_curve(0.25, 'log')
        assert result == pytest.approx(0.5)  # sqrt(0.25)

    def test_invert(self):
        assert _apply_curve(0.3, 'invert') == pytest.approx(0.7)
        assert _apply_curve(0.0, 'invert') == pytest.approx(1.0)

    def test_clamp_to_0_1(self):
        """Las curvas clampean a 0..1."""
        assert _apply_curve(-0.5, 'linear') == pytest.approx(0.0)
        assert _apply_curve(1.5, 'linear') == pytest.approx(1.0)


class TestReadSignal:
    """Lectura de señales del audio_context."""

    def test_scalar_signal(self):
        actx = {'norm': {'rms': 0.6}}
        val = _read_signal_from_context('rms', actx)
        assert val == pytest.approx(0.6)

    def test_vector_signal_with_index(self):
        actx = {'norm': {'mel_bands': np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)}}
        val = _read_signal_from_context('mel_bands.2', actx)
        assert val == pytest.approx(0.3)

    def test_missing_signal(self):
        actx = {'norm': {'rms': 0.5}}
        val = _read_signal_from_context('flux', actx)
        assert val is None

    def test_invalid_index(self):
        actx = {'norm': {'mel_bands': np.array([0.1, 0.2], dtype=np.float32)}}
        val = _read_signal_from_context('mel_bands.10', actx)
        assert val is None

    def test_no_norm_context(self):
        actx = {}  # sin 'norm'
        val = _read_signal_from_context('rms', actx)
        assert val is None


class TestModulationStage:
    """Stage de modulación en el pipeline."""

    def test_fast_path_no_links(self):
        """Sin links: devuelve params SIN copiar (fast path)."""
        stage = ModulationStage()
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0)
        params = {'brightness': 0.5}
        result = stage.apply(params, clip, 0, {})
        assert result is params  # identidad: no copia

    def test_apply_single_link(self):
        """Aplica un link: signal * gain + offset, clampead."""
        stage = ModulationStage()
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0,
                   param_links=[{'param': 'brightness', 'source': 'rms',
                                'gain': 2.0, 'offset': 0.0, 'curve': 'linear',
                                'min_v': 0.0, 'max_v': 1.0}])
        params = {'brightness': 0.3, 'speed': 0.5}
        actx = {'norm': {'rms': 0.4}}
        result = stage.apply(params, clip, 0, actx)
        assert result is not params  # copia hecha
        assert result['brightness'] == pytest.approx(0.8)  # 0.4 * 2.0
        assert result['speed'] == 0.5  # sin tocar

    def test_apply_multiple_links(self):
        """Aplica varios links a parámetros distintos."""
        stage = ModulationStage()
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0,
                   param_links=[
                       {'param': 'brightness', 'source': 'rms', 'gain': 1.0, 'offset': 0.0,
                        'curve': 'linear', 'min_v': 0.0, 'max_v': 1.0},
                       {'param': 'speed', 'source': 'flux', 'gain': 0.5, 'offset': 0.5,
                        'curve': 'linear', 'min_v': 0.0, 'max_v': 1.0},
                   ])
        params = {'brightness': 0.1, 'speed': 0.1}
        actx = {'norm': {'rms': 0.7, 'flux': 0.2}}
        result = stage.apply(params, clip, 0, actx)
        assert result['brightness'] == pytest.approx(0.7)  # 0.7 * 1.0 + 0.0
        assert result['speed'] == pytest.approx(0.6)  # 0.2 * 0.5 + 0.5

    def test_clamp_result(self):
        """Los resultados se clampean a [min_v, max_v]."""
        stage = ModulationStage()
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0,
                   param_links=[{'param': 'hue', 'source': 'rms', 'gain': 1000.0,
                                'offset': 0.0, 'curve': 'linear',
                                'min_v': -180.0, 'max_v': 180.0}])
        params = {'hue': 0.0}
        actx = {'norm': {'rms': 0.5}}
        result = stage.apply(params, clip, 0, actx)
        assert result['hue'] == pytest.approx(180.0)  # clamped at max

    def test_missing_signal_noop(self):
        """Señal ausente: no toca el param (no-op)."""
        stage = ModulationStage()
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0,
                   param_links=[{'param': 'brightness', 'source': 'nonexistent',
                                'gain': 1.0, 'offset': 0.0, 'curve': 'linear',
                                'min_v': 0.0, 'max_v': 1.0}])
        params = {'brightness': 0.3}
        actx = {'norm': {'rms': 0.5}}
        result = stage.apply(params, clip, 0, actx)
        assert result['brightness'] == 0.3  # sin cambiar

    def test_curve_applied(self):
        """Las transformaciones de curva se aplican correctamente."""
        stage = ModulationStage()
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0,
                   param_links=[{'param': 'brightness', 'source': 'rms',
                                'gain': 1.0, 'offset': 0.0, 'curve': 'exp',
                                'min_v': 0.0, 'max_v': 1.0}])
        params = {'brightness': 0.0}
        actx = {'norm': {'rms': 0.5}}
        result = stage.apply(params, clip, 0, actx)
        assert result['brightness'] == pytest.approx(0.25)  # 0.5^2

    def test_vector_signal_with_index(self):
        """Modular con un índice de vector (ej. mel_bands.3)."""
        stage = ModulationStage()
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0,
                   param_links=[{'param': 'bass_level', 'source': 'mel_bands.1',
                                'gain': 1.0, 'offset': 0.0, 'curve': 'linear',
                                'min_v': 0.0, 'max_v': 1.0}])
        params = {'bass_level': 0.0}
        mel_arr = np.array([0.1, 0.6, 0.3, 0.2], dtype=np.float32)
        actx = {'norm': {'mel_bands': mel_arr}}
        result = stage.apply(params, clip, 0, actx)
        assert result['bass_level'] == pytest.approx(0.6)

    def test_broken_link_continues(self):
        """Un link roto no tumba el stage."""
        stage = ModulationStage()
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0,
                   param_links=[
                       {'param': 'brightness', 'source': 'rms', 'gain': 'INVALID',  # ← TypeError
                        'offset': 0.0, 'curve': 'linear', 'min_v': 0.0, 'max_v': 1.0},
                       {'param': 'speed', 'source': 'flux', 'gain': 1.0, 'offset': 0.0,
                        'curve': 'linear', 'min_v': 0.0, 'max_v': 1.0},
                   ])
        params = {'brightness': 0.0, 'speed': 0.0}
        actx = {'norm': {'flux': 0.5}}
        result = stage.apply(params, clip, 0, actx)
        assert result['brightness'] == 0.0  # sin cambiar (link roto)
        assert result['speed'] == pytest.approx(0.5)  # el segundo link sí aplica


class TestClipPersistence:
    """Persistencia de param_links en Clip."""

    def test_to_dict_includes_links(self):
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0,
                   param_links=[{'param': 'brightness', 'source': 'rms'}])
        d = clip.to_dict()
        assert 'param_links' in d
        assert len(d['param_links']) == 1
        assert d['param_links'][0]['param'] == 'brightness'

    def test_from_dict_restores_links(self):
        d = {
            'track': 0, 'start_ms': 0, 'end_ms': 1000, 'effect_id': 0,
            'param_links': [{'param': 'speed', 'source': 'flux', 'gain': 2.0,
                            'offset': 0.0, 'curve': 'linear', 'min_v': 0.0, 'max_v': 1.0}]
        }
        clip = Clip.from_dict(d)
        assert len(clip.param_links) == 1
        assert clip.param_links[0]['param'] == 'speed'
        assert clip.param_links[0]['gain'] == 2.0

    def test_roundtrip_links(self):
        """to_dict + from_dict preserva links."""
        original = Clip(track=2, start_ms=100, end_ms=2000, effect_id=5,
                       param_links=[
                           {'param': 'brightness', 'source': 'rms', 'gain': 1.5},
                           {'param': 'hue', 'source': 'centroid', 'gain': 0.01},
                       ])
        d = original.to_dict()
        restored = Clip.from_dict(d)
        assert len(restored.param_links) == 2
        assert restored.param_links[0]['source'] == 'rms'
        assert restored.param_links[1]['source'] == 'centroid'

    def test_empty_links_default(self):
        """Sin param_links explícito, from_dict usa []."""
        d = {'track': 0, 'start_ms': 0, 'end_ms': 1000, 'effect_id': 0}
        clip = Clip.from_dict(d)
        assert clip.param_links == []
