"""
audio_headless.py — Reproductor de audio headless (sin Qt, sin display).

Portado de `src/ui/feedback_app_with_barras.py::AudioPlayer` con dos cambios:
  1. Solo `pygame.mixer.init()` (NO `pygame.init()`): evita inicializar el
     subsistema de vídeo/display, innecesario en un servidor headless.
  2. Reloj con `time.monotonic()` en vez de `pygame.time.get_ticks()` (que
     requiere `pygame.init()`).

Es el **reloj maestro** del show: el tick lee `get_current_time()` y el resto
del sistema (Art-Net, frames, navegador) se sincroniza con él.
"""
from __future__ import annotations

import time
from pathlib import Path

import pygame


class HeadlessAudioPlayer:
    """Reproduce un MP3/WAV con pygame.mixer.music y expone un reloj de tiempo."""

    def __init__(self):
        # mixer-only init: nada de display. Idempotente si ya estaba init.
        # Si no hay dispositivo de audio (CI/servidor sin tarjeta), caemos a
        # modo silencioso: el reloj (time.monotonic) sigue funcionando, así el
        # tick/Art-Net/streaming operan aunque no suene nada en esa máquina.
        self.silent = False
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(44100, -16, 2, 2048)
        except Exception as e:
            self.silent = True
            print(f"[audio] Sin dispositivo de audio → modo silencioso (reloj OK): {e}")
        self.audio_path: str | None = None
        self.duration: float = 0.0
        self._playing = False
        self._paused = False
        self._pause_time = 0.0       # posición congelada cuando pausado/seek
        self._start_mono = 0.0       # monotonic en el instante de play (corregido por offset)

    # ── carga ────────────────────────────────────────────────────────────────

    def load(self, audio_path, duration: float | None = None) -> bool:
        """Carga el audio. `duration` (s) evita el coste de leerlo con librosa."""
        try:
            self.audio_path = str(audio_path)
            if not self.silent:
                pygame.mixer.music.load(self.audio_path)
            if duration and duration > 0:
                self.duration = float(duration)
            else:
                import librosa
                y, sr = librosa.load(self.audio_path, sr=44100)
                self.duration = len(y) / sr
            print(f"[audio] Cargado: {Path(self.audio_path).name} ({self.duration:.1f}s)")
            return True
        except Exception as e:
            print(f"[audio] Error cargando audio: {e}")
            return False

    # ── transporte ─────────────────────────────────────────────────────────

    def play(self, at: float | None = None):
        """Reproduce desde `at` (s), o reanuda desde la posición pausada/seek."""
        if not self.audio_path:
            return
        if at is not None:
            target = max(0.0, min(float(at), self.duration))
        elif self._paused and self._pause_time < self.duration - 0.1:
            target = self._pause_time
        else:
            target = 0.0

        # SIEMPRE load + play(start=N): unpause() reanudaría desde el punto real
        # del reproductor, no desde nuestro target (que puede venir de un seek).
        if not self.silent:
            try:
                pygame.mixer.music.load(self.audio_path)
                try:
                    pygame.mixer.music.play(loops=0, start=target)
                except pygame.error:
                    pygame.mixer.music.play(loops=0)
                    try:
                        pygame.mixer.music.set_pos(target)
                    except Exception:
                        pass
                pygame.mixer.music.set_volume(1.0)
            except Exception as e:
                print(f"[audio] Error reproduciendo: {e}")
                return

        self._start_mono = time.monotonic() - target
        self._pause_time = target
        self._paused = False
        self._playing = True

    def pause(self):
        if self._playing and not self._paused:
            if not self.silent:
                pygame.mixer.music.pause()
            self._pause_time = self.get_current_time()
            self._paused = True
            self._playing = False

    def stop(self):
        if not self.silent:
            pygame.mixer.music.stop()
        self._playing = False
        self._paused = False
        self._pause_time = 0.0

    def seek(self, seconds: float):
        """Reposiciona. Si estaba sonando, sigue sonando desde el nuevo punto."""
        seconds = max(0.0, min(float(seconds), self.duration))
        was_playing = self._playing
        if was_playing:
            self.play(at=seconds)
        else:
            self._pause_time = seconds
            self._paused = True

    def set_volume(self, vol: float):
        if self.silent:
            return
        try:
            pygame.mixer.music.set_volume(max(0.0, min(1.0, float(vol))))
        except Exception:
            pass

    # ── reloj ────────────────────────────────────────────────────────────────

    def get_current_time(self) -> float:
        if self._playing:
            elapsed = time.monotonic() - self._start_mono
            if elapsed >= self.duration:
                # fin de pista: congelar al final (el tick decide loop/stop)
                return self.duration
            return elapsed
        if self._paused:
            return self._pause_time
        return 0.0

    @property
    def playing(self) -> bool:
        """True solo mientras reproduce activamente (no pausado)."""
        return self._playing

    def is_active(self) -> bool:
        """True si hay audio cargado y en play o pausa (no detenido)."""
        return self._playing or self._paused

    # ── Compat con la interfaz AudioEngine que esperan los handlers ──────────
    # (mcp_bridge habla con `app.audio` usando estos nombres)
    def get_time(self) -> float:
        return self.get_current_time()

    @property
    def duration_s(self) -> float:
        return self.duration

    @property
    def _path(self) -> str | None:
        return self.audio_path
