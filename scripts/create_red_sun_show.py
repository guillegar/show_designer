"""
create_red_sun_show.py — Genera el proyecto 'red_sun' (Oscar Mulero — "Red Sun").

Show LED **techno-minimal, asimétrico y con barridos**, "digno de ver tumbado":
una composición DATA-DRIVEN que sigue la energía real de la canción (no segmentos
hardcodeados). El sol rojo nace tenue, late en la oscuridad, y va calentándose
(rojo→naranja→ámbar) según sube la energía del track; los barridos cruzan el rig en
un solo sentido (asimétricos) y los golpes (kicks/snares) pinchan acentos.

Pipeline:
  - Lee el análisis con `AnalysisService` (beats, downbeats, kicks, snares, secciones)
    + un sampler de energía `energy_at(t)` desde timeseries.npz (curva 'energy').
  - Agrupa downbeats en **frases** (8 downbeats) y clasifica cada frase en un **tier de
    energía** (percentiles → void/low/mid/high/peak), auto-calibrado a la canción.
  - Por frase elige UN look (cambio lento = minimal):
      void → respiración lenta en un subconjunto asimétrico de barras (hipnótico).
      low  → respiración audio-reactiva + pulsos radiales laterales en downbeats.
      mid  → ola 2D / sweep con suelo ámbar tenue.
      high → cometas direccionales (1034) alternando sentido de forma irregular.
      peak → cometas rápidos + anillos radiales (1032) en downbeats (lo más brillante).
  - Acentos ESCASOS (minimal): destellos ember per-bar en 1-2 barras concretas
    (asimétrico) sobre una fracción de los kicks; blinks radiales off-center en snares.

Reutiliza `make_rig`, `nearest`, `next_in` de create_taser_barras (mismo rig de 10 barras).
Escribe atómicamente projects/red_sun/{project.json, rig.json, rig_layout.json, show.json}.

Uso:
  python -m scripts.create_red_sun_show      (desde la raíz del repo)
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# NOTA: create_taser_barras reconfigura sys.stdout a UTF-8 en win32 al importarse
# (una sola vez). No lo dupliquemos aquí o se cierra el buffer.
from scripts.create_taser_barras import make_rig, nearest, next_in  # reutilizamos rig + snap
from src.analysis.analyzer_service import AnalysisService

# ── Identidad del proyecto ──────────────────────────────────────────────────
DST_SLUG = "red_sun"
DST_NAME = "Oscar Mulero — Red Sun"
ANALYSIS_SLUG = "10-CONCEPTUAL-Red_Sun"
AUDIO_PATH = ROOT / "assets" / "audio" / "10-CONCEPTUAL-Red_Sun.mp3"
NUM_BARS = 10
SEED = 11

# ── Efectos (IDs) ───────────────────────────────────────────────────────────
BREATH = 1019          # breathing (per_bar, opcionalmente audio-reactivo)
SOLID = 1004           # solid_color (per_bar) — acentos ember
WAVE2D = 1031          # ola 2D (global, centrada)
SWEEP = 1033           # sweep (global)
RADIAL_C = 1032        # radial centrado (global)
COMET = 1034           # cometa direccional asimétrico (global)   ← color_async
RADIAL_O = 1035        # radial off-center asimétrico (global)    ← color_async
PUMP = 1036            # pulso audio-reactivo de todo el rig      ← color_async

PHRASE_DOWNBEATS = 4   # frase = 4 downbeats (~7.4 s) → más dinámico/asimétrico

# ── Paleta "Sol Rojo" (lerp por tiempo normalizado 0..1) ────────────────────
# Sale de ox-blood casi negro, se calienta a rojo→naranja→ámbar, pico breve, y se
# pone al final (vuelta al ox-blood). El brillo final lo modula el tier de energía.
PALETTE_STOPS = [
    (0.00, (70, 6, 10)),     # ox-blood (intro/void)
    (0.18, (140, 16, 14)),   # rojo oscuro
    (0.42, (200, 40, 18)),   # rojo
    (0.62, (235, 80, 20)),   # naranja sangre
    (0.80, (255, 130, 40)),  # ámbar ember
    (0.90, (255, 175, 85)),  # pico caliente
    (1.00, (60, 6, 10)),     # puesta de sol
]
# Brillo por tier (escala el color del look principal).
TIER_BRIGHT = {0: 0.30, 1: 0.50, 2: 0.68, 3: 0.86, 4: 1.0}


# ─────────────────────────────────────────────────────────────────────────────
# Análisis
# ─────────────────────────────────────────────────────────────────────────────
def load_analysis():
    svc = AnalysisService(ROOT / "analizadas" / ANALYSIS_SLUG)
    assert svc.has_analysis, f"No hay análisis en analizadas/{ANALYSIS_SLUG}"
    dur_ms = int(round(svc.summary["duration_s"] * 1000))

    beats = [int(round(t * 1000)) for t in svc.list_beats()]
    downs = [int(round(t * 1000)) for t in svc.list_downbeats()]
    kicks = [int(round(e.time_sec * 1000)) for e in svc.list_events("kick")]
    snares = [int(round(e.time_sec * 1000)) for e in svc.list_events("snare")]

    # Sampler de energía (curva 'energy' del timeseries, normalizada 0..1).
    svc._load_timeseries()
    ts = svc._timeseries or {}
    ts_times = np.asarray(ts.get("times", []), dtype=np.float64)
    ts_energy = np.asarray(ts.get("energy", []), dtype=np.float64)

    def energy_at(ms: int) -> float:
        if ts_times.size == 0:
            return 0.0
        return float(np.interp(ms / 1000.0, ts_times, ts_energy, left=0.0, right=0.0))

    return svc, dur_ms, beats, downs, kicks, snares, energy_at


# ─────────────────────────────────────────────────────────────────────────────
# Color
# ─────────────────────────────────────────────────────────────────────────────
def palette_at(t_norm: float):
    t_norm = max(0.0, min(1.0, t_norm))
    for i in range(len(PALETTE_STOPS) - 1):
        a_t, a_c = PALETTE_STOPS[i]
        b_t, b_c = PALETTE_STOPS[i + 1]
        if a_t <= t_norm <= b_t:
            f = 0.0 if b_t == a_t else (t_norm - a_t) / (b_t - a_t)
            return tuple(int(round(a_c[k] + (b_c[k] - a_c[k]) * f)) for k in range(3))
    return PALETTE_STOPS[-1][1]


def scale_rgb(rgb, f: float):
    return tuple(max(0, min(255, int(round(c * f)))) for c in rgb)


def hexc(rgb):
    return "#%02x%02x%02x" % rgb


# ─────────────────────────────────────────────────────────────────────────────
# Constructores de clips
# ─────────────────────────────────────────────────────────────────────────────
def _clip(track, start, end, eff, scope, params, color, label, layer=0):
    return {
        "track": int(track), "start_ms": int(start), "end_ms": int(end),
        "effect_id": int(eff), "scope": scope, "params": dict(params),
        "label": label, "color": hexc(color) if isinstance(color, tuple) else color,
        "layer": int(layer), "locked": False, "muted": False,
        "category": "pixel", "channel_effect_id": None,
    }


def _global(start, end, eff, params, color, label, layer=0):
    return _clip(-1, start, end, eff, "global", params, color, label, layer)


def _perbar(track, start, end, eff, params, color, label, layer=0):
    return _clip(track, start, end, eff, "per_bar", params, color, label, layer)


# ─────────────────────────────────────────────────────────────────────────────
# Composición
# ─────────────────────────────────────────────────────────────────────────────
# Subconjuntos asimétricos de barras (nunca simétricos respecto al centro) que rotan
# por frase → la respiración del bed nunca pinta las 10 a la vez en void/low.
ASYM_MASKS = [
    [0, 1, 2, 4, 7],
    [2, 3, 5, 8, 9],
    [0, 3, 4, 6, 9],
    [1, 2, 5, 6, 8],
    [0, 1, 4, 7, 8],
]
# Pares de barras (asimétricos) para los acentos ember de kick.
ACCENT_BARS = [[2, 7], [0, 5], [3, 8], [1, 6], [4, 9], [0, 3], [5, 8]]


def build_phrases(downs, dur_ms):
    """Agrupa downbeats en frases de PHRASE_DOWNBEATS. Devuelve [(start_ms, end_ms)]."""
    if not downs:
        return [(0, dur_ms)]
    phrases = []
    i = 0
    while i < len(downs):
        a = downs[i]
        j = min(i + PHRASE_DOWNBEATS, len(downs))
        b = downs[j] if j < len(downs) else dur_ms
        phrases.append((a, b))
        i = j
    # Hueco inicial (antes del primer downbeat) como su propia frase.
    if downs[0] > 1500:
        phrases.insert(0, (0, downs[0]))
    return phrases


def energy_tiers(phrases, energy_at):
    """Energía media por frase → tier 0..4 por percentiles (auto-calibrado)."""
    e = []
    for (a, b) in phrases:
        mid = (a + b) // 2
        # media de 3 muestras dentro de la frase
        vals = [energy_at(a + (b - a) * k // 4) for k in (1, 2, 3)]
        e.append(sum(vals) / len(vals))
    arr = np.asarray(e)
    # Umbrales por percentiles de la distribución real de la canción.
    q = np.quantile(arr, [0.20, 0.45, 0.70, 0.88])
    tiers = []
    for v in arr:
        t = int(np.searchsorted(q, v))   # 0..4
        tiers.append(min(4, t))
    return tiers, e


def _downbeat_hits(a, b, downs, beats, color, layer=2):
    """Hit warm en cada downbeat: pulso radial centrado breve (el 'golpe' techno)."""
    out = []
    for d in [x for x in downs if a <= x < b]:
        e = min(next_in(beats, d), b)
        e = min(d + 200, e)              # golpe breve (~200ms)
        if e > d:
            out.append(_global(d, e, RADIAL_C,
                               {"r": color[0], "g": color[1], "b": color[2],
                                "speed": 2.4, "width": 1.0},
                               color, "hit", layer=layer))
    return out


def movement_clips(idx, a, b, tier, base_color, beats, downs, rng):
    """Capa 1: el 'look' de la frase. El PULSO audio-reactivo es el motor; el barrido
    da el movimiento. Suelo a 0 → contraste (oscuro entre golpes = pegada). Asimétrico."""
    clips = []
    col = scale_rgb(base_color, TIER_BRIGHT[tier])
    # Sentido irregular (no metronómico) + inclinación lateral asimétrica.
    direction = "ltr" if (idx * 3 + tier) % 2 == 0 else "rtl"
    tilt = [-0.7, 0.6, -0.4, 0.5, -0.6, 0.7][idx % 6]

    if tier == 0:
        # VOID: sin movimiento. El bed de respiración (capa 0) es todo el look.
        return clips

    if tier == 1:
        # LOW: PULSO puro audio-reactivo, dim, inclinado a un lado (asimétrico).
        clips.append(_global(a, b, PUMP,
                             {"r": col[0], "g": col[1], "b": col[2],
                              "gamma": 2.2, "tilt": tilt, "min_brightness": 0.03,
                              "pump_source": "rms"},
                             col, "pulso", layer=1))
        return clips

    if tier == 2:
        # MID: cometa que BOMBEA con el kick, velocidad media.
        clips.append(_global(a, b, COMET,
                             {"r": col[0], "g": col[1], "b": col[2],
                              "speed": 1.3, "width": 1.3, "tail": 3.0,
                              "direction": direction, "min_brightness": 0.0,
                              "pump": 0.8, "pump_source": "rms"},
                             col, f"comet·{direction}", layer=1))
        return clips

    if tier == 3:
        # HIGH: cometa rápido que bombea + hits warm en downbeats.
        clips.append(_global(a, b, COMET,
                             {"r": col[0], "g": col[1], "b": col[2],
                              "speed": 2.2, "width": 1.0, "tail": 2.6,
                              "direction": direction, "min_brightness": 0.0,
                              "pump": 0.85, "pump_source": "rms"},
                             col, f"comet+·{direction}", layer=1))
        clips += _downbeat_hits(a, b, downs, beats, (255, 150, 70))
        return clips

    # PEAK: cometa rapidísimo que bombea + hits warm intensos en downbeats.
    clips.append(_global(a, b, COMET,
                         {"r": col[0], "g": col[1], "b": col[2],
                          "speed": 3.0, "width": 0.8, "tail": 2.2,
                          "direction": direction, "min_brightness": 0.0,
                          "pump": 0.9, "pump_source": "flux"},
                         col, f"comet++·{direction}", layer=1))
    clips += _downbeat_hits(a, b, downs, beats, (255, 200, 120))
    return clips


def bed_clips(idx, a, b, tier, base_color, rng):
    """Capa 0: bed de respiración. En void/low pinta un subconjunto ASIMÉTRICO de
    barras con rate_hz desigual por barra (no pulsan al unísono)."""
    clips = []
    if tier >= 2:
        return clips  # en mid+ el movimiento es el look; sin bed que tape
    ember = scale_rgb(base_color, 0.55 if tier == 1 else 0.42)
    mask = ASYM_MASKS[idx % len(ASYM_MASKS)]
    # Audio-reactivo SIEMPRE → incluso el intro/void flickea sutilmente con la música.
    base_rate = 0.30 if tier == 1 else 0.16
    for k, tr in enumerate(mask):
        rate = round(base_rate + 0.03 * ((k * 7 + idx) % 5), 3)   # desigual por barra
        params = {"r": ember[0], "g": ember[1], "b": ember[2],
                  "rate_hz": rate, "min_brightness": 0.015,
                  "audio_reactive": True, "audio_source": "rms"}
        clips.append(_perbar(tr, a, b, BREATH, params, ember, "bed", layer=0))
    return clips


def accent_clips(kicks, snares, beats, dur_ms, tiers, phrases, rng):
    """Capa 2: acentos ESCASOS. Ember per-bar en 1-2 barras (asimétrico) sobre una
    fracción de kicks (solo en tiers >=2); blink radial off-center en snares (peaks)."""
    clips = []

    def tier_at(ms):
        for (a, b), t in zip(phrases, tiers):
            if a <= ms < b:
                return t
        return 0

    # Kicks → destello ember en 1-2 barras concretas (asimétrico). 1 de cada 2 en
    # energía media+, brillante y breve → pegada extra sin tapar el movimiento.
    for n, ms in enumerate(kicks):
        if n % 2 != 0:
            continue
        t = tier_at(ms)
        if t < 2:
            continue
        s = nearest(beats, ms)
        if abs(s - ms) > 130:
            s = ms
        e = min(next_in(beats, s), dur_ms)
        e = min(s + 150, e)                      # destello breve
        if e <= s:
            continue
        bars = ACCENT_BARS[n % len(ACCENT_BARS)]
        warm = (255, 170, 80)
        for tr in bars:
            clips.append(_perbar(tr, s, e, SOLID,
                                 {"r": warm[0], "g": warm[1], "b": warm[2]},
                                 warm, "punch", layer=3))

    # Snares → blink radial off-center puntual (solo en peaks, 1 de cada 4).
    for n, ms in enumerate(snares):
        if n % 4 != 0:
            continue
        if tier_at(ms) < 4:
            continue
        s = nearest(beats, ms)
        if abs(s - ms) > 130:
            s = ms
        e = min(s + 150, dur_ms)
        if e <= s:
            continue
        org = [0, 9][n % 2]
        clips.append(_global(s, e, RADIAL_O,
                             {"r": 255, "g": 190, "b": 110,
                              "speed": 3.0, "width": 0.7, "origin": org,
                              "min_brightness": 0.0},
                             (255, 190, 110), "snare", layer=3))
    return clips


def build_show(svc, dur_ms, beats, downs, kicks, snares, energy_at):
    rng = random.Random(SEED)
    phrases = build_phrases(downs, dur_ms)
    tiers, energies = energy_tiers(phrases, energy_at)

    clips = []
    for idx, ((a, b), tier) in enumerate(zip(phrases, tiers)):
        t_norm = ((a + b) / 2) / dur_ms
        base_color = palette_at(t_norm)
        clips += bed_clips(idx, a, b, tier, base_color, rng)
        clips += movement_clips(idx, a, b, tier, base_color, beats, downs, rng)

    clips += accent_clips(kicks, snares, beats, dur_ms, tiers, phrases, rng)

    # cue_points = arranque de las primeras secciones / drops (referencia en timeline).
    cues = []
    secs = svc.list_sections()
    for i, sec in enumerate(secs[:9]):
        cues.append({"slot": i + 1, "time_ms": int(sec.start * 1000),
                     "name": sec.label, "color": "#ff5a2a"})

    show = {
        "version": 4,
        "duration_ms": dur_ms,
        "clips": clips,
        "groups": [],
        "cue_points": cues,
        "automation": [],
        "patterns": [],
        "pattern_instances": [],
        "mixer": {},
        "live_slots": [],
        "cue_list": {"entries": [], "active_uid": None},
        "markers": [],
    }
    return show, phrases, tiers, energies


def _write_atomic(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def make_rig_layout(rig):
    """rig_layout.json mínimo a partir de las posiciones del rig (el visor 3D lo
    re-sincroniza al cargar, pero así arranca correcto)."""
    fixtures = {}
    for f in rig.get("fixtures", []):
        pos = f.get("position", [0.0, 1.0, 0.0])
        fixtures[f["fixture_id"]] = {"x": pos[0], "y": pos[1], "z": pos[2],
                                     "rx": 0.0, "ry": 0.0, "rz": 0.0}
    return {"version": 1, "fixtures": fixtures}


def main():
    svc, dur_ms, beats, downs, kicks, snares, energy_at = load_analysis()
    print(f"[+] análisis: {len(beats)} beats · {len(downs)} downbeats · "
          f"{len(kicks)} kicks · {len(snares)} snares · {dur_ms/1000:.0f}s")

    show, phrases, tiers, energies = build_show(
        svc, dur_ms, beats, downs, kicks, snares, energy_at)

    from collections import Counter
    dist = Counter(tiers)
    names = {0: "void", 1: "low", 2: "mid", 3: "high", 4: "peak"}
    tier_str = " ".join(f"{names[k]}:{dist.get(k,0)}" for k in range(5))
    print(f"[show] {len(show['clips'])} clips · {len(phrases)} frases · tiers [{tier_str}]")

    rig = make_rig()
    dst = ROOT / "projects" / DST_SLUG
    dst.mkdir(parents=True, exist_ok=True)

    project = {
        "slug": DST_SLUG,
        "name": DST_NAME,
        "audio_path": str(AUDIO_PATH),
        "analysis_slug": ANALYSIS_SLUG,
        "created": "2026-06-19T00:00:00",
        "notes": "Techno-minimal asimétrico para 'Red Sun' (Oscar Mulero). Composición "
                 "data-driven por energía (frases + tiers), paleta Sol Rojo, barridos "
                 "asimétricos (cometas 1034 / radial off-center 1035), bed de respiración "
                 "audio-reactivo y acentos sobre kicks/snares. "
                 "Generado por scripts/create_red_sun_show.py.",
    }
    _write_atomic(dst / "project.json", project)
    _write_atomic(dst / "rig.json", rig)
    _write_atomic(dst / "rig_layout.json", make_rig_layout(rig))
    _write_atomic(dst / "show.json", show)

    print(f"[✓] proyecto creado: projects/{DST_SLUG}/ "
          f"(rig {len(rig['fixtures'])} barras, {len(show['clips'])} clips, {dur_ms//1000}s)")
    print(f"    Arranca con:  set LUCES_PROJECT={DST_SLUG}  →  python -m server.main")


if __name__ == "__main__":
    main()
