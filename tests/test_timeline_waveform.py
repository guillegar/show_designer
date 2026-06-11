"""
test_timeline_waveform.py — ANALYSIS hallazgo 19 (split del editor).

WaveformData se extrajo de timeline_editor.py a src/ui/timeline/waveform.py.
Al ser Qt-free, ahora es importable y testeable sin PyQt5.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_waveform_imports_without_qt():
    # No debe requerir PyQt5 (la clase es pura: librosa + numpy)
    from src.ui.timeline.waveform import WaveformData
    assert WaveformData is not None


def test_waveform_handles_missing_file_gracefully():
    from src.ui.timeline.waveform import WaveformData
    w = WaveformData("__no_existe__.wav")   # librosa.load falla → se captura
    assert w.duration_s == 0.0
    assert w.peaks.shape == (1,)
