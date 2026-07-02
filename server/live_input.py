"""
server/live_input.py — Captura de audio en vivo + features reactivas (Fase D2).

Implementa la interfaz mínima de AnalysisService para que D1 funcione con
música en directo sin archivo analizado:

  • list_beats / list_downbeats  — beats sintéticos estimados desde IOI
  • section_at                   — siempre None (sin análisis estructural)
  • get_audio_context            — features del ring buffer (rms, flux, norm{…})
  • has_timeseries = True        — mientras haya ≥1 frame capturado

Pipeline (hilo de audio ≠ hilo principal):
  sounddevice callback
  → _process_block(mono)        ← también llamable directo en tests (sin HW)
    → RMS + flux espectral
    → detección de onset (RMS > ratio×smooth con cooldown)
    → historial circular (deque, maxlen ~30 s de frames)
    → _estimate_bpm()           → BPM medio IOI → beats sintéticos

Limitaciones documentadas (timebox D2):
  - Sin análisis estructural (section_at = None).
  - BPM best-effort: funciona en 4/4 estable; peor en ritmos irregulares.
  - No usa madmom (demasiado pesado para tiempo real).
"""
from __future__ import annotations

import math
import threading
from bisect import bisect_left, bisect_right
from collections import deque
from typing import Any

import numpy as np

_SR_DEFAULT: int = 44100
_BLOCKSIZE_DEFAULT: int = 1024          # ≈23 ms por bloque

_HISTORY_SEC: float = 30.0             # historial de features a retener
_ONSET_RATIO: float = 1.5              # RMS > ratio×smooth_rms → onset candidato
_ONSET_MIN_RMS: float = 0.01           # ignora silencio
_ONSET_GAP_MS: float = 150.0          # mínimo entre onsets (ms)
_SMOOTH_N: int = 8                     # ventana EMA para smooth_rms (≈8 bloques)
_IOI_MIN_MS: float = 300.0            # IOI max BPM ≤ 200
_IOI_MAX_MS: float = 2000.0           # IOI min BPM ≥ 30
_BPM_ALPHA: float = 0.8               # EMA de BPM: α×old + (1-α)×new


def _history_maxlen(sr: int, blocksize: int) -> int:
    return int(math.ceil(_HISTORY_SEC * sr / blocksize)) + 4


class LiveInput:
    """
    Captura audio de entrada y expone features reactivas.
    Interfaz compatible con AnalysisService (lista de beats, get_audio_context)
    para que D1 funcione sin pista analizada.

    Uso normal:
        li = LiveInput()
        li.start(device=None)       # None = dispositivo por defecto del SO
        # … en compute_frame …
        ctx = li.get_audio_context(t_s)
        beats = li.list_beats()
        li.stop()

    Uso en tests (sin hardware):
        li = LiveInput(sample_rate=44100, blocksize=1024)
        li._process_block(numpy_array_float32)   # inyecta PCM sintético
    """

    def __init__(self, sample_rate: int = _SR_DEFAULT,
                 blocksize: int = _BLOCKSIZE_DEFAULT):
        self._sr = sample_rate
        self._blocksize = blocksize
        self._lock = threading.Lock()
        self._stream = None

        # Historial de features (circular, maxlen ≈ 30 s)
        _maxlen = _history_maxlen(sample_rate, blocksize)
        self._feat_rms: deque = deque(maxlen=_maxlen)
        self._feat_flux: deque = deque(maxlen=_maxlen)
        self._feat_onset: deque = deque(maxlen=_maxlen)

        # Estado para onset detection
        self._smooth_rms: float = _ONSET_MIN_RMS
        self._last_onset_t: float = -1.0   # tiempo (s) del último onset
        self._frame_count: int = 0
        self._t_s: float = 0.0             # tiempo transcurrido (s) desde start

        # Onset times para estimación de BPM (lista podada cada nuevo onset)
        self._onset_times: list[float] = []

        # Beats sintéticos generados a partir del BPM estimado
        self._bpm: float = 120.0
        self._beats: list[float] = []
        self._downbeats: list[float] = []

        # FFT anterior para flux espectral
        self._prev_mag: np.ndarray | None = None

    # ── Propiedades / interfaz pública ────────────────────────────────────────

    @property
    def has_timeseries(self) -> bool:
        """True en cuanto hay ≥1 bloque procesado (igual que AnalysisService)."""
        with self._lock:
            return self._frame_count > 0

    @property
    def is_active(self) -> bool:
        """True si el stream de sounddevice está capturando."""
        return (self._stream is not None
                and getattr(self._stream, 'active', False))

    @property
    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "bpm": round(self._bpm, 1),
                "duration_s": self._t_s,
                "bpm_source": "live_ioi",
                "downbeats_source": "live_synthetic",
                "has_timeseries": self._frame_count > 0,
            }

    # ── Dispositivos ──────────────────────────────────────────────────────────

    @staticmethod
    def list_devices() -> list[dict[str, Any]]:
        """Lista dispositivos de entrada disponibles."""
        try:
            import sounddevice as sd
            result = []
            for i, d in enumerate(sd.query_devices()):
                if d['max_input_channels'] > 0:
                    result.append({
                        "index": i,
                        "name": d['name'],
                        "channels": int(d['max_input_channels']),
                        "default_sr": int(d['default_samplerate']),
                    })
            return result
        except Exception as e:
            return [{"error": str(e)}]

    # ── Ciclo de vida ─────────────────────────────────────────────────────────

    def start(self, device=None) -> None:
        """Arranca el stream de captura. No-op si ya está activo."""
        if self.is_active:
            return
        import sounddevice as sd
        with self._lock:
            self._reset_state()
        self._stream = sd.InputStream(
            samplerate=self._sr,
            blocksize=self._blocksize,
            device=device,
            channels=1,
            dtype='float32',
            callback=self._audio_callback,
        )
        self._stream.start()

    def stop(self) -> None:
        """Detiene el stream."""
        s = self._stream
        self._stream = None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def _reset_state(self) -> None:
        """Reinicia todo el estado (debe llamarse bajo _lock)."""
        self._feat_rms.clear()
        self._feat_flux.clear()
        self._feat_onset.clear()
        self._smooth_rms = _ONSET_MIN_RMS
        self._last_onset_t = -1.0
        self._frame_count = 0
        self._t_s = 0.0
        self._onset_times.clear()
        self._beats.clear()
        self._downbeats.clear()
        self._prev_mag = None

    # ── Interfaz AnalysisService ──────────────────────────────────────────────

    def list_beats(self, t0: float = 0.0,
                   t1: float | None = None) -> list[float]:
        with self._lock:
            beats = self._beats
            lo = bisect_left(beats, t0)
            hi = bisect_right(beats, t1) if t1 is not None else len(beats)
            return list(beats[lo:hi])

    def list_downbeats(self, t0: float = 0.0,
                       t1: float | None = None) -> list[float]:
        with self._lock:
            dbs = self._downbeats
            lo = bisect_left(dbs, t0)
            hi = bisect_right(dbs, t1) if t1 is not None else len(dbs)
            return list(dbs[lo:hi])

    def section_at(self, time_sec: float):
        """Sin análisis estructural en vivo: devuelve siempre None."""
        return None

    def get_audio_context(self, time_sec: float) -> dict[str, Any]:
        """
        Devuelve el mismo shape que AnalysisService.get_audio_context.
        En modo live siempre devuelve el frame MÁS RECIENTE (time_sec ignorado):
        la latencia de captura ya introduce un pequeño desfase natural.
        """
        ctx = _default_ctx()
        with self._lock:
            if not self._feat_rms:
                return ctx
            rms = self._feat_rms[-1]
            flux = self._feat_flux[-1]
            onset = self._feat_onset[-1]

        ctx['rms'] = rms
        ctx['flux'] = flux
        ctx['energy'] = rms * rms
        ctx['zcr'] = 0.0
        ctx['centroid'] = 2000.0 * (1.0 + float(flux))

        rms_norm = float(np.clip(rms / 0.3, 0.0, 1.0))
        flux_norm = float(np.clip(flux / 0.5, 0.0, 1.0))
        # onset_strength y kick: nonzero SOLO en frames de onset
        transient = float(np.clip(rms / 0.2, 0.0, 1.0)) if onset else 0.0
        ctx['norm'] = {
            'rms': rms_norm,
            'flux': flux_norm,
            'energy': float(np.clip(rms * rms / 0.09, 0.0, 1.0)),
            'onset_strength': transient,
            'kick': transient,   # proxy: D1 usa kick > 0.6 para on_kick
        }
        return ctx

    # ── Procesado de bloques (llamable desde tests sin HW) ───────────────────

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        """sounddevice callback — hilo de audio de alta prioridad."""
        mono = indata[:, 0] if indata.ndim > 1 else indata.ravel()
        self._process_block(mono)

    def _process_block(self, mono: np.ndarray) -> None:
        """
        Extrae features de un bloque mono float32 y actualiza el historial.
        Puede llamarse directamente en tests (inyección de PCM sintético).
        Thread-safe: la computación pesada fuera del lock; solo la escritura dentro.
        """
        n = len(mono)
        # ── Fuera del lock: cómputo puro ────────────────────────────────────
        rms = float(np.sqrt(np.mean(mono * mono) + 1e-12))

        # Flux espectral: suma de diferencias positivas de magnitud FFT
        window = np.hanning(n) if n > 0 else np.array([1.0])
        fft_mag = np.abs(np.fft.rfft(mono * window))

        with self._lock:
            prev_mag = self._prev_mag
            self._prev_mag = fft_mag

        if prev_mag is not None and prev_mag.shape == fft_mag.shape:
            diff = fft_mag - prev_mag
            flux = float(np.sum(np.maximum(diff, 0.0)) / (len(fft_mag) + 1e-12))
        else:
            flux = 0.0

        # ── Dentro del lock: actualización de estado ─────────────────────────
        with self._lock:
            self._frame_count += 1
            t_s = self._frame_count * self._blocksize / self._sr
            self._t_s = t_s

            # EMA del RMS para baseline
            alpha = 1.0 / (_SMOOTH_N + 1)
            self._smooth_rms = (1.0 - alpha) * self._smooth_rms + alpha * rms

            # Detección de onset: transiente + cooldown
            gap_ms = (t_s - self._last_onset_t) * 1000.0
            onset = (rms > _ONSET_RATIO * self._smooth_rms
                     and rms > _ONSET_MIN_RMS
                     and gap_ms >= _ONSET_GAP_MS)
            if onset:
                self._last_onset_t = t_s
                self._onset_times.append(t_s)
                # Podar onsets > 30s
                cutoff = t_s - _HISTORY_SEC
                idx = bisect_left(self._onset_times, cutoff)
                if idx > 0:
                    self._onset_times = self._onset_times[idx:]
                self._estimate_bpm_locked(t_s)

            self._feat_rms.append(rms)
            self._feat_flux.append(flux)
            self._feat_onset.append(onset)

    def _estimate_bpm_locked(self, current_t: float) -> None:
        """
        Estima BPM y regenera listas de beats sintéticos.
        Debe llamarse con self._lock ya adquirido.
        """
        onsets = self._onset_times
        if len(onsets) < 4:
            return

        # IOIs en ms entre onsets consecutivos
        arr = np.array(onsets, dtype=np.float64)
        iois_ms = np.diff(arr) * 1000.0
        valid = iois_ms[(iois_ms >= _IOI_MIN_MS) & (iois_ms <= _IOI_MAX_MS)]
        if len(valid) < 2:
            return

        # Mediana como estimador robusto
        new_bpm = 60000.0 / float(np.median(valid))
        self._bpm = _BPM_ALPHA * self._bpm + (1.0 - _BPM_ALPHA) * new_bpm

        # Beats sintéticos: usa el onset más reciente como referencia de fase
        beat_s = 60.0 / self._bpm
        ref = onsets[-1]
        max_t = current_t + 5.0   # 5 s hacia el futuro para list_beats()

        beats: list[float] = []
        t = ref
        while t >= 0.0:
            beats.append(t)
            t -= beat_s
        t = ref + beat_s
        while t <= max_t:
            beats.append(t)
            t += beat_s
        beats.sort()
        self._beats = beats
        # Downbeats: cada 4 beats (aproxima el "1" de cada compás)
        self._downbeats = beats[::4]


# ── Helpers globales ──────────────────────────────────────────────────────────

def _default_ctx() -> dict[str, Any]:
    """Contexto de audio neutro (mismo shape que AnalysisService)."""
    return {
        'rms': 0.0, 'energy': 0.0, 'flux': 0.0,
        'centroid': 2000.0, 'zcr': 0.0,
        'mfcc': np.zeros(13, dtype=np.float32),
        'chroma': np.full(12, 0.5, dtype=np.float32),
        'tonnetz': np.zeros(6, dtype=np.float32),
        'contrast': np.full(7, 30.0, dtype=np.float32),
        'mel_bands': np.full(8, -25.0, dtype=np.float32),
        'norm': {},
    }
