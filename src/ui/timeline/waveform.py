"""
waveform.py — WaveformData (ANALYSIS hallazgo 19, extraído de timeline_editor.py).

Calcula los picos de la forma de onda (envolvente RMS por bloques de 10 ms) de un
archivo de audio para dibujar el waveform del timeline. SIN dependencia de Qt →
importable y testeable de forma aislada.
"""
from pathlib import Path

import numpy as np
import librosa

from src.log import get_logger

_log = get_logger(__name__)


class WaveformData:
    def __init__(self, path: Path):
        self.audio_path = Path(path)
        self.duration_s = 0.0
        self.peaks = np.zeros(1, dtype=np.float32)
        self.sr = 22050
        self._load()

    def _load(self):
        _log.info("waveform %s...", self.audio_path.name)
        try:
            y, sr = librosa.load(str(self.audio_path), sr=self.sr, mono=True)
            self.duration_s = len(y) / sr
            bs = int(sr * 0.010); nb = len(y) // bs
            blk = y[:nb * bs].reshape(nb, bs)
            self.peaks = np.max(np.abs(blk), axis=1).astype(np.float32)
            self.peaks /= max(0.001, float(self.peaks.max()))
            _log.info("waveform %.1fs OK", self.duration_s)
        except Exception as e:
            _log.error("waveform error: %s", e)
