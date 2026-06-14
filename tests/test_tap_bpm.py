"""
test_tap_bpm.py — Tests para la funcionalidad de tap tempo (M1).
"""
from __future__ import annotations
import time
import pytest
from server.tempo_sync import TempoSyncService


def test_four_taps_500ms_gives_120bpm():
    """4 taps con intervalos de 500 ms → BPM ≈ 120 (±1 BPM)."""
    ts = TempoSyncService()
    t = 0.0
    interval = 0.500  # 120 BPM
    for _ in range(4):
        ts.tap(t)
        t += interval

    result = ts.tap(t)
    assert result["ready"] is True
    assert result["bpm"] is not None
    assert abs(result["bpm"] - 120.0) <= 1.0, f"BPM esperado ~120, obtenido {result['bpm']}"


def test_three_taps_not_ready():
    """3 taps → ready: False, bpm no se actualiza."""
    ts = TempoSyncService()
    t = 0.0
    for _ in range(3):
        result = ts.tap(t)
        t += 0.5
    assert result["ready"] is False
    assert result["bpm"] is None
    assert ts.mode != "manual"


def test_eight_taps_noisy_intervals():
    """8 taps con intervalos ruidosos (±20 ms) → mediana robusta, BPM ≈ 100 (±3 BPM)."""
    import random
    random.seed(42)
    ts = TempoSyncService()
    target_interval = 0.600  # 100 BPM
    t = 0.0
    result = None
    for _ in range(8):
        result = ts.tap(t)
        jitter = random.uniform(-0.020, 0.020)
        t += target_interval + jitter

    assert result is not None
    assert result["ready"] is True
    assert result["bpm"] is not None
    assert abs(result["bpm"] - 100.0) <= 3.0, f"BPM esperado ~100, obtenido {result['bpm']}"


def test_tap_resets_on_long_gap():
    """Gap > 3 s entre taps → se reinicia el buffer (nuevo ritmo)."""
    ts = TempoSyncService()
    # 3 taps a 120 BPM
    for i in range(3):
        ts.tap(i * 0.5)
    # gap grande
    result = ts.tap(10.0)  # >3 s → reset
    assert result["taps"] == 1
    assert result["ready"] is False


def test_tap_sets_mode_manual():
    """Tras 4+ taps, el modo se actualiza a 'manual'."""
    ts = TempoSyncService()
    t = 0.0
    for _ in range(5):
        ts.tap(t)
        t += 0.5
    assert ts.mode == "manual"
    assert ts.bpm > 0
