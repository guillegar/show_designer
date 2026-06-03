"""
Tests de Curation (curación humana sobre análisis crudo).

Cubre:
  - Set/get section labels con vocabulario híbrido + libre
  - Add manual event aparece en list_events
  - Disable event filtra de list_events
  - Round-trip persistencia (save → load) preserva todo
  - Re-cargar payload v3 con curation distinta no contamina

Lanzar:
    pytest tests/test_curation.py -v
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis.analyzer_service import (    # noqa: E402
    AnalysisService, Curation, default_service, SECTION_TYPES,
)


@pytest.fixture
def tmp_curation_path(tmp_path):
    return tmp_path / "curation.json"


@pytest.fixture
def svc():
    s = default_service()
    if not s.has_analysis:
        pytest.skip("No hay análisis disponible para tests")
    return s


# ────────────────────────────────────────────────────────────────
# Curation aislada (sin AnalysisService)
# ────────────────────────────────────────────────────────────────

def test_curation_empty_starts_clean(tmp_curation_path):
    c = Curation.load(tmp_curation_path, song_id="testsong")
    assert c.section_labels == {}
    assert c.manual_events == []
    assert c.disabled_events == []
    assert not c.dirty


def test_curation_set_section_label(tmp_curation_path):
    c = Curation(tmp_curation_path, song_id="testsong")
    c.set_section_label(3, name="Drop 1", type="drop")
    assert c.dirty
    name, type_ = c.section_label_for(3)
    assert name == "Drop 1"
    assert type_ == "drop"


def test_curation_section_label_clear(tmp_curation_path):
    c = Curation(tmp_curation_path, song_id="testsong")
    c.set_section_label(3, name="Drop 1", type="drop")
    c.set_section_label(3, name="", type="")  # clear
    assert c.section_label_for(3) == ("", "")


def test_curation_section_label_libre(tmp_curation_path):
    """Tipo libre (no en SECTION_TYPES) debe aceptarse igual."""
    c = Curation(tmp_curation_path, song_id="testsong")
    c.set_section_label(5, name="raro", type="mi_tipo_custom")
    name, type_ = c.section_label_for(5)
    assert type_ == "mi_tipo_custom"


def test_curation_add_manual_event(tmp_curation_path):
    c = Curation(tmp_curation_path, song_id="testsong")
    c.add_manual_event(64.5, "kick", name="kick fantasma")
    assert len(c.manual_events) == 1
    e = c.manual_events[0]
    assert e.kind == "kick"
    assert e.source == "manual"
    assert e.time_sec == 64.5


def test_curation_disable_event_in_tolerance(tmp_curation_path):
    c = Curation(tmp_curation_path, song_id="testsong")
    c.disable_event(time_sec=10.0, kind="kick", tolerance_ms=20)
    # Dentro de tolerancia → disabled
    assert c.is_disabled(10.005, "kick")
    assert c.is_disabled(10.020, "kick")
    # Fuera de tolerancia → no
    assert not c.is_disabled(10.050, "kick")
    # Distinto kind → no
    assert not c.is_disabled(10.005, "snare")


def test_curation_threshold_override(tmp_curation_path):
    c = Curation(tmp_curation_path, song_id="testsong")
    c.set_event_threshold("kick", 1.7)
    assert c.threshold_overrides["kick"] == 1.7


def test_curation_cue_seed(tmp_curation_path):
    c = Curation(tmp_curation_path, song_id="testsong")
    c.add_cue_seed(86.0, "drop principal")
    assert len(c.cue_seeds) == 1
    assert c.cue_seeds[0]["time_sec"] == 86.0


# ────────────────────────────────────────────────────────────────
# Round-trip persistencia
# ────────────────────────────────────────────────────────────────

def test_curation_roundtrip(tmp_curation_path):
    c = Curation(tmp_curation_path, song_id="testsong")
    c.set_section_label(0, "Intro", "intro")
    c.set_section_label(3, "Drop 1", "drop")
    c.add_manual_event(64.5, "kick", "manual1")
    c.add_manual_event(120.0, "snare", "manual2")
    c.disable_event(45.0, "hat", tolerance_ms=15)
    c.set_event_threshold("kick", 1.8)
    c.add_cue_seed(86.0, "drop")
    c.save()
    assert tmp_curation_path.is_file()

    c2 = Curation.load(tmp_curation_path, song_id="testsong")
    assert c2.section_labels[0] == {"name": "Intro", "type": "intro"}
    assert c2.section_labels[3] == {"name": "Drop 1", "type": "drop"}
    assert len(c2.manual_events) == 2
    assert c2.manual_events[0].kind == "kick"
    assert c2.disabled_events == [(45.0, "hat", 15)]
    assert c2.threshold_overrides == {"kick": 1.8}
    assert len(c2.cue_seeds) == 1


def test_curation_save_format(tmp_curation_path):
    c = Curation(tmp_curation_path, song_id="testsong")
    c.set_section_label(1, "Verso 1", "verse")
    c.save()
    data = json.loads(tmp_curation_path.read_text(encoding="utf-8"))
    assert data["version"] == Curation.SCHEMA_VERSION
    assert data["song_id"] == "testsong"
    assert isinstance(data["section_labels"], list)


# ────────────────────────────────────────────────────────────────
# Integración con AnalysisService
# ────────────────────────────────────────────────────────────────

def test_svc_disable_filters_list_events(svc, tmp_path, monkeypatch):
    # Forzamos al servicio a usar un curation.json temporal aislado
    new_cur_path = tmp_path / "curation.json"
    svc._curation = Curation(new_cur_path, song_id=svc.song_id)

    kicks_before = svc.list_events("kick", 0.0, 30.0)
    if len(kicks_before) < 2:
        pytest.skip("Pocos kicks para probar disable")

    # Disable el primero
    target = kicks_before[0]
    svc.curation.disable_event(target.time_sec, "kick", tolerance_ms=30)
    kicks_after = svc.list_events("kick", 0.0, 30.0)
    assert len(kicks_after) == len(kicks_before) - 1
    assert all(abs(e.time_sec - target.time_sec) > 0.03 for e in kicks_after)


def test_svc_manual_event_appears_in_list_events(svc, tmp_path):
    new_cur_path = tmp_path / "curation.json"
    svc._curation = Curation(new_cur_path, song_id=svc.song_id)
    n_before = len(svc.list_events("kick", 0.0, 100.0))
    svc.curation.add_manual_event(50.0, "kick", name="manual_test")
    n_after = len(svc.list_events("kick", 0.0, 100.0))
    assert n_after == n_before + 1


def test_svc_section_labels_propagate(svc, tmp_path):
    new_cur_path = tmp_path / "curation.json"
    svc._curation = Curation(new_cur_path, song_id=svc.song_id)
    svc.curation.set_section_label(3, name="Drop", type="drop")
    sec3 = next(s for s in svc.list_sections() if s.idx == 3)
    assert sec3.name == "Drop"
    assert sec3.type == "drop"
