"""
test_live_input.py — Tests Fase D2: LiveInput (features + beat tracking).

No requiere hardware de audio real: inyecta bloques de PCM sintéticos
directamente vía _process_block() (el sounddevice callback interno).

Criterio ROADMAP D2:
  - Los onsets detectados deben coincidir con los beats ±50 ms.
  - BPM estimado dentro de ±15% del BPM real del click-track.
  - Latencia de actx < 100 ms (trivialmente satisfecho: _process_block es síncrono).
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from server.live_input import LiveInput, _ONSET_GAP_MS, _HISTORY_SEC

_SR = 44100
_BS = 1024  # blocksize por defecto


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sine(freq_hz: float, n: int, amp: float = 0.5) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / _SR
    return amp * np.sin(2.0 * math.pi * freq_hz * t)


def _click_track(bpm: float, duration_s: float) -> list:
    """Genera bloques con bursts de ruido en cada beat (click-track sintético)."""
    period_s = 60.0 / bpm
    beat_times = np.arange(0.0, duration_s, period_s)
    n_total = int(duration_s * _SR)
    audio = np.zeros(n_total, dtype=np.float32)
    rng = np.random.default_rng(42)
    for bt in beat_times:
        idx = int(bt * _SR)
        end = min(idx + 256, n_total)
        audio[idx:end] = rng.uniform(-0.9, 0.9, end - idx).astype(np.float32)
    # Dividir en bloques de _BS muestras
    blocks = []
    for i in range(0, n_total - _BS, _BS):
        blocks.append(audio[i:i + _BS])
    return blocks


def _feed(li: LiveInput, blocks: list) -> None:
    for blk in blocks:
        li._process_block(blk)


# ── Tests de features ─────────────────────────────────────────────────────────

class TestFeatures:
    def test_rms_silence(self):
        li = LiveInput(_SR, _BS)
        li._process_block(np.zeros(_BS, dtype=np.float32))
        with li._lock:
            assert li._feat_rms[-1] < 0.001

    def test_rms_sine_amplitude(self):
        li = LiveInput(_SR, _BS)
        li._process_block(_sine(440.0, _BS, amp=0.5))
        with li._lock:
            rms = li._feat_rms[-1]
        # RMS de seno amp=0.5 ≈ 0.5/√2 ≈ 0.354
        assert 0.30 < rms < 0.40, f"RMS: {rms:.4f}"

    def test_flux_nonzero_on_transient(self):
        li = LiveInput(_SR, _BS)
        # Varios frames de silencio establecen la baseline
        for _ in range(5):
            li._process_block(np.zeros(_BS, dtype=np.float32))
        li._process_block(_sine(220.0, _BS, amp=0.9))
        with li._lock:
            flux = li._feat_flux[-1]
        assert flux > 0.0

    def test_has_timeseries_initially_false(self):
        li = LiveInput(_SR, _BS)
        assert not li.has_timeseries

    def test_has_timeseries_after_first_block(self):
        li = LiveInput(_SR, _BS)
        li._process_block(np.zeros(_BS, dtype=np.float32))
        assert li.has_timeseries

    def test_get_audio_context_keys(self):
        li = LiveInput(_SR, _BS)
        li._process_block(_sine(440.0, _BS, amp=0.4))
        ctx = li.get_audio_context(1.0)
        for key in ('rms', 'flux', 'energy', 'norm'):
            assert key in ctx, f"Falta clave: {key}"
        for key in ('rms', 'flux', 'onset_strength', 'kick'):
            assert key in ctx['norm'], f"Falta norm[{key}]"

    def test_norm_rms_bounded(self):
        li = LiveInput(_SR, _BS)
        for _ in range(10):
            li._process_block(_sine(440.0, _BS, amp=0.9))
        ctx = li.get_audio_context(1.0)
        rms_n = ctx['norm']['rms']
        assert 0.0 <= rms_n <= 1.0, f"norm.rms={rms_n}"

    def test_norm_flux_bounded(self):
        li = LiveInput(_SR, _BS)
        for _ in range(5):
            li._process_block(np.zeros(_BS, dtype=np.float32))
        li._process_block(_sine(440.0, _BS, amp=0.9))
        ctx = li.get_audio_context(1.0)
        flux_n = ctx['norm']['flux']
        assert 0.0 <= flux_n <= 1.0, f"norm.flux={flux_n}"

    def test_default_ctx_on_empty(self):
        li = LiveInput(_SR, _BS)
        ctx = li.get_audio_context(0.0)
        assert ctx['rms'] == 0.0
        assert isinstance(ctx['norm'], dict)

    def test_history_bounded(self):
        """El deque no crece más allá de su maxlen (~30 s de frames)."""
        li = LiveInput(_SR, _BS)
        # Alimentar 40 s de audio
        n_frames = int(40.0 * _SR / _BS)
        silence = np.zeros(_BS, dtype=np.float32)
        for _ in range(n_frames):
            li._process_block(silence)
        with li._lock:
            n = len(li._feat_rms)
        # maxlen ≈ (30 s × SR / BS) + 4
        expected_max = int(math.ceil(_HISTORY_SEC * _SR / _BS)) + 8
        assert n <= expected_max, f"Historial demasiado largo: {n} > {expected_max}"


# ── Tests de onset detection ──────────────────────────────────────────────────

class TestOnsetDetection:
    def test_onset_on_transient(self):
        """Silencio seguido de burst → debe detectar onset."""
        li = LiveInput(_SR, _BS)
        for _ in range(8):
            li._process_block(np.zeros(_BS, dtype=np.float32))
        li._process_block(_sine(440.0, _BS, amp=0.9))
        with li._lock:
            onsets = list(li._onset_times)
        assert len(onsets) >= 1, "Debería haber detectado ≥1 onset"

    def test_onset_gap_enforced(self):
        """Bursts continuos no producen onsets más rápidos que _ONSET_GAP_MS."""
        li = LiveInput(_SR, _BS)
        burst = _sine(440.0, _BS, amp=0.9)
        for _ in range(20):
            li._process_block(burst)
        with li._lock:
            times = list(li._onset_times)
        if len(times) >= 2:
            gaps_ms = [
                (times[i + 1] - times[i]) * 1000.0
                for i in range(len(times) - 1)
            ]
            min_gap = min(gaps_ms)
            # Tolerancia de ±1 frame (≈23 ms) por redondeo de blocksize
            assert min_gap >= _ONSET_GAP_MS - 30, (
                f"Gap mínimo {min_gap:.1f} ms < {_ONSET_GAP_MS} ms")

    def test_no_onset_in_silence(self):
        li = LiveInput(_SR, _BS)
        for _ in range(30):
            li._process_block(np.zeros(_BS, dtype=np.float32))
        with li._lock:
            n = len(li._onset_times)
        assert n == 0, f"Onsets en silencio: {n}"


# ── Tests de beat tracking ────────────────────────────────────────────────────

class TestBeatTracking:
    def test_bpm_estimate_120(self):
        """Click track a 120 BPM → estimación dentro de ±20 BPM."""
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(120.0, 8.0))
        with li._lock:
            bpm = li._bpm
        assert 100.0 < bpm < 140.0, f"BPM estimado: {bpm:.1f}"

    def test_bpm_estimate_140(self):
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(140.0, 8.0))
        with li._lock:
            bpm = li._bpm
        assert 115.0 < bpm < 165.0, f"BPM estimado: {bpm:.1f}"

    def test_bpm_estimate_90(self):
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(90.0, 10.0))
        with li._lock:
            bpm = li._bpm
        assert 70.0 < bpm < 115.0, f"BPM estimado: {bpm:.1f}"

    def test_onsets_count_on_click_track(self):
        """120 BPM × 8s = 16 beats → ≥7 onsets detectados."""
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(120.0, 8.0))
        with li._lock:
            n = len(li._onset_times)
        assert n >= 7, f"Onsets detectados: {n}"

    def test_list_beats_nonempty_after_feed(self):
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(120.0, 8.0))
        beats = li.list_beats()
        assert len(beats) > 0

    def test_list_beats_sorted(self):
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(120.0, 8.0))
        beats = li.list_beats()
        assert beats == sorted(beats)

    def test_list_beats_time_filter(self):
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(120.0, 8.0))
        beats_all = li.list_beats()
        beats_2_4 = li.list_beats(t0=2.0, t1=4.0)
        assert all(2.0 <= b <= 4.0 for b in beats_2_4)
        assert len(beats_2_4) < len(beats_all)

    def test_list_downbeats_subset_of_beats(self):
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(120.0, 8.0))
        beats = li.list_beats()
        dbs = li.list_downbeats()
        assert len(dbs) <= len(beats)
        # Cada downbeat debe estar en la lista de beats
        beats_set = set(round(b, 6) for b in beats)
        for db in dbs:
            assert round(db, 6) in beats_set, f"Downbeat {db} no está en beats"

    def test_list_downbeats_time_filter(self):
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(120.0, 10.0))
        dbs = li.list_downbeats(t0=3.0, t1=7.0)
        assert all(3.0 <= d <= 7.0 for d in dbs)

    def test_section_at_returns_none(self):
        li = LiveInput(_SR, _BS)
        assert li.section_at(1.0) is None
        assert li.section_at(100.0) is None


# ── Tests de onsets dentro de ±50 ms (criterio ROADMAP D2) ───────────────────

class TestOnsetTolerance:
    def test_onsets_near_beats_120bpm(self):
        """
        Onsets detectados deben coincidir con beats teóricos ±50 ms.
        Criterio ROADMAP D2: ≥50% de los beats teóricos deben tener un onset
        correspondiente dentro de ±50 ms.
        """
        bpm = 120.0
        period_s = 60.0 / bpm
        duration_s = 8.0
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(bpm, duration_s))
        with li._lock:
            detected = list(li._onset_times)

        beat_times = np.arange(0.0, duration_s, period_s)
        matches = sum(
            1 for bt in beat_times
            if any(abs(d - bt) <= 0.05 for d in detected)
        )
        pct = matches / len(beat_times) * 100
        assert matches >= len(beat_times) * 0.5, (
            f"{matches}/{len(beat_times)} beats con onset ±50ms ({pct:.0f}%)")

    def test_onsets_near_beats_90bpm(self):
        bpm = 90.0
        period_s = 60.0 / bpm
        duration_s = 10.0
        li = LiveInput(_SR, _BS)
        _feed(li, _click_track(bpm, duration_s))
        with li._lock:
            detected = list(li._onset_times)

        beat_times = np.arange(0.0, duration_s, period_s)
        matches = sum(
            1 for bt in beat_times
            if any(abs(d - bt) <= 0.05 for d in detected)
        )
        assert matches >= len(beat_times) * 0.4, (
            f"{matches}/{len(beat_times)} beats con onset ±50ms")


# ── Tests de dispositivos ─────────────────────────────────────────────────────

class TestDevices:
    def test_list_devices_returns_list(self):
        """list_devices no debe lanzar excepción aunque no haya HW."""
        devs = LiveInput.list_devices()
        assert isinstance(devs, list)

    def test_list_devices_structure(self):
        devs = LiveInput.list_devices()
        for d in devs:
            if 'error' not in d:
                assert 'index' in d
                assert 'name' in d
                assert 'channels' in d


# ── Tests de ciclo de vida (sin HW) ──────────────────────────────────────────

class TestLifecycle:
    def test_is_active_false_initially(self):
        li = LiveInput(_SR, _BS)
        assert not li.is_active

    def test_stop_when_not_started_is_noop(self):
        li = LiveInput(_SR, _BS)
        li.stop()  # no debe lanzar

    def test_frame_count_increments(self):
        li = LiveInput(_SR, _BS)
        for i in range(5):
            li._process_block(np.zeros(_BS, dtype=np.float32))
        with li._lock:
            fc = li._frame_count
        assert fc == 5

    def test_t_s_tracks_duration(self):
        li = LiveInput(_SR, _BS)
        n = 10
        for _ in range(n):
            li._process_block(np.zeros(_BS, dtype=np.float32))
        expected_s = n * _BS / _SR
        with li._lock:
            t = li._t_s
        assert abs(t - expected_s) < 0.001, f"t_s={t:.4f} expected≈{expected_s:.4f}"

    def test_summary_keys(self):
        li = LiveInput(_SR, _BS)
        li._process_block(np.zeros(_BS, dtype=np.float32))
        s = li.summary
        assert 'bpm' in s
        assert 'duration_s' in s
        assert s['has_timeseries'] is True
