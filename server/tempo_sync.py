"""
server/tempo_sync.py — Sincronización de BPM via Ableton Link o MIDI Clock.

Expone TempoSyncService con bpm y beat_phase en tiempo real.
El render loop (session.compute_frame) inyecta el BPM de sync en el audio
context si el modo no es "off".

Diseño:
  - TempoSyncService corre en un hilo de fondo (Link / mido son blocking I/O).
  - bpm y beat_phase se leen desde el render loop sin lock (float write atómico en CPython).
  - _calc_bpm() es una función pura testeable sin hardware.
  - Ambas librerías (pylinkbpm, mido) son imports opcionales: si no están, se loguea
    y el modo queda efectivamente "off".
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from statistics import median
from typing import Literal

from src.log import get_logger, log_throttled

_log = get_logger(__name__)

_PULSES_PER_BEAT = 24   # MIDI Clock: 24 pulsos por negra
_PULSE_WINDOW    = 48   # guardar 2 beats de historia (48 intervalos)


# ───────────────────────────────────────────────────────────────
# Lógica pura (testeable sin hardware)
# ───────────────────────────────────────────────────────────────

def _calc_bpm(pulse_times_s: list[float]) -> float:
    """BPM a partir de lista de timestamps de pulsos MIDI Clock (en segundos).

    Usa mediana de inter-pulse intervals para robustez ante jitter USB.
    Devuelve 0.0 si no hay suficientes pulsos para calcular.
    """
    if len(pulse_times_s) < 2:
        return 0.0
    intervals = [
        pulse_times_s[i + 1] - pulse_times_s[i]
        for i in range(len(pulse_times_s) - 1)
    ]
    med = median(intervals)
    if med <= 0:
        return 0.0
    # 24 pulsos = 1 beat → beat_duration = 24 × inter_pulse_interval
    return 60.0 / (med * _PULSES_PER_BEAT)


# ───────────────────────────────────────────────────────────────
# TempoSyncService
# ───────────────────────────────────────────────────────────────

class TempoSyncService:
    """Sincroniza BPM vía Ableton Link o MIDI Clock.

    Uso típico (en session.py):
        self.tempo_sync = TempoSyncService()
        # al activar desde UI:
        await self.tempo_sync.start("midi_clock", device="IAC Driver Bus 1")
        # en compute_frame:
        if self.tempo_sync.bpm > 0:
            audio_ctx["bpm"] = self.tempo_sync.bpm
    """

    def __init__(self) -> None:
        self.mode: Literal["off", "link", "midi_clock", "manual"] = "off"
        self.bpm: float = 0.0
        self.beat_phase: float = 0.0
        self.midi_device: str | None = None

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pulse_times: deque[float] = deque(maxlen=_PULSE_WINDOW)

    # ── MIDI Clock ──────────────────────────────────────────────

    def _process_pulse(self, t: float) -> None:
        """Registra un pulso MIDI Clock y recalcula BPM. Thread-safe (deque append es atómico)."""
        self._pulse_times.append(t)
        bpm = _calc_bpm(list(self._pulse_times))
        if bpm > 0:
            self.bpm = bpm

    def _run_midi_clock(self, device: str | None) -> None:
        try:
            import mido  # type: ignore
        except ImportError:
            _log.error(
                "mido no instalado — MIDI Clock no disponible. "
                "Instala: pip install mido python-rtmidi"
            )
            return

        port_name = device
        try:
            port = mido.open_input(port_name)
        except Exception as e:
            _log.error("No se pudo abrir puerto MIDI %r: %s", port_name, e)
            return

        _log.info("MIDI Clock: escuchando en %r", port.name)
        try:
            while not self._stop_event.is_set():
                for msg in port.iter_pending():
                    if msg.type == "clock":
                        self._process_pulse(time.monotonic())
                time.sleep(0.001)
        finally:
            port.close()

    # ── Ableton Link ─────────────────────────────────────────────

    def _run_ableton_link(self) -> None:
        try:
            import pylinkbpm  # type: ignore
        except ImportError:
            _log.error(
                "pylinkbpm no instalado — Ableton Link no disponible. "
                "Instala: pip install pylinkbpm"
            )
            return

        try:
            link = pylinkbpm.PyLinkBpm(120.0)
            link.enabled = True
            _log.info("Ableton Link activo")
            while not self._stop_event.is_set():
                self.bpm = float(link.bpm)
                time.sleep(0.05)
        except Exception as e:
            log_throttled(_log, logging.ERROR, "link_run", f"Ableton Link error: {e}")
        finally:
            try:
                link.enabled = False
            except Exception:
                pass

    # ── Control async ────────────────────────────────────────────

    async def start(self, mode: str, device: str | None = None) -> None:
        """Activa el modo de sync. Para el modo anterior si había uno."""
        await self.stop()

        if mode not in ("off", "link", "midi_clock", "manual"):
            _log.warning("TempoSyncService: modo desconocido %r — ignorado", mode)
            return

        self.mode = mode  # type: ignore[assignment]
        self.midi_device = device
        self.bpm = 0.0
        self.beat_phase = 0.0
        self._pulse_times.clear()

        if mode == "off":
            return

        self._stop_event.clear()
        if mode == "link":
            target = self._run_ableton_link
            args: tuple = ()
        else:
            target = self._run_midi_clock
            args = (device,)

        self._thread = threading.Thread(target=target, args=args, daemon=True,
                                        name=f"TempoSync-{mode}")
        self._thread.start()

    async def stop(self) -> None:
        """Para el hilo de sync. Idempotente."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self.mode = "off"
        self.bpm = 0.0
        self.beat_phase = 0.0

    def get_state(self) -> dict:
        return {
            "mode": self.mode,
            "bpm": round(self.bpm, 2) if self.bpm else 0.0,
            "beat_phase": round(self.beat_phase, 3),
            "midi_device": self.midi_device,
            "synced": self.bpm > 0.0 and self.mode != "off",
        }

    # ── M1: Tap tempo ────────────────────────────────────────────

    _TAP_MAX = 8    # circular buffer de los últimos N taps
    _TAP_MIN = 4    # taps mínimos para actualizar BPM

    def __init_tap(self) -> None:
        if not hasattr(self, "_tap_times"):
            self._tap_times: deque = deque(maxlen=self._TAP_MAX)

    def tap(self, t_wall: float) -> dict:
        """Registra un tap (wall clock en segundos, p. ej. time.perf_counter()).
        Tras 4+ taps calcula BPM por mediana de intervalos y activa mode='manual'.
        Descarta taps > 3 s separados del anterior (nuevo ritmo).
        Devuelve: {bpm: float|None, taps: int, ready: bool}
        """
        self.__init_tap()
        # descarte si hay un hueco grande — el usuario empezó de nuevo
        if self._tap_times and (t_wall - self._tap_times[-1]) > 3.0:
            self._tap_times.clear()
        self._tap_times.append(t_wall)
        n = len(self._tap_times)
        if n < self._TAP_MIN:
            return {"bpm": None, "taps": n, "ready": False}

        intervals = [
            self._tap_times[i + 1] - self._tap_times[i]
            for i in range(n - 1)
        ]
        med = median(intervals)
        if med <= 0:
            return {"bpm": None, "taps": n, "ready": False}

        bpm = round(60.0 / med, 1)
        self.bpm = bpm
        self.mode = "manual"  # type: ignore[assignment]
        return {"bpm": bpm, "taps": n, "ready": True}
