"""
create_taser_barras.py — Genera el proyecto 'el_taser_barras'.

Versión del show *El Taser* recortada a **0–90 s** y **solo barras LED**
(bar_0..bar_9), con:
  - Sincronización snapeada a los **beats reales** (beats_librosa del análisis).
  - **Más cambios de efecto** anclados a la música: variedad de looks por
    sección + acentos (flashes) sobre kicks/snares reales.

Es REPRODUCIBLE e idempotente: regenera
  projects/el_taser_barras/{project.json, rig.json, show.json}
a partir de:
  projects/el_taser/show.json   (timeline origen)
  projects/el_taser/rig.json    (rig origen)
  analizadas/el_taser_de_mama_remix/analysis.json  (beats, sections, kick/snare)

El audio y el análisis NO se duplican: el project.json apunta al mismo MP3 y
comparte analysis_slug, así que la web/engine reutilizan todo el análisis.

Uso:
  python -m scripts.create_taser_barras        (desde la raíz del repo)
"""
from __future__ import annotations

import bisect
import copy
import io
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent

SRC_SLUG = "el_taser"
DST_SLUG = "el_taser_barras"
DST_NAME = "El Taser — Barras"
ANALYSIS_SLUG = "el_taser_de_mama_remix"

LIMIT_MS = 90_000           # 1:30
NUM_BARS = 10               # bar_0..bar_9

# ── Fase 3: parámetros de composición (ajustables) ──────────────────────────
# Cada cuántos beats puede cambiar como mucho el look base (no más rápido que esto).
BASE_CHANGE_EVERY_BEATS = 2
# Paletas de variedad por número de filas de salida del efecto:
#   - 10 filas (cubren las 10 barras) → para clips de scope "global"/"all_bars".
#   - 1 fila (per-bar)               → para clips per_bar / por pista.
# Al variar un clip se elige SIEMPRE un efecto con el mismo nº de filas que el
# original, para no romper la cobertura (p.ej. un global no debe quedarse en 1 barra).
VARIETY_ALLBARS = [32, 39, 13, 12, 28, 26, 21, 35, 33]   # breathing, neon, rainbow,
#   symmetric radial, wave grad, heatmap, radial grad, chase, spinning  (todos 10 filas)
VARIETY_PERBAR = [2, 10, 20, 27]                          # pulse, h-wave, lin grad, pulse grad
# Acentos (flash) sobre percusión real.
ACCENT_FLASH = 0            # White Flash
ACCENT_LAYER = 3            # capa de overlay para los acentos
SEED = 7                    # determinismo

# ── Paleta + guión por segundos (cue sheet del usuario) ─────────────────────
# SOLO estos 3 colores en todo el show:
PALETTE = [(255, 255, 255), (255, 64, 160), (160, 32, 255)]   # blanco, rosa, morado
PALETTE_NAMES = ["blanco", "rosa", "morado"]

# Guión por segmentos (ms). 'slow' = luz lenta encendido/apagado (breathing);
# 'effect' = efecto variado. Huecos 0–25 y 1:17–1:30 completados en el mismo estilo.
SEGMENTS = [
    (0,     25_000, "slow"),    # intro (hueco completado): luz lenta
    (25_000, 31_000, "slow"),   # luz lenta encendido/apagado
    (31_000, 38_000, "effect"),
    (38_000, 42_000, "slow"),   # luz lenta encendido/apagado
    (42_000, 56_000, "effect"),
    (56_000, 66_000, "effect"),
    (66_000, 77_000, "effect"),
    (77_000, 90_000, "effect"),  # finale (hueco completado)
]
# Tramos 'slow': breathing per-bar (fade lento on/off), color de paleta.
SLOW_EFFECT = 1019
# Tramos 'effect': efectos GLOBALES 2D cross-bar que aceptan color (plugin color_global.py).
#   1030 chase-comet · 1031 ola 2D · 1032 radial desde el centro · 1033 sweep.
EFFECT_CYCLE = [1030, 1031, 1032, 1033]
SLOW_BLOCK_MS = 8_000        # cada cuánto cambia el color en tramos 'slow'
EFFECT_COLOR_BEATS = 2       # cada cuántos beats cambia el COLOR en tramos 'effect'
EFFECT_ROTATE_BEATS = 4      # cada cuántos beats cambia el EFECTO global
ACCENT_EVERY = 2             # acento (flash) 1 de cada N golpes (kick/snare) en 'effect'
ACCENT_FLASH_WHITE = 0       # White Flash (10 filas, scope global) — encaja en la paleta


# ─────────────────────────────────────────────────────────────────────────────
# Carga de análisis (beats, secciones, percusión) en milisegundos
# ─────────────────────────────────────────────────────────────────────────────
def load_analysis():
    p = ROOT / "analizadas" / ANALYSIS_SLUG / "analysis.json"
    a = json.load(open(p, encoding="utf-8"))

    beats = [int(round(t * 1000)) for t in a["beats_librosa"] if t * 1000 < LIMIT_MS]
    # Anclas de snap: el 0, todos los beats y el límite (para no perder bordes).
    snap_grid = sorted(set([0] + beats + [LIMIT_MS]))

    sections = []
    for s in a.get("sections", []):
        st = int(round(s["start"] * 1000))
        en = int(round(s["end"] * 1000))
        if st < LIMIT_MS:
            sections.append({"start": st, "end": min(en, LIMIT_MS),
                             "energy": s.get("energy", 0.0)})

    def ev_ms(group, key):
        out = []
        for e in a.get("events_percussive", {}).get(key, []):
            ms = int(round(e["start"] * 1000))
            if ms < LIMIT_MS:
                out.append(ms)
        return out

    kicks = ev_ms("events_percussive", "kick")
    snares = ev_ms("events_percussive", "snare")
    return beats, snap_grid, sections, kicks, snares


def nearest(grid, ms):
    """Valor de `grid` más cercano a ms (grid ordenado)."""
    i = bisect.bisect_left(grid, ms)
    if i == 0:
        return grid[0]
    if i >= len(grid):
        return grid[-1]
    lo, hi = grid[i - 1], grid[i]
    return lo if (ms - lo) <= (hi - ms) else hi


def next_in(grid, ms):
    """Primer valor de grid estrictamente mayor que ms (o ms+1 si no hay)."""
    i = bisect.bisect_right(grid, ms)
    return grid[i] if i < len(grid) else ms + 1


# ─────────────────────────────────────────────────────────────────────────────
# Fase 1 — recortar a barras LED + 0–90 s
# ─────────────────────────────────────────────────────────────────────────────
def trim_clips(clips):
    kept = []
    for c in clips:
        tr = c.get("track", -1)
        if not (0 <= tr <= 9):
            continue                       # fuera movers/wash/dimmer/generics
        if c.get("start_ms", 0) >= LIMIT_MS:
            continue
        c = copy.deepcopy(c)
        c["end_ms"] = min(c.get("end_ms", 0), LIMIT_MS)
        if c["end_ms"] <= c.get("start_ms", 0):
            continue
        kept.append(c)
    return kept


# ─────────────────────────────────────────────────────────────────────────────
# Fase 2 — snap a beats reales (mantiene contigüidad usando un mapa de bordes)
# ─────────────────────────────────────────────────────────────────────────────
def snap_clips(clips, snap_grid):
    # Mapa de cada borde distinto -> beat real más cercano (contigüidad preservada).
    edges = set()
    for c in clips:
        edges.add(c["start_ms"]); edges.add(c["end_ms"])
    bmap = {e: nearest(snap_grid, e) for e in edges}

    out = []
    for c in clips:
        s = bmap[c["start_ms"]]
        e = bmap[c["end_ms"]]
        if e <= s:
            e = next_in(snap_grid, s)      # garantiza >= 1 beat
        e = min(e, LIMIT_MS)
        if e <= s:
            continue
        c["start_ms"], c["end_ms"] = s, e
        out.append(c)
    return out


def on_beat_ratio(clips, beats):
    bs = set(beats)
    grid = sorted(bs)
    aligned = 0
    for c in clips:
        nb = nearest(grid, c["start_ms"]) if grid else -999
        if abs(c["start_ms"] - nb) <= 30:
            aligned += 1
    return aligned, len(clips)


def base_transitions(clips):
    """Cuenta cambios REALES de look base (layer 0): transiciones donde cambia
    effect_id respecto al clip base anterior (mismo track)."""
    base = [c for c in clips if c.get("layer", 0) == 0]
    by_track = {}
    for c in sorted(base, key=lambda c: (c.get("track"), c["start_ms"])):
        by_track.setdefault(c.get("track"), []).append(c)
    trans = 0
    for tr, seq in by_track.items():
        prev = None
        for c in seq:
            if prev is None or c["effect_id"] != prev:
                trans += 1
            prev = c["effect_id"]
    return trans


# ─────────────────────────────────────────────────────────────────────────────
# Fase 3 — más cambios de efecto + variedad (guiado por la música)
# ─────────────────────────────────────────────────────────────────────────────
def probe_effect_rows(effect_ids):
    """dim0 (nº de filas) de cada efecto: 10 = cubre las 10 barras, 1 = per-bar."""
    import numpy as np

    from src.core.effects_engine import EffectLibrary
    lib = EffectLibrary()
    bars = np.zeros((NUM_BARS, 93, 3), dtype=np.float32)
    actx = {"rms": 0.6, "flux": 0.4, "norm": {"rms": 0.6, "flux": 0.4},
            "bpm": 119.68, "beat_phase": 0.3}
    rows = {}
    for eid in effect_ids:
        eff = lib.get_effect(eid)
        if eff is None:
            continue
        try:
            rows[eid] = int(np.asarray(eff.render(0.5, bars, actx)).shape[0])
        except Exception:
            pass
    return rows


def add_variety(clips, beats, rows, rng):
    """Rompe las tiradas largas del MISMO look base alternando efectos del
    catálogo, sin cambiar más rápido que BASE_CHANGE_EVERY_BEATS. El efecto de
    sustitución SIEMPRE tiene el mismo nº de filas que el original (no rompe la
    cobertura de barras)."""
    beat_grid = sorted(set(beats))
    if not beat_grid:
        return clips
    span = BASE_CHANGE_EVERY_BEATS
    # Pools válidos por nº de filas (solo efectos cuyo dim0 conocemos).
    pool10 = [e for e in VARIETY_ALLBARS if rows.get(e) == 10]
    pool1 = [e for e in VARIETY_PERBAR if rows.get(e) == 1]

    base = [c for c in clips if c.get("layer", 0) == 0]
    by_track = {}
    for c in base:
        by_track.setdefault(c.get("track"), []).append(c)

    pal_idx = 0
    for tr, seq in by_track.items():
        seq.sort(key=lambda c: c["start_ms"])
        i = 0
        while i < len(seq):
            j = i
            while j + 1 < len(seq) and seq[j + 1]["effect_id"] == seq[i]["effect_id"] \
                    and seq[j + 1]["start_ms"] == seq[j]["end_ms"]:
                j += 1
            run = seq[i:j + 1]
            base_eff = run[0]["effect_id"]
            # Pool de sustitución con el MISMO nº de filas que el efecto original.
            pool = pool10 if rows.get(base_eff) == 10 else (pool1 if rows.get(base_eff) == 1 else [])
            pool = [e for e in pool if e != base_eff]
            run_start, run_end = run[0]["start_ms"], run[-1]["end_ms"]
            bi0 = bisect.bisect_left(beat_grid, run_start)
            bi1 = bisect.bisect_left(beat_grid, run_end)
            if pool and (bi1 - bi0) > span * 2:
                for c in run:
                    blk = bisect.bisect_left(beat_grid, c["start_ms"]) // span
                    if blk % 2 == 1:                       # bloques impares = variedad
                        c["effect_id"] = pool[pal_idx % len(pool)]
                        c["params"] = {}
                        c["label"] = f"{c.get('label','')} · var".strip(" ·")
                        pal_idx += 1
            i = j + 1
    return clips


def add_accents(clips, kicks, snares, sections, beats, rng):
    """Acentos cortos (flash) sobre kicks/snares reales, más densos en
    secciones de más energía. Capa de overlay (no pisa la base)."""
    beat_grid = sorted(set(beats))
    if not beat_grid:
        return clips, 0

    # Normaliza energía de sección a densidad (cada cuántos kicks ponemos acento).
    energies = [s["energy"] for s in sections] or [0.2]
    emax = max(energies) or 1.0

    def density_step(ms):
        sec = next((s for s in sections if s["start"] <= ms < s["end"]), None)
        if sec is None:
            return 4
        frac = sec["energy"] / emax            # 0..1
        # más energía -> step menor (más acentos). step en {2,3,4}
        return 2 if frac > 0.8 else (3 if frac > 0.45 else 4)

    added = 0
    # Acentos en kicks (blanco) — uno de cada `step`.
    for src, color in ((kicks, "#ffffff"), (snares, "#ffd2a6")):
        last = -1
        for idx, ms in enumerate(src):
            step = density_step(ms)
            if idx % step != 0:
                continue
            s = nearest(beat_grid, ms)
            if abs(s - ms) > 120:              # solo si hay un beat cerca
                s = ms
            e = next_in(beat_grid, s)
            e = min(e, LIMIT_MS)
            if e <= s or s == last:
                continue
            last = s
            clips.append({
                "track": -1, "start_ms": s, "end_ms": e,
                "effect_id": ACCENT_FLASH, "scope": "global", "params": {},
                "label": "Acento", "color": color, "layer": ACCENT_LAYER,
                "locked": False, "muted": False, "category": "pixel",
                "channel_effect_id": None,
            })
            added += 1
    return clips, added


# ─────────────────────────────────────────────────────────────────────────────
# Rig recortado a las 10 barras LED
# ─────────────────────────────────────────────────────────────────────────────
def make_rig():
    """Rig con solo las 10 barras LED, ALINEADAS en una fila limpia y
    equiespaciada. Patch 2D y visor 3D quedan IDÉNTICOS desde el arranque:
      - 3D: misma altura (y=1) y profundidad (z=0); x equiespaciada en el
        escenario (ancho 12) → x = ((i+0.5)/10 - 0.5) * 12 = -5.4..+5.4.
      - 2D: patch_x = x/12 + 0.5 = 0.05..0.95 (mismo mapeo que el acople
        _h_move_fixture), patch_y = 0.5 (centro).
    Se conserva todo lo demás del fixture (universo, dmx, ip, profile,
    legacy_bar_idx); solo se sobrescriben position + patch_x/patch_y."""
    rig = json.load(open(ROOT / "projects" / SRC_SLUG / "rig.json", encoding="utf-8"))
    rig = copy.deepcopy(rig)
    bars = [f for f in rig.get("fixtures", [])
            if str(f.get("fixture_id", "")).startswith("bar_")]
    # Orden estable por índice de barra (0..9).
    bars.sort(key=lambda f: (f.get("legacy_bar_idx")
                             if f.get("legacy_bar_idx") is not None
                             else f.get("fixture_id", "")))
    STAGE_W = 12.0
    n = len(bars)
    for i, f in enumerate(bars):
        frac = (i + 0.5) / n                 # 0.05, 0.15, ..., 0.95
        x = round((frac - 0.5) * STAGE_W, 3)  # -5.4 .. +5.4
        f["position"] = [x, 1.0, 0.0]         # misma altura/profundidad
        f["patch_x"] = round(frac, 6)         # = x/STAGE_W + 0.5
        f["patch_y"] = 0.5
    rig["fixtures"] = bars
    return rig


# ─────────────────────────────────────────────────────────────────────────────
# Construcción del show por segmentos (cue sheet + paleta blanco/rosa/morado)
# ─────────────────────────────────────────────────────────────────────────────
def _clips_all_bars(start, end, eff, color, label):
    """10 clips (track 0..9, scope per_bar) = un look uniforme en las 10 barras.
    Es la única forma de que un efecto per-bar pinte todas las barras, y al ser
    idéntico en todas queda simétrico/CENTRADO."""
    r, g, b = color
    params = {"r": r, "g": g, "b": b}
    if eff == SLOW_EFFECT:               # breathing lento (encendido/apagado)
        params.update({"rate_hz": 0.3, "min_brightness": 0.03})
    hexc = "#%02x%02x%02x" % (r, g, b)
    out = []
    for tr in range(NUM_BARS):
        out.append({
            "track": tr, "start_ms": int(start), "end_ms": int(end),
            "effect_id": eff, "scope": "per_bar", "params": dict(params),
            "label": label, "color": hexc, "layer": 0,
            "locked": False, "muted": False, "category": "pixel",
            "channel_effect_id": None,
        })
    return out


def _accent_clip(start, end):
    """Flash blanco (efecto 0, 10 filas, scope global) en overlay → punch en el golpe.
    track=-1 = pista GLOBAL (se dibuja en el lane 'GLOBAL' del timeline)."""
    return {
        "track": -1, "start_ms": int(start), "end_ms": int(end),
        "effect_id": ACCENT_FLASH_WHITE, "scope": "global", "params": {},
        "label": "acento", "color": "#ffffff", "layer": 2,
        "locked": False, "muted": False, "category": "pixel", "channel_effect_id": None,
    }


def _clip_global(start, end, eff, color, label):
    """Un clip global (scope='global') con un efecto cross-bar de color → un solo
    clip pinta las 10 barras. track=-1 = pista GLOBAL (el timeline lo dibuja en su
    propio lane 'GLOBAL', arriba de las barras)."""
    r, g, b = color
    return {
        "track": -1, "start_ms": int(start), "end_ms": int(end),
        "effect_id": eff, "scope": "global", "params": {"r": r, "g": g, "b": b},
        "label": label, "color": "#%02x%02x%02x" % (r, g, b), "layer": 0,
        "locked": False, "muted": False, "category": "pixel", "channel_effect_id": None,
    }


def build_timeline(beats, kicks, snares):
    """Construye el timeline desde SEGMENTS, snapeado a beats reales, con SOLO la
    paleta blanco/rosa/morado. 'slow' = breathing lento (calmado); 'effect' =
    efecto asignado con cambios de color rápidos (cada EFFECT_COLOR_BEATS) MÁS
    acentos de flash blanco sobre kicks/snares reales (punch, como en el anterior).
    Looks per-bar (10 clips) = uniformes/centrados; acentos globales por encima."""
    grid = sorted(set([0] + list(beats) + [LIMIT_MS]))
    hits = sorted(set(kicks) | set(snares))
    clips = []
    eff_i = 0
    col_i = 0
    for (a0, b0, kind) in SEGMENTS:
        a, b = nearest(grid, a0), nearest(grid, b0)
        if b <= a:
            continue
        if kind == "slow":
            # Bloques de color de ~SLOW_BLOCK_MS, cada uno una breathing lenta.
            t = a
            while t < b:
                t2 = min(nearest(grid, t + SLOW_BLOCK_MS), b)
                if t2 <= t:
                    t2 = b
                color = PALETTE[col_i % 3]
                clips += _clips_all_bars(
                    t, t2, SLOW_EFFECT, color,
                    f"Luz lenta {PALETTE_NAMES[col_i % 3]}")
                col_i += 1
                t = t2
        else:
            # Efectos GLOBALES 2D cross-bar (1 clip pinta las 10 barras). El COLOR
            # cambia cada EFFECT_COLOR_BEATS y el EFECTO rota cada EFFECT_ROTATE_BEATS
            # → muchos cambios. Offset por segmento para variar entre tramos.
            seg_beats = [t for t in grid if a <= t < b] + [b]
            k = 0
            while k < len(seg_beats) - 1:
                kk = min(k + EFFECT_COLOR_BEATS, len(seg_beats) - 1)
                t, t2 = seg_beats[k], seg_beats[kk]
                color = PALETTE[col_i % 3]
                eff = EFFECT_CYCLE[(eff_i + k // EFFECT_ROTATE_BEATS) % len(EFFECT_CYCLE)]
                clips.append(_clip_global(
                    t, t2, eff, color, f"efecto {PALETTE_NAMES[col_i % 3]}"))
                col_i += 1
                k = kk
            eff_i += 1   # desplaza la rotación de efecto para el siguiente tramo
            # Acentos (flash blanco) sobre kicks/snares dentro del tramo.
            seg_hits = [h for h in hits if a <= h < b]
            for n, h in enumerate(seg_hits):
                if n % ACCENT_EVERY != 0:
                    continue
                hs = nearest(grid, h)
                he = next_in(grid, hs)
                if he > hs:
                    clips.append(_accent_clip(hs, min(he, b)))
    return clips


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    beats, snap_grid, sections, kicks, snares = load_analysis()
    print(f"[+] análisis: {len(beats)} beats <90s · {len(sections)} secciones")

    src = json.load(open(ROOT / "projects" / SRC_SLUG / "show.json", encoding="utf-8"))

    # Show construido desde el guión (SEGMENTS) con paleta blanco/rosa/morado.
    clips = build_timeline(beats, kicks, snares)
    n_acc = sum(1 for c in clips if c.get("label") == "acento")
    al, tot = on_beat_ratio(clips, beats)
    print(f"[show] {len(clips)} clips ({n_acc} acentos) · on-beat {al}/{tot} · "
          f"colores: blanco/rosa/morado · efectos {sorted(set(EFFECT_CYCLE+[SLOW_EFFECT]))}")

    # cue_points = límites de los segmentos del guión (referencia en el timeline).
    cues = []
    for i, (a, b, kind) in enumerate(SEGMENTS):
        if i >= 9:
            break
        cues.append({"slot": i + 1, "time_ms": a,
                     "name": ("Luz lenta" if kind == "slow" else "Efecto"),
                     "color": "#ff40a0"})

    show = {
        "version": src.get("version", 2),
        "duration_ms": LIMIT_MS,
        "clips": clips,
        "groups": src.get("groups", []),
        "cue_points": cues,
        "markers": [],
    }

    # ── Escribir proyecto ──────────────────────────────────────────────────
    dst = ROOT / "projects" / DST_SLUG
    dst.mkdir(parents=True, exist_ok=True)

    project = {
        "slug": DST_SLUG,
        "name": DST_NAME,
        "audio_path": str(ROOT / "El Taser de Mama Remix.mp3"),
        "analysis_slug": ANALYSIS_SLUG,
        "created": "2026-06-16T00:00:00",
        "notes": "Barras LED 0–1:30. Guión por segmentos (luz lenta + efectos), "
                 "paleta blanco/rosa/morado, sync a beats reales, barras alineadas "
                 "y centradas. Generado por scripts/create_taser_barras.py.",
    }
    json.dump(project, open(dst / "project.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    json.dump(make_rig(), open(dst / "rig.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    json.dump(show, open(dst / "show.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    print(f"[✓] proyecto creado: projects/{DST_SLUG}/ "
          f"(rig {len(make_rig()['fixtures'])} barras, {len(clips)} clips, {LIMIT_MS//1000}s)")
    print(f"    Arranca con:  set LUCES_PROJECT={DST_SLUG}  →  python -m server.main")


if __name__ == "__main__":
    main()
