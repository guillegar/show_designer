"""
Tests del Universe Assembler en show_engine.py.

Cubre:
  - assemble_universe() para fixtures LED strip (RGB en dmx_start correcto)
  - assemble_universe() para fixtures non-LED (channels en dmx_start correcto)
  - Mix de varios fixtures en el mismo universo (cada uno en su offset)
  - Universos vacíos → 512 bytes en cero
  - render_channels_for_fixture devuelve buffer vacío cuando no hay clips
    (Fase 3: channel-effects todavía no existen, viene en Fase 6)
  - FixtureProfile.supported_categories() deduce correctamente

Lanzar:
    pytest tests/test_universe_assembler.py -v
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.fixtures import (    # noqa: E402
    FixtureProfile, Fixture, FixtureRig, load_profile, CATEGORIES,
)


# ────────────────────────────────────────────────────────────────
# supported_categories — deducción automática
# ────────────────────────────────────────────────────────────────

def test_categories_constant_exposed():
    assert "pixel" in CATEGORIES
    assert "position" in CATEGORIES
    assert "color" in CATEGORIES
    assert "intensity" in CATEGORIES
    assert "optical" in CATEGORIES
    assert "strobe" in CATEGORIES
    assert len(CATEGORIES) == 6


def test_supported_categories_wled():
    p = load_profile("wled_strip_93")
    cats = p.supported_categories()
    assert cats == {"pixel"}


def test_supported_categories_wash():
    p = load_profile("generic_wash_15ch")
    cats = p.supported_categories()
    # Debe tener position + color + intensity + strobe (+ optical por zoom)
    assert "position" in cats
    assert "color" in cats
    assert "intensity" in cats
    assert "strobe" in cats
    assert "pixel" not in cats


def test_supported_categories_beam():
    p = load_profile("generic_beam_18ch")
    cats = p.supported_categories()
    assert {"position", "color", "intensity", "optical", "strobe"} <= cats
    assert "pixel" not in cats


def test_supported_categories_strobe():
    p = load_profile("generic_strobe_2ch")
    cats = p.supported_categories()
    assert "intensity" in cats
    assert "strobe" in cats
    # Strobe simple no tiene pan/tilt/color/gobo
    assert "position" not in cats
    assert "color" not in cats
    assert "optical" not in cats


def test_supported_categories_dimmer():
    p = load_profile("dimmer_1ch")
    cats = p.supported_categories()
    assert cats == {"intensity"}


def test_supported_categories_manual_no_rgb():
    """Profile sintético con solo pan+tilt → solo 'position'."""
    p = FixtureProfile(
        profile_id="x", name="x", kind="moving_head", num_channels=2,
        channel_map={"pan": 0, "tilt": 1},
    )
    assert p.supported_categories() == {"position"}


def test_supported_categories_color_wheel_counts_as_color():
    p = FixtureProfile(
        profile_id="x", name="x", kind="moving_head", num_channels=2,
        channel_map={"dim": 0, "color_wheel": 1},
    )
    cats = p.supported_categories()
    assert "color" in cats
    assert "intensity" in cats


# ────────────────────────────────────────────────────────────────
# Universe Assembler — show_engine
# ────────────────────────────────────────────────────────────────
#
# Test del assemble_universe(). Necesitamos un ShowEngine + un FixtureRig
# mínimo. NO arrancamos pygame/audio/etc — solo el assembler.

@pytest.fixture
def minimal_engine():
    """ShowEngine sin audio, sin tests de El Taser — solo el assembler."""
    from src.core.show_engine import ShowEngine
    # Truco: pasar use_effects=False y no inicializar timeseries/audio
    eng = ShowEngine(use_effects=False)
    return eng


@pytest.fixture
def rig_two_fixtures():
    """Rig con: 1 barra WLED en univ 1 + 1 wash 15ch en univ 11 dmx_start 1."""
    rig = FixtureRig()
    rig.fixtures.append(Fixture(
        fixture_id="bar_test",
        profile_id="wled_strip_93",
        universe=1,
        dmx_start=1,
        legacy_bar_idx=0,
    ))
    rig.fixtures.append(Fixture(
        fixture_id="wash_test",
        profile_id="generic_wash_15ch",
        universe=11,
        dmx_start=1,
    ))
    return rig


def test_assemble_universe_returns_512_bytes(minimal_engine, rig_two_fixtures):
    minimal_engine.rig = rig_two_fixtures
    pkt = minimal_engine.assemble_universe(universe_id=1, t=0.0)
    assert isinstance(pkt, bytes)
    assert len(pkt) == 512


def test_assemble_universe_empty_when_no_fixtures(minimal_engine):
    minimal_engine.rig = FixtureRig()
    pkt = minimal_engine.assemble_universe(universe_id=99, t=0.0)
    assert pkt == b'\x00' * 512


def test_assemble_universe_no_rig(minimal_engine):
    minimal_engine.rig = None
    pkt = minimal_engine.assemble_universe(universe_id=1, t=0.0)
    assert pkt == b'\x00' * 512


def test_assemble_universe_led_strip_with_rgb(minimal_engine, rig_two_fixtures):
    minimal_engine.rig = rig_two_fixtures
    # Fake RGB frame para la barra 0: 93 LEDs × 3 = 279 bytes
    rgb = bytes([255, 128, 64] * 93)
    pkt = minimal_engine.assemble_universe(
        universe_id=1, t=0.0,
        rgb_frames_by_bar=[rgb],
    )
    # En dmx_start=1 (offset 0), 279 bytes RGB
    assert pkt[0:3] == bytes([255, 128, 64])
    assert pkt[3:6] == bytes([255, 128, 64])
    # Después del LED strip, el resto debe ser 0
    assert pkt[279:] == b'\x00' * (512 - 279)


def test_assemble_universe_non_led_returns_zeros(minimal_engine, rig_two_fixtures):
    """Universo 11 con un wash sin channel-clips → todos los 15 ch en 0."""
    minimal_engine.rig = rig_two_fixtures
    pkt = minimal_engine.assemble_universe(universe_id=11, t=0.0)
    # 15 bytes del wash + resto de 512
    assert pkt[:15] == b'\x00' * 15
    assert len(pkt) == 512


def test_assemble_universe_multiple_fixtures_offsets(minimal_engine):
    """Dos washes en el mismo universo en offsets distintos no se pisan."""
    rig = FixtureRig()
    rig.fixtures.append(Fixture(
        fixture_id="wash_A", profile_id="generic_wash_15ch",
        universe=11, dmx_start=1,
    ))
    rig.fixtures.append(Fixture(
        fixture_id="wash_B", profile_id="generic_wash_15ch",
        universe=11, dmx_start=17,
    ))
    minimal_engine.rig = rig
    pkt = minimal_engine.assemble_universe(universe_id=11, t=0.0)
    # Sin clips channel-level (Fase 6), cada wash es 15 ceros consecutivos
    # en sus offsets — no hay overlapping. Verificar tamaño total intacto.
    assert len(pkt) == 512


def test_render_channels_for_fixture_no_timeline(minimal_engine, rig_two_fixtures):
    """Sin timeline → buffer entero en 0s (sin clips para aplicar)."""
    minimal_engine.rig = rig_two_fixtures
    wash = rig_two_fixtures.by_id("wash_test")
    buf = minimal_engine.render_channels_for_fixture(wash, t=0.0, timeline=None)
    assert len(buf) == 15   # generic_wash_15ch.num_channels
    assert buf == bytearray(15)


def test_assemble_universe_with_dmx_start_offset(minimal_engine):
    """Un fixture en dmx_start=100 debe escribir en offset 99 (1-based → 0-based)."""
    rig = FixtureRig()
    rig.fixtures.append(Fixture(
        fixture_id="bar_offset", profile_id="wled_strip_93",
        universe=1, dmx_start=100, legacy_bar_idx=0,
    ))
    minimal_engine.rig = rig
    rgb = bytes([1, 2, 3] * 93)
    pkt = minimal_engine.assemble_universe(
        universe_id=1, t=0.0, rgb_frames_by_bar=[rgb],
    )
    # offset 0-98 debe ser 0
    assert pkt[0:99] == b'\x00' * 99
    # offset 99 (dmx_start=100, 1-based) tiene los primeros bytes RGB
    assert pkt[99:102] == bytes([1, 2, 3])


# ────────────────────────────────────────────────────────────────
# send_frame_via_assembler — flujo completo Assembler → Router
# ────────────────────────────────────────────────────────────────

def test_send_frame_via_assembler_uses_router(minimal_engine, rig_two_fixtures):
    """Al enviar por el assembler, el router recibe los bytes."""
    from src.io.outputs.router import OutputRouter, SimOnlyTarget
    minimal_engine.rig = rig_two_fixtures
    # Forzar todos los universos a sim_only para inspección
    minimal_engine.router = OutputRouter(targets={
        1: SimOnlyTarget(), 11: SimOnlyTarget()
    })
    rgb = bytes([10, 20, 30] * 93)
    minimal_engine.send_frame_via_assembler(
        t=0.0, audio_context={}, rgb_frames_by_bar=[rgb],
    )
    sent_1 = minimal_engine.router.last_sent_for(1)
    sent_11 = minimal_engine.router.last_sent_for(11)
    assert sent_1 is not None and len(sent_1) == 512
    assert sent_11 is not None and len(sent_11) == 512
    assert sent_1[:3] == bytes([10, 20, 30])
    assert sent_11[:15] == b'\x00' * 15
