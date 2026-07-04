"""
tests/test_exporter.py — Tests de los exportadores (v1.8 F5)
"""
import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.core.timeline_model import BarGroup, Clip, CuePoint, Timeline

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_timeline() -> Timeline:
    tl = Timeline(duration_ms=120_000)
    tl.clips = [
        Clip(track=0, start_ms=0,     end_ms=5000,  effect_id=0,  scope='per_bar', label='Flash',  color='#ff0000'),
        Clip(track=1, start_ms=5000,  end_ms=10000, effect_id=10, scope='per_bar', label='Wave',   color='#00ff00', layer=1),
        Clip(track=0, start_ms=10000, end_ms=15000, effect_id=20, scope='global',  label='Grad',   color='#0000ff', locked=True),
        Clip(track=-1, start_ms=0,    end_ms=8000,  effect_id=0,  scope='fixture:mover_L',
             category='position', channel_effect_id='mover_circle', label=''),
    ]
    tl.cue_points = [
        CuePoint(slot=0, time_ms=0,     name='Intro'),
        CuePoint(slot=1, time_ms=30000, name='Drop'),
        CuePoint(slot=2, time_ms=90000, name='Outro'),
    ]
    tl.groups = [BarGroup(name='IZQ', bars=[0,1,2,3,4])]
    return tl


# ── 1. CSV Clips ──────────────────────────────────────────────────────────────

def test_export_clips_csv_creates_file(tmp_path):
    from src.io.exporter import export_clips_csv
    tl = _make_timeline()
    out = tmp_path / 'clips.csv'
    n = export_clips_csv(tl, out)
    assert out.is_file()
    assert n == 4   # 4 clips


def test_export_clips_csv_columns(tmp_path):
    from src.io.exporter import export_clips_csv
    tl = _make_timeline()
    out = tmp_path / 'clips.csv'
    export_clips_csv(tl, out)
    with open(out, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 4
    # Columnas esperadas
    for col in ('clip_id', 'track', 'start_ms', 'end_ms', 'duration_ms',
                'effect_id', 'category', 'channel_effect_id', 'scope',
                'label', 'color', 'locked', 'muted', 'params_json'):
        assert col in rows[0], f"Falta columna '{col}'"


def test_export_clips_csv_values(tmp_path):
    from src.io.exporter import export_clips_csv
    tl = _make_timeline()
    out = tmp_path / 'clips.csv'
    export_clips_csv(tl, out)
    with open(out, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    # Clips ordenados por start_ms
    assert int(rows[0]['start_ms']) == 0
    assert rows[0]['label'] in ('Flash', '')   # primer clip puede ser Flash o el channel clip
    # Clip bloqueado
    locked_rows = [r for r in rows if r['locked'] == '1']
    assert len(locked_rows) == 1


def test_export_clips_csv_channel_clip(tmp_path):
    """Los clips de canal exportan category y channel_effect_id correctamente."""
    from src.io.exporter import export_clips_csv
    tl = _make_timeline()
    out = tmp_path / 'clips.csv'
    export_clips_csv(tl, out)
    with open(out, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    channel_rows = [r for r in rows if r['category'] == 'position']
    assert len(channel_rows) == 1
    assert channel_rows[0]['channel_effect_id'] == 'mover_circle'


def test_export_clips_csv_empty_timeline(tmp_path):
    """Timeline vacío exporta solo la cabecera."""
    from src.io.exporter import export_clips_csv
    tl = Timeline(duration_ms=60000)
    out = tmp_path / 'empty.csv'
    n = export_clips_csv(tl, out)
    assert n == 0
    with open(out, encoding='utf-8') as f:
        lines = f.readlines()
    assert len(lines) == 1   # solo cabecera


def test_export_clips_csv_params_json(tmp_path):
    """Los params se exportan como JSON valido."""
    from src.io.exporter import export_clips_csv
    tl = Timeline(duration_ms=60000)
    tl.clips = [
        Clip(track=0, start_ms=0, end_ms=1000, effect_id=1,
             params={'hue': 200, 'saturation': 0.9}),
    ]
    out = tmp_path / 'params.csv'
    export_clips_csv(tl, out)
    with open(out, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        row = next(reader)
    params = json.loads(row['params_json'])
    assert params['hue'] == 200
    assert params['saturation'] == pytest.approx(0.9)


# ── 2. QLC+ XML ──────────────────────────────────────────────────────────────

def test_export_qlc_creates_file(tmp_path):
    from src.io.exporter import export_qlc_workspace
    tl = _make_timeline()
    out = tmp_path / 'show.qxw'
    stats = export_qlc_workspace(tl, None, out)
    assert out.is_file()
    assert stats['scenes'] == 3   # 3 cue points
    assert stats['chaser_steps'] == 3


def test_export_qlc_valid_xml(tmp_path):
    from src.io.exporter import export_qlc_workspace
    tl = _make_timeline()
    out = tmp_path / 'show.qxw'
    export_qlc_workspace(tl, None, out)
    # Debe parsear sin errores
    tree = ET.parse(str(out))
    root = tree.getroot()
    assert 'Workspace' in root.tag


_QLC_NS = 'http://www.qlcplus.org/Workspace'


def _iter_functions(root):
    """Itera los elementos Function del XML (con o sin namespace)."""
    results = list(root.iter(f'{{{_QLC_NS}}}Function'))
    if not results:
        results = list(root.iter('Function'))
    return results


def test_export_qlc_has_functions(tmp_path):
    from src.io.exporter import export_qlc_workspace
    tl = _make_timeline()
    out = tmp_path / 'show.qxw'
    export_qlc_workspace(tl, None, out)
    tree = ET.parse(str(out))
    root = tree.getroot()
    # Debe haber funciones: 3 scenes + 1 chaser
    functions = _iter_functions(root)
    assert len(functions) >= 4   # 3 scenes + 1 chaser


def test_export_qlc_chaser_steps(tmp_path):
    """El Chaser tiene tantos steps como cues."""
    from src.io.exporter import export_qlc_workspace
    tl = _make_timeline()
    out = tmp_path / 'show.qxw'
    stats = export_qlc_workspace(tl, None, out)
    tree = ET.parse(str(out))
    root = tree.getroot()

    # Buscar el chaser (Function Type="Chaser")
    chaser = None
    for fn in _iter_functions(root):
        if fn.get('Type') == 'Chaser':
            chaser = fn
            break
    assert chaser is not None, "Debe haber un Function de tipo Chaser"
    # Steps con o sin namespace
    ns_step = f'{{{_QLC_NS}}}Step'
    steps = list(chaser.iter(ns_step))
    if not steps:
        steps = list(chaser.iter('Step'))
    assert len(steps) == 3


def test_export_qlc_no_cues_uses_defaults(tmp_path):
    """Sin cue points, exporta Inicio+Fin como scenes."""
    from src.io.exporter import export_qlc_workspace
    tl = Timeline(duration_ms=60000)
    # Sin cue_points (None o [])
    tl.cue_points = []
    tl.clips = [Clip(track=0, start_ms=0, end_ms=5000, effect_id=0)]
    out = tmp_path / 'nocues.qxw'
    stats = export_qlc_workspace(tl, None, out)
    assert stats['scenes'] == 2   # Inicio + Fin


def test_export_qlc_with_rig(tmp_path):
    """Con rig, los fixtures aparecen en el XML."""
    from core.fixtures import Fixture, FixtureRig
    from src.io.exporter import export_qlc_workspace

    tl = _make_timeline()
    # Usar el rig real si existe
    rig_file = Path(__file__).parent.parent / 'fixtures.json'
    try:
        rig = FixtureRig.load(rig_file) if rig_file.is_file() else None
    except (FileNotFoundError, OSError):
        rig = None

    out = tmp_path / 'withrig.qxw'
    stats = export_qlc_workspace(tl, rig, out)
    if rig is not None:
        assert stats['fixtures'] == len(rig.fixtures)

    # El XML debe parsear
    ET.parse(str(out))


def test_export_qlc_song_name_in_chaser(tmp_path):
    """El nombre del show aparece en el Chaser."""
    from src.io.exporter import export_qlc_workspace
    tl = _make_timeline()
    out = tmp_path / 'named.qxw'
    export_qlc_workspace(tl, None, out, song_name='Mi Show')
    tree = ET.parse(str(out))
    root = tree.getroot()
    chaser_found = False
    for fn in _iter_functions(root):
        if fn.get('Type') == 'Chaser' and 'Mi Show' in (fn.get('Name') or ''):
            chaser_found = True
            break
    assert chaser_found, "El nombre 'Mi Show' debe estar en el Chaser"
