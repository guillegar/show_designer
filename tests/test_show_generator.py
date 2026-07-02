"""
test_show_generator.py — Tests para generación automática de show (M2).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from server.show_generator import SOLID_COLOR_ID, STROBE_COLOR_ID, generate_show
from src.core.timeline_model import Clip

# ─── helpers ─────────────────────────────────────────────────────────────────

class _FakeSection:
    def __init__(self, start, end, name="s"):
        self.start = start; self.end = end
        self.name = name; self.type = "verse"

def _beats(bpm=120.0, n=32, offset=0.0):
    """Lista de tiempos de beat a BPM constante."""
    interval = 60.0 / bpm
    return [offset + i * interval for i in range(n)]

def _downbeats(bpm=120.0, n=8, offset=0.0):
    """Lista de downbeats (cada 4 beats)."""
    beat_interval = 60.0 / bpm
    bar_interval = beat_interval * 4
    return [offset + i * bar_interval for i in range(n)]


# ─── tests ───────────────────────────────────────────────────────────────────

def test_generate_show_no_overlap_same_layer():
    """generate_show('club', 0.5) → ningún clip se solapa en el mismo layer."""
    beats = _beats(120.0, n=32)
    dbs = _downbeats(120.0, n=8)
    sections = [_FakeSection(0, 20), _FakeSection(20, 40)]
    clips = generate_show(beats, dbs, sections, style="club", density=0.5, bpm=120.0)
    assert len(clips) > 0

    # Verificar no-solapamiento por layer
    by_layer: dict = {}
    for c in clips:
        layer = c["layer"]
        by_layer.setdefault(layer, []).append((c["start_ms"], c["end_ms"]))

    for layer, intervals in by_layer.items():
        intervals.sort()
        for i in range(len(intervals) - 1):
            s1, e1 = intervals[i]
            s2, e2 = intervals[i + 1]
            assert e1 <= s2, f"Solapamiento en layer {layer}: [{s1},{e1}) y [{s2},{e2})"


def test_generate_show_minimal_only_downbeats():
    """generate_show('minimal', 0.0) → clips SOLO en downbeats (layer 0, no hay otros)."""
    beats = _beats(120.0, n=32)
    dbs = _downbeats(120.0, n=8)
    sections = [_FakeSection(0, 40)]
    clips = generate_show(beats, dbs, sections, style="minimal", density=0.0, bpm=120.0)

    # Con density=0.0 solo debe haber layer 0 (downbeats)
    layers = {c["layer"] for c in clips}
    assert layers == {0}, f"Esperado solo layer 0, obtenido {layers}"
    # El número de clips de layer 0 debe ser <= número de downbeats
    assert len(clips) <= len(dbs)


def test_generate_show_festival_all_beats():
    """generate_show('festival', 1.0) → clips en cada beat (layer 0 + 1 + 2)."""
    beats = _beats(120.0, n=16)
    dbs = _downbeats(120.0, n=4)
    sections = [_FakeSection(0, 20)]
    clips = generate_show(beats, dbs, sections, style="festival", density=1.0, bpm=120.0)
    layers = {c["layer"] for c in clips}
    # Density>0.8 → debe haber layer 2 además de 0 y 1
    assert 2 in layers


def test_generate_show_replace_true_clears_timeline():
    """replace=True → handler limpia el timeline antes de añadir clips."""
    from server.dispatcher import Dispatcher
    from src.core.timeline_model import Clip as TClip
    from src.core.timeline_model import Timeline, make_default_groups

    # Crear sesión mínima con análisis mock
    session = MagicMock()
    session.bpm = 120.0
    session.snapshot = MagicMock()
    session.invalidate_caches = MagicMock()
    session._tokens_config = []

    # timeline real con un clip pre-existente
    tl = Timeline()
    tl.groups = make_default_groups()
    existing_clip = TClip(track=0, start_ms=0, end_ms=1000, effect_id=1004, scope="per_bar", params={})
    tl.clips.append(existing_clip)
    session.timeline = tl

    # análisis mock
    beats = _beats(120.0, n=16)
    dbs = _downbeats(120.0, n=4)
    analysis = MagicMock()
    analysis.list_beats.return_value = beats
    analysis.list_downbeats.return_value = dbs
    analysis.list_sections.return_value = [_FakeSection(0, 20)]
    session.analysis = analysis

    disp = Dispatcher(session)
    resp = disp.handle({"method": "generate_show", "params": {"style": "club", "density": 0.3, "replace": True}})
    result = resp.get("result", resp)

    assert result.get("ok") is True
    # El clip pre-existente debe haberse eliminado (replace=True)
    assert existing_clip not in tl.clips


def test_generate_show_replace_false_keeps_existing():
    """replace=False → clips añadidos sobre los existentes, no se borran."""
    from server.dispatcher import Dispatcher
    from src.core.timeline_model import Clip as TClip
    from src.core.timeline_model import Timeline, make_default_groups

    session = MagicMock()
    session.bpm = 120.0
    session.snapshot = MagicMock()
    session.invalidate_caches = MagicMock()
    session._tokens_config = []

    tl = Timeline()
    tl.groups = make_default_groups()
    existing = TClip(track=0, start_ms=999000, end_ms=1000000, effect_id=1004, scope="per_bar", params={})
    tl.clips.append(existing)
    session.timeline = tl

    beats = _beats(120.0, n=16)
    dbs = _downbeats(120.0, n=4)
    analysis = MagicMock()
    analysis.list_beats.return_value = beats
    analysis.list_downbeats.return_value = dbs
    analysis.list_sections.return_value = [_FakeSection(0, 20)]
    session.analysis = analysis

    disp = Dispatcher(session)
    resp = disp.handle({"method": "generate_show", "params": {"style": "club", "density": 0.3, "replace": False}})
    result = resp.get("result", resp)

    assert result.get("ok") is True
    # El clip pre-existente debe seguir en el timeline
    assert existing in tl.clips


def test_generated_clips_serializable():
    """Clips generados por generate_show son serializables a JSON (roundtrip)."""
    beats = _beats(120.0, n=8)
    dbs = _downbeats(120.0, n=2)
    sections = [_FakeSection(0, 10)]
    clips = generate_show(beats, dbs, sections, style="club", density=0.7, bpm=120.0)
    assert len(clips) > 0
    # Todos deben ser serializables
    serialized = json.dumps(clips)
    recovered = json.loads(serialized)
    assert len(recovered) == len(clips)
    # Campos obligatorios presentes en todos
    for c in recovered:
        assert "start_ms" in c and "end_ms" in c
        assert "effect_id" in c
        assert "layer" in c
