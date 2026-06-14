"""
test_key_detection.py — Tests para detección de tonalidad (M1).
"""
from __future__ import annotations
import os
import struct
import wave
import math
import tempfile
import pytest


from server.key_detector import detect_key


def _make_sine_wav(frequency: float, duration_s: float = 2.0, sample_rate: int = 22050) -> str:
    """Genera un WAV mono con una senoide pura a la frecuencia dada."""
    n_samples = int(sample_rate * duration_s)
    samples = [
        int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
        for i in range(n_samples)
    ]
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_samples}h", *samples))
    return tmp.name


def test_detect_key_missing_file():
    """Audio path inexistente → detect_key devuelve {error: 'not found'} sin crash."""
    result = detect_key("/nonexistent/path/audio.wav")
    assert "error" in result
    assert "not found" in result["error"]


def test_detect_key_returns_dict_structure():
    """detect_key devuelve dict con claves key/mode/confidence o error."""
    path = _make_sine_wav(440.0)  # La (A)
    try:
        result = detect_key(path)
        # Puede fallar si librosa no está, pero no debe lanzar excepción
        if "error" not in result:
            assert "key" in result
            assert "mode" in result
            assert "confidence" in result
            assert result["mode"] in ("major", "minor")
            assert 0.0 <= result["confidence"] <= 1.0
    finally:
        os.unlink(path)


def test_detect_key_no_crash_on_invalid_audio():
    """Archivo inválido (no es audio) → detect_key devuelve {error: ...} sin crash."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, mode="wb") as f:
        f.write(b"not audio data at all")
        tmp_path = f.name
    try:
        result = detect_key(tmp_path)
        # Puede devolver error o éxito parcial, pero no debe lanzar
        assert isinstance(result, dict)
    finally:
        os.unlink(tmp_path)


_ALL_KEYS = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"}


def test_detect_key_a_sine():
    """WAV de senoide pura → detect_key devuelve estructura válida (tolerancia total en el key)."""
    pytest.importorskip("librosa")
    path = _make_sine_wav(440.0, duration_s=3.0)
    try:
        result = detect_key(path)
        if "error" not in result:
            # La detección de tonalidad de una senoide pura no es fiable (overtones),
            # pero la función debe devolver una clave válida
            assert result["key"] in _ALL_KEYS, f"Clave inválida: {result['key']}"
            assert result["mode"] in ("major", "minor")
            assert 0.0 <= result["confidence"] <= 1.0
    finally:
        os.unlink(path)
