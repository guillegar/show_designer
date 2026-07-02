"""
test_automation.py — Tests de A2 (automatización de parámetros).
"""
import math

import pytest

from src.core.automation import AutomationLane, AutomationPoint, AutomationStage, Target, parse_target
from src.core.timeline_model import Clip


class TestAutomationPoint:
    """AutomationPoint serialización."""

    def test_to_dict(self):
        pt = AutomationPoint(t_ms=1000, value=0.5, shape='smooth')
        d = pt.to_dict()
        assert d['t_ms'] == 1000
        assert d['value'] == 0.5
        assert d['shape'] == 'smooth'

    def test_from_dict(self):
        d = {'t_ms': 2000, 'value': 0.75, 'shape': 'hold'}
        pt = AutomationPoint.from_dict(d)
        assert pt.t_ms == 2000
        assert pt.value == 0.75
        assert pt.shape == 'hold'

    def test_default_shape(self):
        d = {'t_ms': 500, 'value': 0.3}
        pt = AutomationPoint.from_dict(d)
        assert pt.shape == 'linear'


class TestParseTarget:
    """Parseador de targets."""

    def test_parse_clip_target(self):
        target = parse_target('clip:abc123def456:brightness')
        assert target is not None
        assert target.target_type == 'clip'
        assert target.uid == 'abc123def456'
        assert target.param == 'brightness'

    def test_parse_track_target(self):
        target = parse_target('track:3:speed')
        assert target is not None
        assert target.target_type == 'track'
        assert target.track_id == 3
        assert target.param == 'speed'

    def test_parse_master_target(self):
        target = parse_target('master:hue')
        assert target is not None
        assert target.target_type == 'master'
        assert target.param == 'hue'

    def test_invalid_target(self):
        assert parse_target('invalid') is None
        assert parse_target('') is None
        assert parse_target(None) is None


class TestAutomationPointInterpolation:
    """Interpolación en AutomationLane."""

    def test_empty_lane(self):
        lane = AutomationLane(uid='lane1', target='clip:id:param', points=[])
        assert lane.value_at(500) is None

    def test_single_point_before(self):
        lane = AutomationLane(uid='lane1', target='clip:id:param',
                            points=[{'t_ms': 1000, 'value': 0.5, 'shape': 'linear'}])
        assert lane.value_at(500) == pytest.approx(0.5)

    def test_single_point_after(self):
        lane = AutomationLane(uid='lane1', target='clip:id:param',
                            points=[{'t_ms': 1000, 'value': 0.5, 'shape': 'linear'}])
        assert lane.value_at(2000) == pytest.approx(0.5)

    def test_linear_interpolation(self):
        lane = AutomationLane(uid='lane1', target='clip:id:param',
                            points=[
                                {'t_ms': 0, 'value': 0.0, 'shape': 'linear'},
                                {'t_ms': 1000, 'value': 1.0, 'shape': 'linear'},
                            ])
        assert lane.value_at(0) == pytest.approx(0.0)
        assert lane.value_at(500) == pytest.approx(0.5)
        assert lane.value_at(1000) == pytest.approx(1.0)

    def test_hold_shape(self):
        """Hold mantiene el valor anterior."""
        lane = AutomationLane(uid='lane1', target='clip:id:param',
                            points=[
                                {'t_ms': 0, 'value': 0.2, 'shape': 'hold'},
                                {'t_ms': 1000, 'value': 0.8, 'shape': 'linear'},
                            ])
        # Entre 0 y 1000, hold hace que se mantenga 0.2
        assert lane.value_at(500) == pytest.approx(0.2)
        # En el punto siguiente se toma su valor
        assert lane.value_at(1000) == pytest.approx(0.8)

    def test_smooth_shape(self):
        """Smooth (cosine) es más suave que lineal."""
        lane = AutomationLane(uid='lane1', target='clip:id:param',
                            points=[
                                {'t_ms': 0, 'value': 0.0, 'shape': 'smooth'},
                                {'t_ms': 1000, 'value': 1.0, 'shape': 'smooth'},
                            ])
        # En la mitad, smooth debería ser ~0.5 pero con easing diferente
        val = lane.value_at(500)
        assert 0.4 < val < 0.6  # suave

    def test_multiple_points_ordered(self):
        """Los puntos se mantienen ordenados."""
        lane = AutomationLane(uid='lane1', target='clip:id:param',
                            points=[
                                {'t_ms': 0, 'value': 0.0, 'shape': 'linear'},
                                {'t_ms': 500, 'value': 0.5, 'shape': 'linear'},
                                {'t_ms': 1000, 'value': 1.0, 'shape': 'linear'},
                            ])
        assert lane.value_at(250) == pytest.approx(0.25)
        assert lane.value_at(750) == pytest.approx(0.75)


class TestAutomationLane:
    """AutomationLane serialización."""

    def test_to_dict(self):
        lane = AutomationLane(uid='lane1', target='clip:id:param',
                            points=[{'t_ms': 1000, 'value': 0.5, 'shape': 'linear'}],
                            enabled=True)
        d = lane.to_dict()
        assert d['uid'] == 'lane1'
        assert d['target'] == 'clip:id:param'
        assert len(d['points']) == 1
        assert d['enabled'] is True

    def test_roundtrip(self):
        original = AutomationLane(uid='lane1', target='track:3:speed',
                                 points=[
                                     {'t_ms': 0, 'value': 0.0, 'shape': 'linear'},
                                     {'t_ms': 1000, 'value': 1.0, 'shape': 'linear'},
                                 ],
                                 enabled=True)
        d = original.to_dict()
        restored = AutomationLane.from_dict(d)
        assert restored.uid == original.uid
        assert restored.target == original.target
        assert len(restored.points) == 2
        assert restored.enabled is True


class TestAutomationStage:
    """Stage de automatización en el pipeline."""

    def test_fast_path_no_lanes(self):
        """Sin lanes: devuelve params sin copiar."""
        stage = AutomationStage(get_automation_lanes=lambda: [])
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0)
        params = {'brightness': 0.3}
        result = stage.apply(params, clip, 500, {})
        assert result is params  # identidad

    def test_apply_clip_lane(self):
        """Aplica una lane que target esta clip."""
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0)
        clip.uid = 'clip_abc'
        lane = AutomationLane(uid='lane1', target=f'clip:{clip.uid}:brightness',
                            points=[
                                {'t_ms': 0, 'value': 0.0, 'shape': 'linear'},
                                {'t_ms': 1000, 'value': 1.0, 'shape': 'linear'},
                            ])
        stage = AutomationStage(get_automation_lanes=lambda: [lane])
        params = {'brightness': 0.5}  # será sobrescrito por la lane
        result = stage.apply(params, clip, 500, {})
        assert result['brightness'] == pytest.approx(0.5)

    def test_apply_track_lane(self):
        """Aplica una lane que target el track."""
        clip = Clip(track=2, start_ms=0, end_ms=1000, effect_id=0)
        lane = AutomationLane(uid='lane1', target='track:2:speed',
                            points=[
                                {'t_ms': 0, 'value': 0.2, 'shape': 'linear'},
                                {'t_ms': 1000, 'value': 0.8, 'shape': 'linear'},
                            ])
        stage = AutomationStage(get_automation_lanes=lambda: [lane])
        params = {'speed': 0.5}
        result = stage.apply(params, clip, 750, {})
        # Interpolación lineal: 0.2 + (0.8-0.2)*0.75 = 0.2 + 0.45 = 0.65
        assert result['speed'] == pytest.approx(0.65)

    def test_disabled_lane_noop(self):
        """Una lane disabled no aplica."""
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0)
        clip.uid = 'clip_abc'
        lane = AutomationLane(uid='lane1', target=f'clip:{clip.uid}:brightness',
                            points=[{'t_ms': 500, 'value': 1.0, 'shape': 'linear'}],
                            enabled=False)
        stage = AutomationStage(get_automation_lanes=lambda: [lane])
        params = {'brightness': 0.3}
        result = stage.apply(params, clip, 500, {})
        assert result['brightness'] == 0.3  # sin cambiar

    def test_multiple_lanes(self):
        """Múltiples lanes aplican a parámetros distintos."""
        clip = Clip(track=1, start_ms=0, end_ms=1000, effect_id=0)
        clip.uid = 'clip_xyz'
        lanes = [
            AutomationLane(uid='lane1', target=f'clip:{clip.uid}:brightness',
                          points=[{'t_ms': 500, 'value': 0.8, 'shape': 'linear'}]),
            AutomationLane(uid='lane2', target='track:1:speed',
                          points=[{'t_ms': 500, 'value': 0.3, 'shape': 'linear'}]),
        ]
        stage = AutomationStage(get_automation_lanes=lambda: lanes)
        params = {'brightness': 0.0, 'speed': 0.0}
        result = stage.apply(params, clip, 500, {})
        assert result['brightness'] == pytest.approx(0.8)
        assert result['speed'] == pytest.approx(0.3)

    def test_lane_not_applicable(self):
        """Una lane que no aplica a este clip no toca params."""
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0)
        clip.uid = 'clip_abc'
        lane = AutomationLane(uid='lane1', target='clip:other_clip_id:brightness',
                            points=[{'t_ms': 500, 'value': 1.0, 'shape': 'linear'}])
        stage = AutomationStage(get_automation_lanes=lambda: [lane])
        params = {'brightness': 0.3}
        result = stage.apply(params, clip, 500, {})
        assert result['brightness'] == 0.3  # sin cambiar

    def test_lane_no_points_at_time(self):
        """Lane con puntos pero value_at devuelve None → no aplica."""
        clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0)
        clip.uid = 'clip_abc'
        lane = AutomationLane(uid='lane1', target=f'clip:{clip.uid}:brightness',
                            points=[])  # empty
        stage = AutomationStage(get_automation_lanes=lambda: [lane])
        params = {'brightness': 0.5}
        result = stage.apply(params, clip, 500, {})
        assert result['brightness'] == 0.5  # sin cambiar
