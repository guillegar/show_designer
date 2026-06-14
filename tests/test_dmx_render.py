"""
test_dmx_render.py — Tests J2: soporte DMX completo por canal.

Cubre:
  test_dimmer_brightness          — dimmer: canal 1 = brightness del clip
  test_rgb_channels               — rgb: canales 1-3 = R/G/B correctos
  test_moving_head_pan            — moving_head: canal pan en rango 0..255
  test_strobe_rate                — strobe: canal 1 proporcional al rate
  test_last_wins_mixing           — mezcla LAST_WINS: capa más alta gana
  test_compute_fixture_channels   — session: _fixture_dmx_channels poblado
"""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.core.dmx_render import render_fixture_channels, _to_dmx
from src.core.fixtures import Fixture, FixtureRig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fixture(kind: str, universe: int = 1, dmx_start: int = 1) -> Fixture:
    fx = Fixture(
        fixture_id=f"fx_{kind}",
        profile_id=kind,
        universe=universe,
        dmx_start=dmx_start,
        kind_override=kind,
    )
    return fx


def _make_clip(params: dict, layer: int = 0, start_ms: int = 0, end_ms: int = 5000) -> MagicMock:
    clip = MagicMock()
    clip.params = params
    clip.layer = layer
    clip.start_ms = start_ms
    clip.end_ms = end_ms
    clip.muted = False
    return clip


# ── Tests render_fixture_channels (función pura) ──────────────────────────────

def test_dimmer_brightness():
    """Fixture dimmer: canal 1 = brightness del clip (0..255)."""
    fx = _make_fixture("dimmer")
    clip = _make_clip({"brightness": 0.5})
    ch = render_fixture_channels(fx, None, [clip], t_ms=1000)
    assert ch[1] == pytest.approx(127, abs=1)


def test_rgb_channels():
    """Fixture rgb: canales 1-3 = R/G/B correctos."""
    fx = _make_fixture("rgb")
    clip = _make_clip({"r": 1.0, "g": 0.0, "b": 0.5})
    ch = render_fixture_channels(fx, None, [clip], t_ms=1000)
    assert ch[1] == 255   # R
    assert ch[2] == 0     # G
    assert ch[3] == pytest.approx(127, abs=1)  # B


def test_moving_head_pan():
    """Fixture moving_head: canal pan (ch1) mapeado de 0..360° a 0..255."""
    fx = _make_fixture("moving_head")
    # 180° → 0.5 × 255 = 127
    clip = _make_clip({"pan": 180.0, "tilt": 0.0, "brightness": 1.0,
                        "r": 0.0, "g": 0.0, "b": 0.0, "strobe": 0.0})
    ch = render_fixture_channels(fx, None, [clip], t_ms=1000)
    assert ch[1] == pytest.approx(127, abs=1)   # pan
    # 360° → 255
    clip360 = _make_clip({"pan": 360.0, "tilt": 0.0, "brightness": 1.0,
                           "r": 0.0, "g": 0.0, "b": 0.0, "strobe": 0.0})
    ch360 = render_fixture_channels(fx, None, [clip360], t_ms=1000)
    assert ch360[1] == 255


def test_strobe_rate():
    """Fixture strobe: canal 1 proporcional al rate (0..1 → 0..255)."""
    fx = _make_fixture("strobe")
    clip_off = _make_clip({"rate": 0.0})
    clip_max = _make_clip({"rate": 1.0})
    clip_half = _make_clip({"rate": 0.5})
    assert render_fixture_channels(fx, None, [clip_off], 0)[1] == 0
    assert render_fixture_channels(fx, None, [clip_max], 0)[1] == 255
    assert render_fixture_channels(fx, None, [clip_half], 0)[1] == pytest.approx(127, abs=1)


def test_last_wins_mixing():
    """LAST_WINS: capa más alta sobreescribe capa más baja."""
    fx = _make_fixture("dimmer")
    clip_low = _make_clip({"brightness": 0.2}, layer=0)
    clip_high = _make_clip({"brightness": 0.8}, layer=2)
    # Orden: clip_low primero, clip_high sobreescribe → valor = 0.8
    ch = render_fixture_channels(fx, None, [clip_low, clip_high], t_ms=1000)
    assert ch[1] == pytest.approx(204, abs=1)   # 0.8 × 255 ≈ 204

    # Invertimos el orden de llamada — el resultado debe ser igual (sort por layer)
    ch2 = render_fixture_channels(fx, None, [clip_high, clip_low], t_ms=1000)
    assert ch2[1] == pytest.approx(204, abs=1)


def test_compute_fixture_channels(tmp_path):
    """Session._compute_fixture_channels pobla _fixture_dmx_channels."""
    from server.session import ShowSession
    from src.core.timeline_model import Timeline, Clip

    # Rig con un dimmer en universe=11, dmx_start=1
    rig = FixtureRig()
    fx = Fixture(
        fixture_id="dimmer_test",
        profile_id="dimmer",
        universe=11,
        dmx_start=1,
        kind_override="dimmer",
    )
    rig.fixtures.append(fx)

    # Mock session mínimo con rig y timeline
    session = MagicMock()
    session.fixture_rig = rig
    tl = Timeline()
    # Clip en track = universe - 1 = 10, brightness = 1.0
    c = Clip(track=10, start_ms=0, end_ms=5000, effect_id=1,
             scope="per_bar", label="dim", uid="c1")
    c.params = {"brightness": 1.0}
    tl.clips.append(c)
    session.timeline = tl
    session._fixture_dmx_channels = {}

    # Inyectar la función en el contexto del session real (sin inicializar todo)
    from server import session as session_module
    s = object.__new__(ShowSession)
    s.fixture_rig = rig
    s.timeline = tl
    s._fixture_dmx_channels = {}

    s._compute_fixture_channels(1000)

    assert 11 in s._fixture_dmx_channels
    buf = s._fixture_dmx_channels[11]
    # dmx_start=1, ch1 → idx=0; brightness=1.0 → 255
    assert buf[0] == 255


def test_pixel_fixture_returns_empty():
    """led_strip y wled_bar retornan {} (cubiertos por el render pixel)."""
    from src.core.dmx_render import render_fixture_channels
    fx_led = _make_fixture("led_strip")
    fx_wled = _make_fixture("wled_bar")
    clip = _make_clip({"brightness": 1.0})
    assert render_fixture_channels(fx_led, None, [clip], 0) == {}
    assert render_fixture_channels(fx_wled, None, [clip], 0) == {}
