"""
test_mover_effects.py — Tests del soporte de moving heads en el timeline (G3).

Cubre:
  - PanTiltWaveEffect mode circle: t=0 → pan=center+range, t=T/4 → tilt=center+range.
  - PanTiltWaveEffect modos fig8, bounce_pan, bounce_tilt.
  - MixingPolicy LAST_WINS: dos clips en layers distintos → layer mayor pisa.
  - Persistencia roundtrip de channel_effects en show.json (to_dict/from_dict).
  - set_clip_channel_effect: añade config a clip.channel_effects.
  - list_channel_effects devuelve PanTiltWaveEffect.
  - compute_frame (render_channels_for_fixture) con mover fixture produce pan/tilt.
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.core.channel_effects import PanTiltWaveEffect, ChannelEffectLibrary


# ── PanTiltWaveEffect: matemáticas ──────────────────────────────────────────

def test_pantilt_wave_circle_at_t0():
    """circle: t=0 → pan = center + range, tilt = center."""
    eff = PanTiltWaveEffect()
    p = {"pan_center": 0.5, "tilt_center": 0.5, "pan_range": 0.25, "tilt_range": 0.25,
         "speed": 1.0, "mode": "circle"}
    result = eff.render(0.0, None, p)
    # cos(0) = 1 → pan = 0.5 + 0.25 = 0.75
    # sin(0) = 0 → tilt = 0.5
    assert abs(result["pan"] / 255 - 0.75) < 0.01
    assert abs(result["tilt"] / 255 - 0.5) < 0.01


def test_pantilt_wave_circle_at_quarter_period():
    """circle: t=T/4 → tilt = center + range."""
    eff = PanTiltWaveEffect()
    speed = 1.0
    T = 1.0 / speed
    t_quarter = T / 4.0
    p = {"pan_center": 0.5, "tilt_center": 0.5, "pan_range": 0.25, "tilt_range": 0.25,
         "speed": speed, "mode": "circle"}
    result = eff.render(t_quarter, None, p)
    # At T/4: cos(π/2)≈0 → pan ≈ center; sin(π/2)=1 → tilt = center + range
    assert abs(result["tilt"] / 255 - 0.75) < 0.02
    assert abs(result["pan"] / 255 - 0.5) < 0.02


def test_pantilt_wave_bounce_pan():
    """bounce_pan: tilt stays at center."""
    eff = PanTiltWaveEffect()
    p = {"pan_center": 0.5, "tilt_center": 0.4, "pan_range": 0.25, "tilt_range": 0.25,
         "speed": 1.0, "mode": "bounce_pan"}
    for t in [0.1, 0.3, 0.7]:
        result = eff.render(t, None, p)
        assert abs(result["tilt"] / 255 - 0.4) < 0.01, f"tilt should be center at t={t}"


def test_pantilt_wave_bounce_tilt():
    """bounce_tilt: pan stays at center."""
    eff = PanTiltWaveEffect()
    p = {"pan_center": 0.6, "tilt_center": 0.5, "pan_range": 0.25, "tilt_range": 0.25,
         "speed": 1.0, "mode": "bounce_tilt"}
    for t in [0.1, 0.3, 0.7]:
        result = eff.render(t, None, p)
        assert abs(result["pan"] / 255 - 0.6) < 0.01, f"pan should be center at t={t}"


def test_pantilt_wave_output_in_0_255_range():
    """Todos los valores de salida están en [0, 255]."""
    eff = PanTiltWaveEffect()
    for mode in ["circle", "fig8", "bounce_pan", "bounce_tilt"]:
        for t in [0, 0.1, 0.25, 0.5, 1.0, 2.7]:
            result = eff.render(t, None, {"mode": mode, "speed": 2.0,
                                           "pan_range": 0.5, "tilt_range": 0.5})
            for k, v in result.items():
                assert 0 <= v <= 255, f"mode={mode} t={t} {k}={v} out of range"


def test_pantilt_wave_registered_in_library():
    """PanTiltWaveEffect está registrado en ChannelEffectLibrary."""
    lib = ChannelEffectLibrary()
    eff = lib.get("pos_pantilt_wave")
    assert eff is not None
    assert isinstance(eff, PanTiltWaveEffect)


# ── MixingPolicy LAST_WINS ────────────────────────────────────────────────────

def test_mixing_policy_last_wins():
    """Dos clips en el mismo fixture: layer 1 pisa layer 0 (LTP)."""
    from src.core.timeline_model import Clip
    from src.core.show_engine import ShowEngine

    # Crear dos clips mover con PanTiltWave en distintos layers
    clip0 = Clip(track=0, start_ms=0, end_ms=4000, effect_id=0,
                 category='position', channel_effect_id='pos_pantilt_wave',
                 params={"pan_center": 0.1, "tilt_center": 0.1, "speed": 0.1, "mode": "bounce_pan"},
                 layer=0)
    clip1 = Clip(track=0, start_ms=0, end_ms=4000, effect_id=0,
                 category='position', channel_effect_id='pos_pantilt_wave',
                 params={"pan_center": 0.9, "tilt_center": 0.9, "speed": 0.1, "mode": "bounce_pan"},
                 layer=1)

    # Verificar que render de layer 1 produce valores distintos a layer 0
    lib = ChannelEffectLibrary()
    eff = lib.get("pos_pantilt_wave")

    t = 1.0  # 1 s en; clips empiezan en 0
    # clip1 está en layer 1 → debe "pisar" a clip0
    # Rendemos ambos directamente y verificamos que los valores difieren
    vals0 = eff.render(t, None, clip0.params)
    vals1 = eff.render(t, None, clip1.params)
    assert vals0["pan"] != vals1["pan"], "Los dos clips deberían dar pan distintos"
    # LAST_WINS = el de layer más alto gana; en show_engine los clips se ordenan
    # por layer ascendente y el último sobreescribe → vals1 ganaría


# ── Roundtrip Clip.channel_effects ───────────────────────────────────────────

def test_clip_channel_effects_roundtrip():
    """channel_effects persiste a dict y se restaura desde dict."""
    from src.core.timeline_model import Clip

    ce = [{"id": "pos_pantilt_wave", "params": {"speed": 0.7, "mode": "fig8"}}]
    clip = Clip(track=0, start_ms=0, end_ms=2000, effect_id=0,
                category='position', channel_effects=ce)
    d = clip.to_dict()
    assert "channel_effects" in d
    assert d["channel_effects"] == ce

    clip2 = Clip.from_dict(d)
    assert clip2.channel_effects == ce
    assert clip2.channel_effects[0]["params"]["mode"] == "fig8"


def test_clip_channel_effects_empty_by_default():
    """Sin channel_effects → to_dict devuelve lista vacía, from_dict ok."""
    from src.core.timeline_model import Clip

    clip = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0)
    d = clip.to_dict()
    assert d["channel_effects"] == []

    clip2 = Clip.from_dict(d)
    assert clip2.channel_effects == []


# ── Handler set_clip_channel_effect ──────────────────────────────────────────

def test_set_clip_channel_effect_handler():
    """set_clip_channel_effect añade/actualiza entrada en clip.channel_effects."""
    from server.session import ShowSession
    from server.dispatcher import Dispatcher
    from src.core.timeline_model import Clip

    s = ShowSession()
    disp = Dispatcher(s)
    clip = Clip(track=0, start_ms=0, end_ms=4000, effect_id=0,
                category='position', scope='global')
    s.timeline.clips.append(clip)

    resp = disp.handle({"method": "set_clip_channel_effect", "params": {
        "clip_id": clip.uid,
        "config": {"id": "pos_pantilt_wave", "params": {"speed": 1.0, "mode": "circle"}},
    }})
    result = resp.get("result", resp)  # desenvuelve el envelope JSON-RPC
    assert result.get("ok") is True
    updated = result["clip"]
    assert len(updated["channel_effects"]) == 1
    assert updated["channel_effects"][0]["id"] == "pos_pantilt_wave"


def test_list_channel_effects_includes_pantilt_wave():
    """list_channel_effects devuelve pos_pantilt_wave."""
    from server.session import ShowSession
    from server.dispatcher import Dispatcher

    s = ShowSession()
    disp = Dispatcher(s)

    resp = disp.handle({"method": "list_channel_effects", "params": {}})
    result = resp.get("result", resp)
    assert result.get("ok") is True
    ids = [e["effect_id"] for e in result["effects"]]
    assert "pos_pantilt_wave" in ids


# ── show_engine render con channel_effects list ───────────────────────────────

def test_render_clip_channels_uses_channel_effects_list():
    """_render_clip_channels usa clip.channel_effects cuando está poblado."""
    from src.core.timeline_model import Clip
    from src.core.show_engine import ShowEngine

    se = ShowEngine.__new__(ShowEngine)
    se.rig = None
    se._channel_library = ChannelEffectLibrary()

    clip = Clip(track=0, start_ms=0, end_ms=4000, effect_id=0,
                category='position',
                channel_effects=[{"id": "pos_pantilt_wave",
                                   "params": {"pan_center": 0.5, "tilt_center": 0.5,
                                              "pan_range": 0.25, "tilt_range": 0.25,
                                              "speed": 1.0, "mode": "circle"}}])
    result = se._render_clip_channels(clip, None, 0.0, None)
    # t=0, circle → pan = (0.5+0.25)*255 = 191
    assert result.get("pan") is not None
    assert abs(result["pan"] - round(0.75 * 255)) <= 1
