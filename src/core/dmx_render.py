"""
dmx_render.py — J2: renderizado de canales DMX para fixtures no-pixel.

Función pura testeable sin hardware:
  render_fixture_channels(fixture, profile, clips, t_ms) → {canal_1based: 0..255}

Política de mezcla: LAST_WINS — capa más alta sobreescribe capas inferiores.
Para pixel (led_strip / wled_bar) retorna {} (el pixel render ya los cubre).
"""
from __future__ import annotations

# Kinds que producen pixel (led_strip) — se omiten en el renderizado DMX canal.
_PIXEL_KINDS = {"led_strip", "wled_bar"}


def _effective_kind(fixture, profile) -> str:
    """Devuelve el kind efectivo: kind_override > profile.kind > profile_id."""
    ko = getattr(fixture, "kind_override", None)
    if ko:
        return ko
    if profile is not None:
        return profile.kind or "dimmer"
    return getattr(fixture, "profile_id", "dimmer")


def _param(clip, name: str, default: float | None = None) -> float | None:
    """Extrae un param normalizado (0..1) del clip."""
    p = getattr(clip, "params", None) or {}
    if name not in p:
        return default
    try:
        return float(p[name])
    except (TypeError, ValueError):
        return default


def _to_dmx(norm: float) -> int:
    """Convierte valor normalizado 0..1 a DMX 0..255."""
    return int(max(0, min(255, round(norm * 255))))


def _render_clip_channels(kind: str, channel_map: dict, clip) -> dict[int, int]:
    """Renderiza los canales de un clip según kind y channel_map del profile.

    Si el profile tiene channel_map, lo usa directamente (0-based offset → 1-based canal).
    Si no, usa los defaults por kind.
    """
    result: dict[int, int] = {}

    if channel_map:
        for ch_name, offset in channel_map.items():
            val = _param(clip, ch_name)
            if val is not None:
                result[int(offset) + 1] = _to_dmx(val)
        return result

    # Defaults por kind sin channel_map
    if kind == "dimmer":
        b = _param(clip, "brightness", 0.5)
        result[1] = _to_dmx(b)
    elif kind in ("rgb", "rgb_par"):
        result[1] = _to_dmx(_param(clip, "r", 0.0))
        result[2] = _to_dmx(_param(clip, "g", 0.0))
        result[3] = _to_dmx(_param(clip, "b", 0.0))
    elif kind == "moving_head":
        pan_deg = _param(clip, "pan", 0.0)   # 0..360 grados
        tilt_deg = _param(clip, "tilt", 0.0)
        result[1] = _to_dmx(pan_deg / 360.0)
        result[2] = _to_dmx(tilt_deg / 360.0)
        result[3] = _to_dmx(_param(clip, "brightness", 1.0))
        result[4] = _to_dmx(_param(clip, "r", 0.0))
        result[5] = _to_dmx(_param(clip, "g", 0.0))
        result[6] = _to_dmx(_param(clip, "b", 0.0))
        result[7] = _to_dmx(_param(clip, "strobe", 0.0))
    elif kind == "strobe":
        result[1] = _to_dmx(_param(clip, "rate", 0.0))

    return result


def render_fixture_channels(
    fixture,
    profile,         # FixtureProfile | None
    clips: list,     # clips activos en t_ms para este fixture
    t_ms: int,
    audio_context: dict | None = None,
) -> dict[int, int]:
    """Renderiza los canales DMX de un fixture no-pixel.

    Retorna dict {canal_1based: valor 0..255}.
    Para led_strip / wled_bar retorna {} (cubiertos por el render pixel).
    Mezcla LAST_WINS: capa más alta sobreescribe capas inferiores.
    """
    kind = _effective_kind(fixture, profile)
    if kind in _PIXEL_KINDS:
        return {}

    channel_map: dict = (profile.channel_map if profile is not None else {}) or {}

    result: dict[int, int] = {}
    sorted_clips = sorted(clips, key=lambda c: getattr(c, "layer", 0))
    for clip in sorted_clips:
        updates = _render_clip_channels(kind, channel_map, clip)
        result.update(updates)

    return result
