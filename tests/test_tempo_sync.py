"""
test_tempo_sync.py — Tests del servicio de sync de tempo (G2).

Sin hardware real: se usa _calc_bpm() directamente y se mockea la sesión
para verificar la inyección del BPM en el audio context.

Cubre:
  - _calc_bpm: 24 pulsos uniformes → BPM correcto (120, 128, 60).
  - _calc_bpm: pulsos con jitter → usa mediana, estable.
  - _calc_bpm: < 2 pulsos → devuelve 0.0.
  - TempoSyncService.get_state en modo "off".
  - TempoSyncService._process_pulse acumula y calcula BPM.
  - mode="off" → session._get_audio_context no modifica bpm del análisis.
  - Link (mock pylinkbpm): bpm=128.5 → tempo_sync.bpm == 128.5.
"""
import sys
import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from server.tempo_sync import _calc_bpm, TempoSyncService


# ── _calc_bpm: función pura ──────────────────────────────────────────────────

def _pulse_times(n_pulses: int, ipi_s: float, t0: float = 0.0):
    """Genera n timestamps de pulsos uniformemente espaciados."""
    return [t0 + i * ipi_s for i in range(n_pulses)]


def test_calc_bpm_120():
    """24 pulsos a 120 BPM → IPI = 500ms/24 ≈ 20.83ms."""
    ipi = 0.5 / 24  # 500ms de beat / 24 pulsos
    times = _pulse_times(25, ipi)
    bpm = _calc_bpm(times)
    assert abs(bpm - 120.0) < 0.5, f"esperado ~120, got {bpm}"


def test_calc_bpm_128():
    """24 pulsos a 128 BPM → IPI = (60/128)/24."""
    ipi = (60.0 / 128) / 24
    times = _pulse_times(25, ipi)
    bpm = _calc_bpm(times)
    assert abs(bpm - 128.0) < 0.5


def test_calc_bpm_60():
    """24 pulsos a 60 BPM → IPI = 1/24 s."""
    ipi = 1.0 / 24
    times = _pulse_times(25, ipi)
    bpm = _calc_bpm(times)
    assert abs(bpm - 60.0) < 0.5


def test_calc_bpm_with_jitter():
    """Jitter ±5% sobre IPI → mediana estable, BPM dentro de ±5."""
    import random
    random.seed(42)
    ipi = 0.5 / 24
    jitter = 0.05 * ipi
    # Cada pulso en t0 + i*ipi + perturbación independiente
    times = [i * ipi + random.uniform(-jitter, jitter) for i in range(25)]
    bpm = _calc_bpm(times)
    assert abs(bpm - 120.0) < 5.0


def test_calc_bpm_too_few_pulses():
    """Menos de 2 pulsos → devuelve 0.0."""
    assert _calc_bpm([]) == 0.0
    assert _calc_bpm([1.0]) == 0.0


# ── TempoSyncService.get_state ───────────────────────────────────────────────

def test_tempo_sync_initial_state():
    """Estado inicial: mode=off, bpm=0, synced=False."""
    ts = TempoSyncService()
    st = ts.get_state()
    assert st["mode"] == "off"
    assert st["bpm"] == 0.0
    assert st["synced"] is False


def test_tempo_sync_process_pulse():
    """_process_pulse con 25 pulsos a 120 BPM → bpm se acerca a 120."""
    ts = TempoSyncService()
    ipi = 0.5 / 24
    t0 = time.monotonic()
    for i in range(25):
        ts._process_pulse(t0 + i * ipi)
    assert abs(ts.bpm - 120.0) < 1.0


# ── Integración con session (_get_audio_context) ─────────────────────────────

def _make_stub_session(analysis_bpm: float = 130.0):
    """Sesión mínima con tempo_sync = TempoSyncService() y analysis simulado."""
    from server.tempo_sync import TempoSyncService
    from server.session import ShowSession

    class _FakeAnalysis:
        has_timeseries = True
        def get_audio_context(self, t_s):
            return {"bpm": analysis_bpm, "rms": 0.5, "norm": {"rms": 0.5}}

    s = ShowSession.__new__(ShowSession)
    s.tempo_sync = TempoSyncService()
    s.analysis = _FakeAnalysis()
    s._cached_actx = {"bpm": analysis_bpm, "rms": 0.5, "norm": {"rms": 0.5}}
    s._live_mode = False
    s.live_input = None
    return s


def test_mode_off_does_not_override_bpm():
    """Con mode=off, _get_audio_context devuelve el BPM del análisis sin cambios."""
    s = _make_stub_session(analysis_bpm=130.0)
    s.tempo_sync.mode = "off"
    s.tempo_sync.bpm = 0.0

    actx = s._get_audio_context(0.0)
    assert actx["bpm"] == 130.0


def test_tempo_sync_overrides_bpm_in_audio_context():
    """Con bpm=128.5, _get_audio_context inyecta 128.5 sobre el BPM del análisis."""
    s = _make_stub_session(analysis_bpm=130.0)
    s.tempo_sync.mode = "midi_clock"
    s.tempo_sync.bpm = 128.5

    actx = s._get_audio_context(0.0)
    assert abs(actx["bpm"] - 128.5) < 0.01


def test_tempo_sync_does_not_mutate_cache():
    """La inyección de BPM no muta _cached_actx (hace copia shallow)."""
    s = _make_stub_session(analysis_bpm=130.0)
    s.tempo_sync.mode = "midi_clock"
    s.tempo_sync.bpm = 100.0
    # Forzar que el fallback sea _cached_actx
    s.analysis = None
    s._get_audio_context(0.0)
    # El cache original no debe haberse modificado
    assert s._cached_actx["bpm"] == 130.0


# ── Ableton Link (mock) ──────────────────────────────────────────────────────

def test_link_mode_reads_bpm_from_pylinkbpm():
    """Con pylinkbpm mockeado, el hilo Link actualiza self.bpm."""
    mock_pylinkbpm = MagicMock()
    mock_link_instance = MagicMock()
    mock_link_instance.bpm = 128.5
    mock_pylinkbpm.PyLinkBpm.return_value = mock_link_instance

    ts = TempoSyncService()

    # Simula el hilo de Link: lee bpm dos veces y sale
    call_count = [0]
    original_sleep = time.sleep

    def fake_sleep(n):
        call_count[0] += 1
        if call_count[0] >= 2:
            ts._stop_event.set()  # para el hilo tras 2 ciclos

    with patch.dict("sys.modules", {"pylinkbpm": mock_pylinkbpm}):
        with patch("time.sleep", side_effect=fake_sleep):
            ts._stop_event.clear()
            t = threading.Thread(target=ts._run_ableton_link, daemon=True)
            t.start()
            t.join(timeout=3.0)

    assert abs(ts.bpm - 128.5) < 0.01


# ── MIDI Clock (mode="midi_clock") sin abrir puerto real ─────────────────────

def test_midi_clock_bpm_calc_end_to_end():
    """Simulación end-to-end: 25 pulsos a 120 BPM inyectados en _process_pulse."""
    ts = TempoSyncService()
    ts.mode = "midi_clock"
    ipi = 0.5 / 24  # 120 BPM
    t0 = time.monotonic()
    for i in range(25):
        ts._process_pulse(t0 + i * ipi)
    assert abs(ts.bpm - 120.0) < 1.0
    st = ts.get_state()
    assert st["synced"] is True
    assert abs(st["bpm"] - 120.0) < 1.0
