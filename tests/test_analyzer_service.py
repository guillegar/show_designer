"""
Tests de analyzer_service.AnalysisService.

Cubre:
  - Migración v1 (bad_guy, lola_santa) → v3
  - Migración v2 (El Taser) → v3
  - Carga de payload + validación de campos requeridos
  - list_sections, list_beats, list_downbeats, list_events
  - features_at, features_range con downsample
  - find_drops y find_breakdowns sobre el show actual
  - get_audio_context (compat con efectos antiguos)

Lanzar:
    pytest tests/test_analyzer_service.py -v
"""
import sys
from pathlib import Path

import numpy as np
import pytest

# Permitir importar desde la raíz del repo
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis.analyzer_service import (   # noqa: E402
    AnalysisService, default_service, detect_schema_version, migrate_to_v3,
    ANALIZADAS_DIR, SECTION_TYPES,
)


# ────────────────────────────────────────────────────────────────
# Detección de schema_version
# ────────────────────────────────────────────────────────────────

def test_detect_schema_version_v1():
    payload = {"beats": [], "global": {"bpm": 128}}
    assert detect_schema_version(payload) == 1


def test_detect_schema_version_v2():
    payload = {"beats_librosa": [], "global": {"bpm_librosa": 128}}
    assert detect_schema_version(payload) == 2


def test_detect_schema_version_explicit():
    payload = {"schema_version": 3, "beats": []}
    assert detect_schema_version(payload) == 3


def test_detect_schema_version_unknown():
    assert detect_schema_version({"foo": "bar"}) == 0


# ────────────────────────────────────────────────────────────────
# Migración
# ────────────────────────────────────────────────────────────────

def _v1_payload():
    return {
        "schema_version": 1,
        "file": "test.mp3",
        "sha256": "abc123def" + "0" * 55,
        "duration_s": 100.0,
        "sample_rate": 44100,
        "global": {"bpm": 120.0, "beat_count": 200, "key": {"tonic": "C", "mode": "major"}},
        "beats": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
        "downbeats": [0.5, 2.5],
        "sections": [{"index": 0, "start": 0, "end": 100, "label": "section_0"}],
        "onsets": {"all": [0.5, 1.0], "percussive": [0.5], "harmonic": [1.0]},
        "events_by_band": {"bass": [{"start": 1.0, "end": 1.5, "duration": 0.5}]},
        "events_percussive": {"kick": [{"start": 0.5, "end": 0.6, "duration": 0.1}]},
        "events_harmonic": {"bass_notes": []},
    }


def _v2_payload(with_madmom=False):
    return {
        "schema_version": 2,
        "file": "test.mp3",
        "sha256": "deadbeef" + "0" * 56,
        "duration_s": 100.0,
        "sample_rate": 48000,
        "global": {
            "bpm_librosa": 128.0,
            "bpm_madmom": 128.5 if with_madmom else None,
            "beat_count_librosa": 200,
            "key": {"tonic": "D", "mode": "minor"},
        },
        "beats_librosa": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
        "beats_madmom": [0.51, 1.01, 1.51, 2.01] if with_madmom else [],
        "downbeats_madmom": [0.51, 2.01] if with_madmom else [],
        "sections": [{"index": 0, "start": 0, "end": 100, "label": "section_0"}],
        "onsets": {"all": [0.5], "percussive": [], "harmonic": []},
        "events_by_band": {"bass": []},
        "events_percussive": {"kick": []},
        "events_harmonic": {"bass_notes": []},
    }


def test_migrate_v1_to_v3_basic():
    out = migrate_to_v3(_v1_payload())
    assert out["schema_version"] == 3
    assert out["global"]["bpm"] == 120.0
    assert out["global"]["bpm_source"] == "librosa"
    assert out["global"]["downbeats_source"] == "fallback_4_4"
    assert out["beats"] == [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    assert out["downbeats"] == [0.5, 2.5]
    # Eventos planos
    assert "events" in out
    assert "kick" in out["events"]
    assert "bass" in out["events"]
    assert "bass_notes" in out["events"]
    # song_id derivado del sha
    assert out["song_id"] == "abc123def000"


def test_migrate_v2_madmom_unreliable():
    out = migrate_to_v3(_v2_payload(with_madmom=False))
    assert out["global"]["bpm"] == 128.0
    assert out["global"]["bpm_source"] == "librosa"
    assert out["global"]["downbeats_source"] == "fallback_4_4"
    # downbeats fallback: cada 4º beat
    assert out["downbeats"] == [0.5, 2.5]


def test_migrate_v2_madmom_available():
    out = migrate_to_v3(_v2_payload(with_madmom=True))
    assert out["global"]["bpm"] == 128.5
    assert out["global"]["bpm_source"] == "madmom"
    assert out["global"]["downbeats_source"] == "madmom"
    assert out["downbeats"] == [0.51, 2.01]


def test_migrate_v3_is_passthrough():
    v3 = migrate_to_v3(_v2_payload(with_madmom=True))
    v3_again = migrate_to_v3(v3)
    assert v3 == v3_again


# ────────────────────────────────────────────────────────────────
# Carga del payload real (El Taser, v2 en disco)
# ────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    s = default_service()
    if not s.has_analysis:
        pytest.skip("No hay análisis de El Taser disponible")
    return s


def test_svc_summary_keys(svc):
    s = svc.summary
    for k in ("bpm", "bpm_source", "beat_count", "downbeats_source",
             "duration_s", "num_sections", "song_id"):
        assert k in s, f"Falta clave {k!r} en summary"


def test_svc_summary_values(svc):
    s = svc.summary
    assert s["bpm"] > 0
    assert s["bpm_source"] in ("librosa", "madmom")
    assert s["downbeats_source"] in ("madmom", "fallback_4_4", "none")
    assert s["duration_s"] > 0
    assert s["num_sections"] >= 1


def test_svc_list_sections_returns_dataclasses(svc):
    secs = svc.list_sections()
    assert len(secs) >= 1
    for s in secs:
        assert s.start <= s.end
        assert s.duration >= 0
        assert s.label.startswith("section_")


def test_svc_list_beats_range(svc):
    all_beats = svc.list_beats()
    sub = svc.list_beats(0.0, 10.0)
    assert len(sub) <= len(all_beats)
    for t in sub:
        assert 0.0 <= t <= 10.0


def test_svc_list_downbeats_smaller_than_beats(svc):
    n_beats = len(svc.list_beats())
    n_db = len(svc.list_downbeats())
    # downbeats es subset (1/4 en fallback)
    assert n_db <= n_beats


def test_svc_list_events_kick(svc):
    kicks = svc.list_events("kick", 0.0, 30.0)
    for e in kicks:
        assert e.kind == "kick"
        assert e.source in ("auto", "manual")
        assert 0.0 <= e.time_sec <= 30.0


def test_svc_list_events_onsets(svc):
    onsets = svc.list_events("onsets_all", 0.0, 5.0)
    for e in onsets:
        assert e.kind == "onsets_all"


def test_svc_features_at(svc):
    feats = svc.features_at(60.0, names=["rms", "centroid"])
    if not feats:
        pytest.skip("Sin timeseries")
    assert "rms" in feats
    assert isinstance(feats["rms"], float)
    assert feats["rms"] >= 0.0


def test_svc_features_range_downsample(svc):
    out = svc.features_range(0.0, 30.0, downsample_to=50, names=["rms"])
    if not out["features"]:
        pytest.skip("Sin timeseries")
    assert len(out["times"]) <= 51  # +1 por la última muestra
    assert "rms" in out["features"]
    assert len(out["features"]["rms"]) == len(out["times"])


def test_svc_find_drops(svc):
    drops = svc.find_drops(min_energy_jump=0.4)
    # Si la canción tiene drops, deberían detectarse al menos algunos
    for d in drops:
        assert d["energy_jump_ratio"] >= 0.4
        assert "idx" in d and "start" in d


def test_svc_find_breakdowns(svc):
    bdwn = svc.find_breakdowns(min_low_energy_sec=4.0)
    for b in bdwn:
        assert b["duration"] >= 4.0


def test_svc_get_audio_context_has_keys(svc):
    ctx = svc.get_audio_context(60.0)
    for k in ("rms", "centroid", "flux", "zcr", "mfcc", "chroma"):
        assert k in ctx
    # MFCC siempre array de 13 elementos
    assert len(ctx["mfcc"]) == 13


def test_svc_get_audio_context_dtempo_wired(svc):
    """Fase D: dtempo debe estar expuesto en audio_context."""
    ctx = svc.get_audio_context(60.0)
    assert "dtempo" in ctx, "dtempo no expuesto"
    # En la canción real debería rondar la BPM
    assert ctx["dtempo"] > 0


# ────────────────────────────────────────────────────────────────
# Versionado v1 (bad_guy, lola_santa) si existen
# ────────────────────────────────────────────────────────────────

def test_load_v1_billie_eilish():
    p = ANALIZADAS_DIR / "billie_eilish_bad_guy"
    if not (p / "analysis.json").is_file():
        pytest.skip("bad_guy no analizado")
    svc = AnalysisService(p)
    s = svc.summary
    assert s["schema_version"] == 3   # migrado al vuelo
    assert s["bpm"] > 0
    assert s["downbeats_source"] in ("fallback_4_4", "madmom", "none")


def test_load_v1_lola_santa():
    p = ANALIZADAS_DIR / "lola_indigo_la_santa"
    if not (p / "analysis.json").is_file():
        pytest.skip("lola_santa no analizado")
    svc = AnalysisService(p)
    assert svc.summary["schema_version"] == 3
