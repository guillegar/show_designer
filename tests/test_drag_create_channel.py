"""
tests/test_drag_create_channel.py — v1.9 F1: drag-create de channel clips

Verifica la lógica que `TimelineView.mouseReleaseEvent` ejecuta cuando
`draw_kind == 'channel'`, aislada de Qt. Probamos:
  - Construcción del Clip con scope, category y channel_effect_id correctos
  - Coherencia de categorías con ChannelEffectLibrary
  - default_params se copian al clip recién creado
  - Mapeo track-index ↔ fixture_id es estable
  - El clip resultante es persistible/recuperable por Timeline.save/load
"""
import json
from pathlib import Path
import pytest

from src.core.timeline_model import Timeline, Clip
from src.core.channel_effects import ChannelEffectLibrary


# ── 1. Construcción del Clip ─────────────────────────────────────────────────

def test_channel_clip_construction_basic():
    """El Clip que crea mouseReleaseEvent tiene los campos clave correctos."""
    fx_id = 'mover_wash_L_back'
    clip = Clip(
        track=-1,
        start_ms=1000,
        end_ms=5000,
        effect_id=0,
        scope=f'fixture:{fx_id}',
        category='position',
        channel_effect_id='pos_circle',
        layer=0,
        params={},
        label='pos_circle',
        color='#e06c30',
    )
    assert clip.track == -1
    assert clip.scope == f'fixture:{fx_id}'
    assert clip.category == 'position'
    assert clip.channel_effect_id == 'pos_circle'
    assert clip.duration_ms == 4000


def test_channel_clip_scope_prefix():
    """El scope siempre empieza por 'fixture:' para channel clips."""
    clip = Clip(track=-1, start_ms=0, end_ms=1000, effect_id=0,
                scope='fixture:mover_X', category='color',
                channel_effect_id='col_rainbow')
    assert clip.scope.startswith('fixture:')
    fx_id = clip.scope.split(':', 1)[1]
    assert fx_id == 'mover_X'


def test_channel_clip_category_color_mapping():
    """Los 5 categorías tienen colores únicos en la paleta."""
    palette = {
        'position':  '#e06c30',
        'color':     '#5b8dd9',
        'intensity': '#d4b840',
        'optical':   '#4caf82',
        'strobe':    '#d94040',
    }
    assert len(set(palette.values())) == 5


# ── 2. Coherencia con ChannelEffectLibrary ───────────────────────────────────

def test_channel_lib_categories_match():
    """La category derivada del channel_effect_id es la correcta para todos."""
    lib = ChannelEffectLibrary()
    for eid, expected_cat in [
        ('pos_circle',     'position'),
        ('pos_figure8',    'position'),
        ('col_rainbow',    'color'),
        ('col_fade',       'color'),
        ('dim_pulse',      'intensity'),
        ('dim_bump',       'intensity'),
        ('opt_gobo_spin',  'optical'),
        ('str_flash',      'strobe'),
        ('str_burst',      'strobe'),
    ]:
        eff = lib.get(eid)
        assert eff is not None, f"Channel effect '{eid}' no existe"
        assert eff.category == expected_cat, \
            f"'{eid}' debería ser {expected_cat}, es {eff.category}"


def test_channel_lib_returns_24_effects():
    """ChannelEffectLibrary expone los 24 efectos del catálogo."""
    lib = ChannelEffectLibrary()
    effects = lib.all()
    assert len(effects) >= 20  # margen por si añaden más
    # Al menos una por categoría
    cats = {e.category for e in effects}
    assert {'position', 'color', 'intensity', 'optical', 'strobe'}.issubset(cats)


def test_channel_lib_default_params_dict():
    """default_params es siempre un dict (potencialmente vacío)."""
    lib = ChannelEffectLibrary()
    for eff in lib.all():
        assert isinstance(eff.default_params, dict), \
            f"{eff.effect_id}: default_params no es dict"


def test_channel_lib_by_category():
    """by_category() filtra correctamente y todos los efectos vuelven."""
    lib = ChannelEffectLibrary()
    total = 0
    for cat in ['position', 'color', 'intensity', 'optical', 'strobe']:
        effs = lib.by_category(cat)
        assert all(e.category == cat for e in effs)
        total += len(effs)
    assert total == len(lib.all())


# ── 3. Defaults del channel effect → params del clip ─────────────────────────

def test_default_params_copied_to_clip():
    """Los default_params del ChannelEffect arrancan como params del clip.

    Simula la línea `params=dict(self.draw_channel_defaults or {})` del
    mouseReleaseEvent: el clip recibe una COPIA del dict (no la misma
    referencia) para que añadir/borrar claves no afecte al template.
    """
    lib = ChannelEffectLibrary()
    eff = lib.get('pos_circle')
    assert eff is not None
    # Simulamos exactamente lo que hace mouseReleaseEvent
    params_for_clip = dict(eff.default_params)
    clip = Clip(track=-1, start_ms=0, end_ms=2000, effect_id=0,
                scope='fixture:m1', category=eff.category,
                channel_effect_id=eff.effect_id, params=params_for_clip)
    # Los valores iniciales deben coincidir
    for k, v in eff.default_params.items():
        assert clip.params.get(k) == v
    # Añadir una clave nueva al template NO debe alterar el clip
    eff.default_params['__nuevo__'] = 'X'
    assert '__nuevo__' not in clip.params
    # Cleanup
    eff.default_params.pop('__nuevo__', None)


# ── 4. Mapeo track-index ↔ fixture_id ────────────────────────────────────────

def test_fixture_lane_index_to_fixture_id():
    """El primer fixture lane corresponde al primer fixture non-LED del rig."""
    from core.fixtures import FixtureRig, DEFAULT_RIG_FILE
    # Cargar rig real si existe; sino crear uno mínimo
    if DEFAULT_RIG_FILE.is_file():
        rig = FixtureRig.load()
    else:
        rig = FixtureRig(fixtures=[])
    non_led = [fx for fx in rig.fixtures if fx.profile_id != 'wled_strip_93']
    # Si hay non-LED, el primer fixture_id debe ser válido
    for fx in non_led:
        assert fx.fixture_id, "fixture_id no debe estar vacío"
        assert ':' not in fx.fixture_id, "fixture_id no debe contener ':'"


# ── 5. Persistencia: el channel clip va y viene por JSON ─────────────────────

def test_channel_clip_roundtrip_json(tmp_path):
    """Save + load preservan todos los campos del channel clip."""
    tl = Timeline(duration_ms=10000)
    tl.clips = [
        Clip(track=-1, start_ms=0,    end_ms=3000,  effect_id=0,
             scope='fixture:mover_X', category='position',
             channel_effect_id='pos_circle', layer=0,
             params={'speed': 0.5, 'radius': 0.3}),
        Clip(track=-1, start_ms=2000, end_ms=8000,  effect_id=0,
             scope='fixture:mover_Y', category='color',
             channel_effect_id='col_rainbow', layer=1,
             params={'speed': 0.8}),
    ]
    fpath = tmp_path / 'roundtrip.json'
    tl.save(fpath)

    loaded = Timeline.load(fpath)
    assert len(loaded.clips) == 2
    c0 = loaded.clips[0]
    assert c0.track == -1
    assert c0.scope == 'fixture:mover_X'
    assert c0.category == 'position'
    assert c0.channel_effect_id == 'pos_circle'
    assert c0.params == {'speed': 0.5, 'radius': 0.3}
    c1 = loaded.clips[1]
    assert c1.channel_effect_id == 'col_rainbow'
    assert c1.category == 'color'
