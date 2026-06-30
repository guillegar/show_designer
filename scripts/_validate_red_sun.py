#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None
sys.path.insert(0, str(Path.cwd()))

from src.analysis.analyzer_service import AnalysisService

out_dir = Path("analizadas/10-CONCEPTUAL-Red_Sun")
svc = AnalysisService(out_dir)

assert svc.has_analysis, "No analysis"
s = svc.summary
print("=" * 60)
print("RESUMEN - Red Sun")
print("=" * 60)
print(f"Duracion: {s['duration_s']:.1f}s  BPM: {s['bpm']:.1f}  beats: {s['beat_count']}")
print(f"secciones: {s['num_sections']}  timeseries: {s['has_timeseries']}")

beats = svc.list_beats()
downs = svc.list_downbeats()
print(f"\nBeats: {len(beats)}  Downbeats: {len(downs)}")

# Audio-reactive context (needs 'times')
print("\nget_audio_context (debe ser >0 en zonas con energia):")
for t in (10.0, 60.0, 120.0, 180.0, 240.0):
    ctx = svc.get_audio_context(t)
    nrms = ctx.get("norm", {}).get("rms", 0.0)
    print(f"  t={t:6.1f}s  rms={ctx.get('rms',0):.3f}  norm.rms={nrms:.3f}")

drops = svc.find_drops(0.4)
print(f"\nDrops detectados: {len(drops)}")
for d in drops[:6]:
    print(f"  [{d['idx']}] {d['start']:.1f}-{d['end']:.1f}s  jump={d.get('energy_jump_ratio',0):.2f}")

print("\nOK: analisis listo para componer.")
