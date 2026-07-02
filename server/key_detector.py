"""
key_detector.py — Detección de tonalidad musical (M1).

Función pura, diseñada para correr en executor (puede tardar varios segundos).
Usa librosa chroma + votación de Krumhansl-Schmuckler.
Devuelve: {key: "A", mode: "major"|"minor", confidence: 0.0..1.0}
Sin librosa o audio inexistente → {error: "..."} sin crash (I4/I6).
"""
from __future__ import annotations

import os

# Perfiles de Krumhansl-Schmuckler para mayor y menor
_MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _ks_score(chroma: list, profile: list) -> list:
    """Correlación de Krumhansl-Schmuckler para las 12 rotaciones."""
    import statistics
    scores = []
    n = len(profile)
    mean_c = statistics.mean(chroma)
    mean_p = statistics.mean(profile)
    for rot in range(n):
        rotated = profile[rot:] + profile[:rot]
        num = sum((c - mean_c) * (p - mean_p) for c, p in zip(chroma, rotated))
        denom_c = sum((c - mean_c) ** 2 for c in chroma) ** 0.5
        denom_p = sum((p - mean_p) ** 2 for p in rotated) ** 0.5
        if denom_c * denom_p == 0:
            scores.append(0.0)
        else:
            scores.append(num / (denom_c * denom_p))
    return scores


def detect_key(audio_path: str) -> dict:
    """
    Detecta la tonalidad del archivo de audio.

    Devuelve: {key: str, mode: "major"|"minor", confidence: float}
    o {error: str} si falla (I4).
    """
    if not os.path.isfile(audio_path):
        return {"error": f"not found: {audio_path}"}
    try:
        import librosa  # type: ignore
        import numpy as np
    except ImportError:
        return {"error": "librosa no instalado"}

    try:
        y, sr = librosa.load(audio_path, sr=None, mono=True, duration=60.0)
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        mean_chroma = chroma.mean(axis=1).tolist()

        major_scores = _ks_score(mean_chroma, _MAJOR_PROFILE)
        minor_scores = _ks_score(mean_chroma, _MINOR_PROFILE)

        best_major_idx = major_scores.index(max(major_scores))
        best_minor_idx = minor_scores.index(max(minor_scores))
        best_major_score = major_scores[best_major_idx]
        best_minor_score = minor_scores[best_minor_idx]

        if best_major_score >= best_minor_score:
            key = _NOTE_NAMES[best_major_idx]
            mode = "major"
            confidence = round(float(best_major_score), 3)
        else:
            key = _NOTE_NAMES[best_minor_idx]
            mode = "minor"
            confidence = round(float(best_minor_score), 3)

        return {"key": key, "mode": mode, "confidence": confidence}
    except Exception as e:
        return {"error": str(e)}
