#!/usr/bin/env python3
import librosa
import numpy as np

audio_path = "assets/audio/10-CONCEPTUAL-Red_Sun.mp3"

# Load audio
y, sr = librosa.load(audio_path)
duration = librosa.get_duration(y=y, sr=sr)

# Estimate BPM
onset_env = librosa.onset.onset_strength(y=y, sr=sr)
bpm = librosa.beat.tempo(onset_envelope=onset_env, sr=sr)[0]

# Analyze energy over time
S = librosa.feature.melspectrogram(y=y, sr=sr)
energy = np.mean(S, axis=0)

# Convert frames to time
times = librosa.frames_to_time(np.arange(len(energy)), sr=sr)

print("=== AUDIO ANALYSIS: 10-CONCEPTUAL-Red_Sun ===")
print(f"Duration: {duration:.2f}s ({int(duration//60)}m {int(duration%60)}s)")
print(f"BPM: {bpm:.1f}")
print(f"Sample Rate: {sr}Hz")

print("\nEnergy Stats:")
print(f"  Mean: {np.mean(energy):.3f}")
print(f"  Std Dev: {np.std(energy):.3f}")
print(f"  Min: {np.min(energy):.3f}")
print(f"  Max: {np.max(energy):.3f}")

# Spectral centroid (brightness)
spec_center = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
print(f"\nSpectral Centroid (brightness): {np.mean(spec_center):.0f} Hz")

# Detect onsets (structural changes)
onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units='time')
print("\nDetected Onsets (structural changes):")
for i, onset in enumerate(onset_frames[:15]):  # First 15
    print(f"  {onset:.2f}s")
