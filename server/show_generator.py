"""
show_generator.py — Generación automática de show desde análisis (M2).

Algoritmo determinista sobre beats/secciones del AnalysisService.
Estilos: minimal | club | festival | chill.
Densidad: 0.0 (solo downbeats) .. 1.0 (cada beat).

Sin IA externa. Resultado editable como cualquier show.json.
I1: toma snapshot antes de mutar (deshaciable con Ctrl+Z).
I4: retorna clips vacíos y error si no hay análisis.
"""
from __future__ import annotations

import uuid
from typing import Any

SOLID_COLOR_ID = 1004   # plugins/effects/solid_color.py
STROBE_COLOR_ID = 1015  # plugins/effects/strobe_color.py

STYLES = ("minimal", "club", "festival", "chill")


# ── Paletas de colores por estilo ─────────────────────────────────────────────

def _style_colors(style: str, n_sections: int) -> list[str]:
    """Devuelve lista de colores hex (uno por sección)."""
    if style == "minimal":
        base = ["#ffffff", "#3a7acc", "#ffffff", "#a0a0a0"]
        return [base[i % len(base)] for i in range(n_sections)]
    if style == "club":
        base = ["#ff2244", "#2244ff", "#22ff88", "#ff22cc"]
        return [base[i % len(base)] for i in range(n_sections)]
    if style == "festival":
        return [
            _hsv_to_hex(i / max(n_sections, 1), 1.0, 1.0)
            for i in range(n_sections)
        ]
    if style == "chill":
        base = ["#ffcc88", "#88ccff", "#ffaaaa", "#aaffcc", "#ffddaa"]
        return [base[i % len(base)] for i in range(n_sections)]
    # fallback
    return ["#3a7acc"] * n_sections


def _hsv_to_hex(h: float, s: float, v: float) -> str:
    """HSV (0..1 each) → '#rrggbb'."""
    h6 = h * 6.0
    i = int(h6)
    f = h6 - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    rgb = [
        (v, t, p), (q, v, p), (p, v, t),
        (p, q, v), (t, p, v), (v, p, q),
    ][i % 6]
    return f"#{int(rgb[0] * 255):02x}{int(rgb[1] * 255):02x}{int(rgb[2] * 255):02x}"


def _parse_hex_color(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 255, 255, 255


# ── Lógica de generación ──────────────────────────────────────────────────────

def generate_show(
    beats: list[float],
    downbeats: list[float],
    sections: list[Any],
    style: str = "club",
    density: float = 0.5,
    bpm: float = 120.0,
) -> list[dict]:
    """
    Genera una lista de dicts de clips (ya serializados, listos para timeline.clips).

    Args:
        beats:      lista de tiempos de beat en segundos.
        downbeats:  lista de tiempos de downbeat en segundos.
        sections:   lista de objetos con .start, .end (en segundos).
        style:      "minimal" | "club" | "festival" | "chill".
        density:    0.0 .. 1.0.
        bpm:        BPM del show (para calcular duraciones).
    Returns:
        Lista de dicts de clips.
    """
    if not beats and not downbeats:
        return []

    beat_dur_ms = int(round(60000.0 / max(bpm, 1)))
    downbeat_set = set(round(d, 4) for d in downbeats)

    # Asignar colores por sección
    n_sec = max(len(sections), 1)
    palette = _style_colors(style, n_sec)

    def _color_at(t_s: float) -> str:
        for i, sec in enumerate(sections):
            if sec.start <= t_s < sec.end:
                return palette[i % len(palette)]
        return palette[0] if palette else "#3a7acc"

    clips: list[dict] = []
    # tracker de ocupación por layer: {layer: [(start_ms, end_ms)]}
    occupied: dict[int, list[tuple[int, int]]] = {0: [], 1: [], 2: []}

    def _can_place(layer: int, start_ms: int, end_ms: int) -> bool:
        for s, e in occupied.get(layer, []):
            if start_ms < e and end_ms > s:
                return False
        return True

    def _place(clip_dict: dict, layer: int, start_ms: int, end_ms: int):
        occupied.setdefault(layer, []).append((start_ms, end_ms))
        clips.append(clip_dict)

    # Layer 0: clips en downbeats (siempre)
    for db in downbeats:
        t_ms = int(db * 1000)
        end_ms = t_ms + beat_dur_ms
        color = _color_at(db)
        r, g, b = _parse_hex_color(color)
        if _can_place(0, t_ms, end_ms):
            _place({
                "uid": uuid.uuid4().hex[:12],
                "track": 0, "start_ms": t_ms, "end_ms": end_ms,
                "effect_id": SOLID_COLOR_ID, "scope": "per_bar",
                "params": {"r": r, "g": g, "b": b}, "color": color,
                "label": "GEN", "layer": 0, "locked": False, "muted": False,
                "category": "pixel", "channel_effect_id": None, "preset_id": None,
                "param_links": [], "events": [], "channel_effects": [],
            }, 0, t_ms, end_ms)

    # Layer 1: clips en beats (solo si density > 0.5)
    if density > 0.5:
        half = beat_dur_ms // 2
        for bt in beats:
            bt_r = round(bt, 4)
            if bt_r in downbeat_set:
                continue  # ya cubierto en layer 0
            t_ms = int(bt * 1000)
            end_ms = t_ms + half
            color = _color_at(bt)
            r, g, b = _parse_hex_color(color)
            if _can_place(1, t_ms, end_ms):
                _place({
                    "uid": uuid.uuid4().hex[:12],
                    "track": 0, "start_ms": t_ms, "end_ms": end_ms,
                    "effect_id": SOLID_COLOR_ID, "scope": "per_bar",
                    "params": {"r": r, "g": g, "b": b}, "color": color,
                    "label": "GEN", "layer": 1, "locked": False, "muted": False,
                    "category": "pixel", "channel_effect_id": None, "preset_id": None,
                    "param_links": [], "events": [], "channel_effects": [],
                }, 1, t_ms, end_ms)

    # Layer 2: strobe en beats enérgicos (solo si density > 0.8)
    if density > 0.8:
        # Usar subconjunto de beats (1 de cada 2) para no saturar
        energetic = [bt for i, bt in enumerate(beats) if i % 2 == 0]
        for bt in energetic:
            t_ms = int(bt * 1000)
            end_ms = t_ms + 50  # 50 ms
            color = _color_at(bt)
            r, g, b = _parse_hex_color(color)
            if _can_place(2, t_ms, end_ms):
                _place({
                    "uid": uuid.uuid4().hex[:12],
                    "track": 0, "start_ms": t_ms, "end_ms": end_ms,
                    "effect_id": STROBE_COLOR_ID, "scope": "per_bar",
                    "params": {"r": r, "g": g, "b": b, "speed": 10.0, "duty": 0.5},
                    "color": color,
                    "label": "GEN-S", "layer": 2, "locked": False, "muted": False,
                    "category": "pixel", "channel_effect_id": None, "preset_id": None,
                    "param_links": [], "events": [], "channel_effects": [],
                }, 2, t_ms, end_ms)

    return clips
