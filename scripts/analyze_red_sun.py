#!/usr/bin/env python3
"""
analyze_red_sun.py — Análisis profundo de "10-CONCEPTUAL-Red_Sun" (Oscar Mulero).

Genera analysis.json (schema v2) + timeseries.npz en analizadas/10-CONCEPTUAL-Red_Sun/

Motor principal: librosa (BPM, beats, onsets, energía, spectral features).
Extensiones opcionales: madmom (downbeats), demucs (stems).

Uso:
    python scripts/analyze_red_sun.py
"""
import json
import sys
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import librosa
import numpy as np

# Rutas
PROJECT_DIR = Path(__file__).resolve().parent.parent
AUDIO_PATH = PROJECT_DIR / "assets/audio/10-CONCEPTUAL-Red_Sun.mp3"
OUT_DIR = PROJECT_DIR / "analizadas/10-CONCEPTUAL-Red_Sun"
ANALYSIS_PATH = OUT_DIR / "analysis.json"
TIMESERIES_PATH = OUT_DIR / "timeseries.npz"


def compute_file_hash(fpath):
    """SHA256 del archivo."""
    with open(fpath, "rb") as f:
        return sha256(f.read()).hexdigest()


def detect_kick_snare_hats(y, sr, onset_frames):
    """
    Detección simple de kick/snare/hat por bandas de frecuencia.
    Retorna: (kick_times, snare_times, hat_times).
    """
    # Espectrograma
    S = librosa.stft(y)
    mag = np.abs(S)

    # Bandas de frecuencia
    freqs = librosa.fft_frequencies(sr=sr)
    kick_band = (freqs >= 20) & (freqs <= 150)      # <150 Hz
    snare_band = (freqs >= 150) & (freqs <= 5000)   # 150-5k Hz
    hat_band = (freqs >= 5000) & (freqs <= 20000)   # >5k Hz

    kick_energy = np.mean(mag[kick_band, :], axis=0)
    snare_energy = np.mean(mag[snare_band, :], axis=0)
    hat_energy = np.mean(mag[hat_band, :], axis=0)

    # Threshold = media + std
    kick_thresh = np.mean(kick_energy) + np.std(kick_energy)
    snare_thresh = np.mean(snare_energy) + np.std(snare_energy)
    hat_thresh = np.mean(hat_energy) + np.std(hat_energy)

    kick_frames = np.where(kick_energy > kick_thresh)[0]
    snare_frames = np.where(snare_energy > snare_thresh)[0]
    hat_frames = np.where(hat_energy > hat_thresh)[0]

    # Unificar con onsets detectados
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)

    # Simple: if onset frame está en kick_frames, es kick; si está en hat, es hat; sino snare
    kick_times = []
    snare_times = []
    hat_times = []

    for f in onset_frames:
        t = librosa.frames_to_time(f, sr=sr)
        if f in kick_frames:
            kick_times.append(float(t))
        elif f in hat_frames:
            hat_times.append(float(t))
        else:
            snare_times.append(float(t))

    return kick_times, snare_times, hat_times


def analyze_red_sun():
    """Análisis completo."""
    print(f"[*] Analizando {AUDIO_PATH}...")

    if not AUDIO_PATH.exists():
        print(f"[!] Archivo no encontrado: {AUDIO_PATH}")
        return False

    # Crear directorio de salida
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Cargar audio
    print("[*] Cargando audio...")
    y, sr = librosa.load(str(AUDIO_PATH))
    duration_s = librosa.get_duration(y=y, sr=sr)

    # BPM
    print("[*] Estimando BPM...")
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    bpm = float(librosa.beat.tempo(onset_envelope=onset_env, sr=sr)[0])

    # Beats: sintetizamos a partir del BPM
    print("[*] Sintetizando beats desde BPM...")
    beat_interval = 60.0 / bpm  # segundos por beat
    beats_librosa = np.arange(0, duration_s, beat_interval).tolist()
    beats_librosa = [float(b) for b in beats_librosa]

    # Onsets (percussive)
    print("[*] Detectando onsets...")
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
    onsets_percussive = librosa.frames_to_time(onset_frames, sr=sr).tolist()
    onsets_percussive = [float(o) for o in onsets_percussive]

    # Kick/snare/hat
    print("[*] Detectando kick/snare/hat...")
    kick_times, snare_times, hat_times = detect_kick_snare_hats(y, sr, onset_frames)

    # Loudness RMS
    print("[*] Calculando loudness...")
    rms = librosa.feature.rms(y=y)[0]
    loudness_rms_db = float(20 * np.log10(np.mean(rms) + 1e-10))
    peak_amplitude = float(np.max(np.abs(y)))

    # Spectral features
    print("[*] Calculando features espectrales...")
    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    spectral_centroid_mean_hz = float(np.mean(spectral_centroid))

    zcr = librosa.feature.zero_crossing_rate(y)[0]
    zcr_mean = float(np.mean(zcr))

    S = librosa.feature.melspectrogram(y=y, sr=sr)
    S_db = librosa.power_to_db(S, ref=np.max)
    spectral_flatness = np.mean(10 ** (S_db / 10), axis=0)  # aprox
    spectral_flatness_mean = float(np.mean(spectral_flatness))

    # Key detection (intent a usar essentia, pero fallback simple)
    key_info = {
        "tonic": "?",
        "mode": "?",
        "confidence": 0.0
    }
    try:
        import essentia.standard as es
        profile = es.KeyExtractor()(y)
        key_info = {
            "tonic": profile[0],
            "mode": profile[1],
            "confidence": float(profile[2])
        }
        print(f"[+] Key detectada: {key_info['tonic']} {key_info['mode']}")
    except ImportError:
        print("[!] essentia no disponible, key = ?")
    except Exception as e:
        print(f"[!] Error en key detection: {e}")

    # Timeseries (energía frame a frame)
    print("[*] Generando timeseries...")
    melspec = librosa.feature.melspectrogram(y=y, sr=sr)
    energy_frames = np.mean(melspec, axis=0)

    # Flux (cambio de espectro)
    flux = np.sqrt(np.sum(np.diff(melspec, axis=1) ** 2, axis=0))
    flux = np.concatenate([[0], flux])  # Match length

    # RMS por frame
    rms_frames = librosa.feature.rms(y=y)[0]

    # Spectral centroid por frame
    sc_frames = librosa.feature.spectral_centroid(y=y, sr=sr)[0]

    # Alinear todas las series a una longitud común (hop_length=512 por defecto,
    # pero distintas features pueden diferir en 1-2 frames → truncar al mínimo).
    n = min(len(energy_frames), len(flux), len(rms_frames), len(sc_frames))
    energy_frames = energy_frames[:n]
    flux = flux[:n]
    rms_frames = rms_frames[:n]
    sc_frames = sc_frames[:n]

    # Eje temporal real (segundos) por frame → IMPRESCINDIBLE para que
    # AnalysisService.get_audio_context(t) y los efectos audio-reactivos funcionen.
    times = librosa.frames_to_time(np.arange(n), sr=sr).astype(np.float32)

    # Normalizar a [0, 1] para compatibilidad
    energy_norm = (energy_frames - np.min(energy_frames)) / (np.max(energy_frames) - np.min(energy_frames) + 1e-10)
    flux_norm = (flux - np.min(flux)) / (np.max(flux) - np.min(flux) + 1e-10)
    rms_norm = (rms_frames - np.min(rms_frames)) / (np.max(rms_frames) - np.min(rms_frames) + 1e-10)
    sc_norm = (sc_frames - np.min(sc_frames)) / (np.max(sc_frames) - np.min(sc_frames) + 1e-10)

    # Guardar timeseries (con 'times' + alias 'centroid' para AnalysisService)
    np.savez(
        str(TIMESERIES_PATH),
        times=times,
        energy=energy_norm,
        flux=flux_norm,
        rms=rms_norm,
        spectral_centroid=sc_norm,
        centroid=sc_norm,
    )
    print(f"[+] Timeseries guardado: {TIMESERIES_PATH}  ({n} frames, times 0..{times[-1]:.1f}s)")

    # Detección de secciones (simple: cambios bruscos de energía)
    print("[*] Detectando secciones...")
    energy_mean = np.mean(energy_frames)
    energy_std = np.std(energy_frames)
    threshold = energy_mean

    section_boundaries = [0.0]
    for i in range(1, len(energy_frames) - 1):
        # Si hay cambio brusco de energía, es frontera de sección
        if (energy_frames[i] > threshold and energy_frames[i-1] <= threshold) or \
           (energy_frames[i] <= threshold and energy_frames[i-1] > threshold):
            t = librosa.frames_to_time(i, sr=sr)
            section_boundaries.append(float(t))

    section_boundaries.append(duration_s)
    section_boundaries = sorted(list(set(section_boundaries)))  # Unificar

    # Limitar número de secciones (máx 20 para no ser excesivo)
    if len(section_boundaries) > 20:
        # Muestrear uniformemente
        indices = np.linspace(0, len(section_boundaries) - 1, 20, dtype=int)
        section_boundaries = [section_boundaries[i] for i in indices]

    sections = []
    for i in range(len(section_boundaries) - 1):
        start = section_boundaries[i]
        end = section_boundaries[i + 1]
        # Energía promedio en la sección
        start_frame = librosa.time_to_frames(start, sr=sr)
        end_frame = librosa.time_to_frames(end, sr=sr)
        section_energy = float(np.mean(energy_frames[start_frame:end_frame])) if start_frame < end_frame else 0.0

        sections.append({
            "index": i,
            "start": start,
            "end": end,
            "energy": section_energy,
            "label": f"section_{i}",
        })

    # Construir events_percussive (dict con arrays de start/end/duration)
    # Estimamos duración ~50ms por evento
    event_duration = 0.05
    events_percussive = {
        "kick": [{"start": t, "end": t + event_duration, "duration": event_duration} for t in kick_times],
        "snare": [{"start": t, "end": t + event_duration, "duration": event_duration} for t in snare_times],
        "hat": [{"start": t, "end": t + event_duration, "duration": event_duration} for t in hat_times],
    }
    events_by_band = {}  # Placeholder
    events_harmonic = {}  # No harmonic detection por ahora

    # Onsets (listas de timestamps)
    all_onsets = sorted(onsets_percussive)
    onsets = {
        "all": all_onsets,
        "percussive": onsets_percussive,
        "harmonic": [],
    }

    analysis = {
        "schema_version": 2,
        "file": AUDIO_PATH.name,
        "sha256": compute_file_hash(AUDIO_PATH),
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "duration_s": float(duration_s),
        "sample_rate": int(sr),
        "global": {
            "bpm_librosa": bpm,
            "bpm_madmom": None,
            "beat_count_librosa": len(beats_librosa),
            "beat_count_madmom": 0,
            "downbeat_count_madmom": 0,
            "key": key_info,
            "loudness_rms_db": loudness_rms_db,
            "peak_amplitude": peak_amplitude,
            "spectral_centroid_mean_hz": spectral_centroid_mean_hz,
            "zcr_mean": zcr_mean,
            "spectral_flatness_mean": spectral_flatness_mean,
        },
        "beats_librosa": beats_librosa,
        "beats_madmom": [],
        "downbeats_madmom": [],
        "sections": sections,
        "onsets": onsets,
        "events_by_band": events_by_band,
        "events_percussive": events_percussive,
        "events_harmonic": events_harmonic,
        "stems": {},  # Sin demucs
        "piano_roll": {},  # Sin basic-pitch
        "lyrics": {},  # Sin whisper
        "cues_manual": [],
        "files": {
            "analysis": str(ANALYSIS_PATH),
            "timeseries": str(TIMESERIES_PATH)
        }
    }

    # Guardar analysis.json
    with open(ANALYSIS_PATH, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2)
    print(f"[+] Analysis guardado: {ANALYSIS_PATH}")

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("ANALYZE RED SUN")
    print("=" * 60)
    print()

    success = analyze_red_sun()

    if success:
        print()
        print("[OK] Análisis completado.")
        print(f"  - {ANALYSIS_PATH}")
        print(f"  - {TIMESERIES_PATH}")
        sys.exit(0)
    else:
        print()
        print("[!] Error en análisis.")
        sys.exit(1)
