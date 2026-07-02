"""
Tests de los handlers MCP analyzer_* (Fase B).

Verifica el dispatcher de mcp_bridge llamando handlers directamente con un
objeto "app" mínimo que solo expone .analysis (un AnalysisService real).
No arranca el servidor WebSocket — testea solo la capa de handlers.

Lanzar:
    pytest tests/test_mcp_analyzer.py -v
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis.analyzer_service import (  # noqa: E402
    AnalysisService,
    Curation,
    default_service,
)
from src.mcp import mcp_bridge as mb  # noqa: E402


class MockApp:
    """App mínima — solo necesita el atributo `analysis`."""
    def __init__(self, svc):
        self.analysis = svc


@pytest.fixture
def app(tmp_path):
    svc = default_service()
    if not svc.has_analysis:
        pytest.skip("No hay análisis disponible")
    # Aislar curación a un tmp para no contaminar el repo
    svc._curation = Curation(tmp_path / "curation.json", song_id=svc.song_id)
    return MockApp(svc)


# ────────────────────────────────────────────────────────────────
# Reads
# ────────────────────────────────────────────────────────────────

def test_h_analyzer_summary(app):
    r = mb._h_analyzer_summary(app, {})
    assert r["available"] is True
    s = r["summary"]
    assert s["bpm"] > 0
    assert "bpm_source" in s
    assert s["num_sections"] >= 1


def test_h_analyzer_list_sections(app):
    r = mb._h_analyzer_list_sections(app, {"with_curated": True})
    assert r["count"] >= 1
    for s in r["sections"]:
        assert "idx" in s and "start" in s and "end" in s


def test_h_analyzer_list_beats(app):
    r = mb._h_analyzer_list_beats(app, {"start_sec": 0, "end_sec": 5})
    assert r["count"] >= 1
    for t in r["beats"]:
        assert 0 <= t <= 5


def test_h_analyzer_list_downbeats(app):
    r = mb._h_analyzer_list_downbeats(app, {"start_sec": 0, "end_sec": 20})
    assert "source" in r
    assert r["source"] in ("madmom", "fallback_4_4", "none")


def test_h_analyzer_list_events(app):
    r = mb._h_analyzer_list_events(app, {"kind": "kick",
                                         "start_sec": 0, "end_sec": 30})
    assert r["kind"] == "kick"
    for e in r["events"]:
        assert e["kind"] == "kick"
        assert e["source"] in ("auto", "manual")


def test_h_analyzer_list_events_missing_kind(app):
    r = mb._h_analyzer_list_events(app, {})
    assert "error" in r


def test_h_analyzer_get_features_at(app):
    r = mb._h_analyzer_get_features_at(
        app, {"time_sec": 60, "names": ["rms", "centroid"]}
    )
    assert "features" in r
    # rms puede no estar si no hay timeseries — pero el dict existe
    if "rms" in r["features"]:
        assert isinstance(r["features"]["rms"], float)


def test_h_analyzer_get_features_range_downsample(app):
    r = mb._h_analyzer_get_features_range(
        app, {"start_sec": 0, "end_sec": 30,
              "downsample_to": 40, "names": ["rms"]}
    )
    assert "times" in r
    if r["times"]:
        assert len(r["times"]) <= 41


def test_h_analyzer_find_drops(app):
    r = mb._h_analyzer_find_drops(app, {"min_energy_jump": 0.4})
    assert "drops" in r
    for d in r["drops"]:
        assert d["energy_jump_ratio"] >= 0.4


def test_h_analyzer_find_breakdowns(app):
    r = mb._h_analyzer_find_breakdowns(app, {"min_low_energy_sec": 4.0})
    assert "breakdowns" in r


def test_h_analyzer_list_stems_events_unavailable(app):
    # El Taser no tiene stems → available=False
    r = mb._h_analyzer_list_stems_events(app, {"stem": "drums"})
    assert "available" in r


# ────────────────────────────────────────────────────────────────
# Writes (curación)
# ────────────────────────────────────────────────────────────────

def test_h_analyzer_set_section_label(app):
    r = mb._h_analyzer_set_section_label(
        app, {"idx": 3, "name": "Drop", "type": "drop"}
    )
    assert r["ok"] is True
    # Verificar que la curación se aplicó
    sec3 = next(s for s in app.analysis.list_sections() if s.idx == 3)
    assert sec3.name == "Drop"
    assert sec3.type == "drop"


def test_h_analyzer_add_manual_event(app):
    n_before = len(app.analysis.list_events("kick", 0, 200))
    r = mb._h_analyzer_add_manual_event(
        app, {"time_sec": 100.0, "kind": "kick", "name": "manual_test"}
    )
    assert r["ok"] is True
    n_after = len(app.analysis.list_events("kick", 0, 200))
    assert n_after == n_before + 1


def test_h_analyzer_disable_event(app):
    kicks = app.analysis.list_events("kick", 0, 30)
    if len(kicks) < 2:
        pytest.skip("Pocos kicks para test")
    target = kicks[0]
    mb._h_analyzer_disable_event(app, {
        "time_sec": target.time_sec, "kind": "kick", "tolerance_ms": 30
    })
    kicks_after = app.analysis.list_events("kick", 0, 30)
    assert all(abs(k.time_sec - target.time_sec) > 0.03 for k in kicks_after)


def test_h_analyzer_set_event_threshold(app):
    r = mb._h_analyzer_set_event_threshold(
        app, {"kind": "kick", "value": 1.8}
    )
    assert r["ok"] is True
    assert app.analysis.curation.threshold_overrides["kick"] == 1.8


# ────────────────────────────────────────────────────────────────
# Dispatcher
# ────────────────────────────────────────────────────────────────

def test_dispatcher_routes_to_handlers(app):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "analyzer_summary",
           "params": {}}
    resp = mb._dispatch(app, msg)
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["available"] is True


def test_dispatcher_unknown_method(app):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "analyzer_doesnt_exist",
           "params": {}}
    resp = mb._dispatch(app, msg)
    assert "error" in resp
    assert resp["error"]["code"] == -32601
