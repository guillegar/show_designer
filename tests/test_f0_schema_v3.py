"""
test_f0_schema_v3.py — ROADMAP v2, Fase F0.2: schema v3 + migración v1/v2→v3.

Invariante: cargar un show viejo NUNCA falla ni pierde datos; al re-guardar
sale como v3 con los contenedores nuevos.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.timeline_model import Clip, Timeline  # noqa: E402

FIXTURE_V2 = Path(__file__).parent / "fixtures" / "show_v2.json"


def test_carga_v2_sin_perdida():
    tl = Timeline.load(FIXTURE_V2)
    assert len(tl.clips) == 2
    assert tl.duration_ms == 273_300
    assert len(tl.groups) == 2
    # Datos intactos
    c0, c1 = tl.clips
    assert c0.label == "intro wave" and c0.params == {"hue": 220}
    assert c1.uid == "a1b2c3d4e5f6"  # uid persistido se conserva
    assert c0.uid and isinstance(c0.uid, str)  # clip legacy con id int → uid nuevo
    # Cue points del archivo (no los 9 default)
    assert tl.cue_points[0].time_ms == 52_000


def test_v2_migra_con_contenedores_vacios():
    tl = Timeline.load(FIXTURE_V2)
    assert tl.automation == []
    assert tl.patterns == []
    assert tl.pattern_instances == []
    assert tl.mixer == {}


def test_reguardar_sale_como_v3(tmp_path):
    tl = Timeline.load(FIXTURE_V2)
    out = tmp_path / "show.json"
    tl.save(out)
    data = json.loads(out.read_text(encoding="utf-8"))
    # Schema v4 desde E1 (ROADMAP v3): añade cue_list
    assert data["version"] == 4
    for key in ("automation", "patterns", "pattern_instances", "mixer", "cue_list"):
        assert key in data
    # Y los datos siguen ahí
    assert len(data["clips"]) == 2
    assert data["clips"][1]["uid"] == "a1b2c3d4e5f6"


def test_roundtrip_v3_preserva_contenedores(tmp_path):
    tl = Timeline(duration_ms=10_000)
    tl.add(Clip(track=0, start_ms=0, end_ms=1000, effect_id=0))
    tl.automation = [{"uid": "lane00000001", "target": "clip:x:hue", "points": []}]
    tl.patterns = [{"uid": "pat000000001", "name": "estribillo", "clips": []}]
    tl.pattern_instances = [{"uid": "ins000000001", "pattern_uid": "pat000000001",
                             "start_ms": 5000, "track_offset": 0}]
    tl.mixer = {"master": {"brightness": 0.8}}
    out = tmp_path / "show.json"
    tl.save(out)
    tl2 = Timeline.load(out)
    assert tl2.automation == tl.automation
    assert tl2.patterns == tl.patterns
    assert tl2.pattern_instances == tl.pattern_instances
    assert tl2.mixer == tl.mixer


def test_show_v1_sin_cues_ni_version(tmp_path):
    """v1: ni version, ni cue_points, ni groups — debe cargar con defaults."""
    v1 = {"duration_ms": 165000,
          "clips": [{"track": 1, "start_ms": 0, "end_ms": 999, "effect_id": 5}]}
    p = tmp_path / "v1.json"
    p.write_text(json.dumps(v1), encoding="utf-8")
    tl = Timeline.load(p)
    assert len(tl.clips) == 1
    assert len(tl.cue_points) == 9   # los 9 default
    assert tl.mixer == {}
