"""
offline_render.py — Fase B3: render offline del timeline completo a frames numpy.

El render offline bakea SOLO la parte timeline_render (sin postfx/master).
El postfx/master (B2) se aplica en runtime sobre los frames bakeados, así el
modo baked sigue siendo "tocable" en directo (macros de B2 siguen funcionando).

Invariante I4 CRÍTICO:
    _render_worker corre en loop.run_in_executor → NUNCA en el event loop.
    Si bloquea el tick aunque sea 1 s, el show en vivo se congela.

Copia congelada OBLIGATORIA:
    El worker usa una copia independiente del timeline (Timeline.from_dict del
    snapshot). Si usara session.timeline directamente, una edición a mitad de
    render corrompería el npz silenciosamente.

Guardado atómico:
    Se escribe a render_tmp.npz y se hace os.replace → nunca npz corrupto.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from src.log import get_logger, log_throttled

_log = get_logger(__name__)

# ── Constantes ───────────────────────────────────────────────────────────────

_FPS = 30
_BUCKET_MS = 500

_FALLBACK_ACTX: dict = {
    'rms': 0.5, 'energy': 0.5, 'flux': 0.3, 'centroid': 4000.0, 'zcr': 0.2,
    'rolloff': 3000.0, 'bandwidth': 2000.0, 'flatness': 0.1, 'dtempo': 0.0,
    'mfcc': np.zeros(13, dtype=np.float32),
    'chroma': np.full(12, 0.5, dtype=np.float32),
    'tonnetz': np.zeros(6, dtype=np.float32),
    'contrast': np.full(7, 30.0, dtype=np.float32),
    'mel_bands': np.full(8, -25.0, dtype=np.float32),
    'norm': {
        'rms': 0.5, 'energy': 0.5, 'flux': 0.3, 'centroid': 0.5, 'zcr': 0.2,
        'rolloff': 0.5, 'bandwidth': 0.5, 'flatness': 0.1, 'dtempo': 0.0,
    },
}


# ── Hash de show (para invalidación) ─────────────────────────────────────────

def compute_timeline_hash(tl_dict: dict) -> str:
    """MD5 del dict del timeline serializado — para detectar que el render es obsoleto."""
    return hashlib.md5(
        json.dumps(tl_dict, sort_keys=True, ensure_ascii=True, default=str).encode()
    ).hexdigest()


# ── Worker síncrono ───────────────────────────────────────────────────────────

def _resolve_scope_bars_worker(scope: str, groups: list) -> list:
    """Replica _resolve_scope_bars de ShowSession, para el worker thread."""
    if not isinstance(scope, str):
        return []
    if scope.startswith('group:') or scope.startswith('group_set:'):
        target = scope.split(':', 1)[1]
        for g in groups:
            if g.name == target:
                return g.resolve_bars(groups)
    return []


def _expand_pattern_instances(frozen_tl) -> list:
    """Expande PatternInstances a Clips efímeros (igual que ShowSession._expand_all_pattern_instances)."""
    from src.core.effects_engine import NUM_BARS
    from src.core.timeline_model import Clip, Pattern, PatternInstance

    result = []
    for inst_d in frozen_tl.pattern_instances:
        inst = PatternInstance.from_dict(inst_d)
        pat_d = next(
            (p for p in frozen_tl.patterns if p.get("uid") == inst.pattern_uid),
            None,
        )
        if pat_d is None:
            continue
        pat = Pattern.from_dict(pat_d)
        for clip in pat.clips:
            result.append(Clip(
                track=max(0, min(NUM_BARS - 1, clip.track + inst.track_offset)),
                start_ms=inst.start_ms + clip.start_ms,
                end_ms=inst.start_ms + clip.end_ms,
                effect_id=clip.effect_id,
                scope=clip.scope,
                params=dict(clip.params),
                color=clip.color,
                label=clip.label,
                layer=clip.layer,
                locked=False,
                muted=clip.muted,
                category=clip.category,
                channel_effect_id=clip.channel_effect_id,
                preset_id=clip.preset_id,
                uid=f"{inst.uid}::{clip.uid}",
                param_links=list(clip.param_links),
            ))
    return result


def _render_worker(
    frozen_tl,
    library: Any,
    analysis: Any,
    n_frames: int,
    fps: int,
    out_path: Path,
    show_hash: str,
    progress_fn: Callable[[float], None] | None,
) -> None:
    """Worker síncrono de render offline. Corre en executor (I4).

    Renderiza SOLO la parte timeline_render — sin postfx/master (eso se aplica
    en runtime sobre los frames bakeados). numpy suelta el GIL en operaciones
    vectorizadas, así el event loop del servidor sigue respondiendo.

    Args:
        frozen_tl:    Timeline congelado (copia independiente, NO la sesión viva).
        library:      EffectLibrary compartida (sólo lectura).
        analysis:     AnalysisService (sólo lectura) o None.
        n_frames:     Número total de frames a renderizar.
        fps:          Frames por segundo (30).
        out_path:     Ruta del npz de salida (guardado atómico).
        show_hash:    Hash del timeline para render_meta.json.
        progress_fn:  Callback(pct: float) thread-safe o None.
    """
    from src.core.automation import AutomationLane, AutomationStage
    from src.core.effects_engine import LEDS_PER_BAR, NUM_BARS
    from src.core.micro_events import MicroEventStage
    from src.core.modulation import ModulationStage
    from src.core.param_pipeline import resolve_params

    LEDS = LEDS_PER_BAR  # 93

    # ── Pipeline de parámetros (igual que ShowSession) ────────────────────────
    automation_lanes = [AutomationLane.from_dict(d) for d in frozen_tl.automation]
    param_stages = [
        ModulationStage(),
        AutomationStage(get_automation_lanes=lambda: automation_lanes),
        MicroEventStage(),
    ]

    # ── Bucket index (clips reales + efímeros de patterns) ────────────────────
    expanded = _expand_pattern_instances(frozen_tl)
    all_clips = frozen_tl.clips + expanded
    buckets: dict = {}
    for c in all_clips:
        b_lo = max(0, c.start_ms // _BUCKET_MS)
        b_hi = max(b_lo, c.end_ms // _BUCKET_MS)
        for b in range(b_lo, b_hi + 1):
            buckets.setdefault(b, []).append(c)
    for b in buckets:
        buckets[b].sort(key=lambda c: c.layer)

    groups = frozen_tl.groups  # para resolver scopes de grupo

    # ── Array de salida ────────────────────────────────────────────────────────
    frames = np.zeros((n_frames, NUM_BARS, LEDS, 3), dtype=np.uint8)

    last_pct = -1.0

    for frame_idx in range(n_frames):
        t_s = frame_idx / fps
        t_ms = int(t_s * 1000)

        # Audio context: real si hay análisis, fallback estático si no
        actx = _FALLBACK_ACTX
        if analysis is not None:
            try:
                if getattr(analysis, 'has_timeseries', False):
                    actx = analysis.get_audio_context(t_s)
            except Exception:
                pass

        # ── Renderizar frame (mismo algoritmo que compute_frame, sin postfx) ──
        frame = np.zeros((NUM_BARS, LEDS, 3), dtype=np.uint8)
        bucket = t_ms // _BUCKET_MS

        for clip in buckets.get(bucket, ()):
            if clip.start_ms > t_ms or clip.end_ms <= t_ms:
                continue
            if getattr(clip, 'muted', False):
                continue
            eff = library.get_effect(clip.effect_id)
            if not eff:
                continue
            params = resolve_params(clip, t_ms, actx, param_stages,
                                    base_params=clip.params)
            try:
                r = eff.render(elapsed_time=t_ms - clip.start_ms,
                               bars_state=frame,
                               audio_context=actx, **params)
                group_bars = _resolve_scope_bars_worker(clip.scope, groups)
                if group_bars:
                    if r.shape == (1, LEDS, 3):
                        for b in group_bars:
                            if 0 <= b < NUM_BARS:
                                frame[b] = np.maximum(frame[b], r[0])
                    elif r.shape == (NUM_BARS, LEDS, 3):
                        for b in group_bars:
                            if 0 <= b < NUM_BARS:
                                frame[b] = np.maximum(frame[b], r[b])
                    continue
                if r.shape == (1, LEDS, 3) and 0 <= clip.track < NUM_BARS:
                    frame[clip.track] = (np.maximum(frame[clip.track], r[0])
                                         if clip.layer > 0 else r[0])
                elif r.shape == (NUM_BARS, LEDS, 3):
                    if clip.scope == 'global':
                        frame = np.maximum(frame, r)
                    else:
                        frame[clip.track] = np.maximum(frame[clip.track],
                                                        r[clip.track])
            except Exception as _e:
                # Un efecto buggy NO debe abortar el render entero; pero tampoco
                # debe dejar frames negros en silencio (antes: except: pass).
                log_throttled(_log, logging.WARNING, f"render_fail:{clip.effect_id}",
                              f"efecto {clip.effect_id} falló en render offline: {_e}")

        frames[frame_idx] = frame

        # ── Progreso: emitir cada 1% ──────────────────────────────────────────
        if progress_fn is not None:
            pct = frame_idx / n_frames * 100.0
            if pct - last_pct >= 1.0:
                last_pct = pct
                try:
                    progress_fn(round(pct, 1))
                except Exception:
                    pass

    # ── Guardado atómico (tmp → replace) ─────────────────────────────────────
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # np.savez_compressed añade '.npz' si no está presente → usar stem sin extensión
    stem = str(out_path.with_name('render_tmp'))
    np.savez_compressed(stem, frames=frames)
    tmp_npz = out_path.with_name('render_tmp.npz')
    os.replace(str(tmp_npz), str(out_path))

    # render_meta.json (atómico)
    meta = {
        "fps": fps,
        "duration_s": round(n_frames / fps, 3),
        "n_frames": n_frames,
        "show_hash": show_hash,
    }
    meta_path = out_path.parent / "render_meta.json"
    tmp_meta = meta_path.with_suffix('.tmp')
    with open(tmp_meta, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2)
    os.replace(str(tmp_meta), str(meta_path))


# ── Orchestrador async ────────────────────────────────────────────────────────

def _make_progress_callback(loop: asyncio.AbstractEventLoop, hub: Any) -> Callable:
    """Devuelve una función thread-safe que emite render_progress al stream hub."""
    def _callback(pct: float) -> None:
        asyncio.run_coroutine_threadsafe(
            hub.broadcast_json({"type": "render_progress", "pct": pct}),
            loop,
        )
    return _callback


async def start_render(session) -> None:
    """Lanza el render offline del timeline completo en un executor (I4).

    Usa una COPIA CONGELADA del timeline — si el usuario edita mientras el
    worker corre, el npz sigue siendo coherente con el estado al momento del
    lanzamiento.

    El worker NO bloquea el tick (corre en thread pool). Cuando termina, emite
    render_progress pct=100 done=True al stream hub.
    """
    from src.core.timeline_model import Timeline

    if getattr(session, 'render_in_progress', False):
        return  # ya hay un render en curso

    # ── Snapshot congelado — CRÍTICO ──────────────────────────────────────────
    frozen_tl_dict = session.timeline.to_dict()
    frozen_tl = Timeline.from_dict(frozen_tl_dict)

    show_hash = compute_timeline_hash(frozen_tl_dict)

    out_path = session.project.folder / "render.npz"
    fps = _FPS
    duration_s = session.duration or (session.timeline.duration_ms / 1000.0)
    n_frames = max(1, round(duration_s * fps))

    # ── Progreso thread-safe ──────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    hub = getattr(session, 'hub', None)
    progress_fn = _make_progress_callback(loop, hub) if hub else None

    session.render_in_progress = True
    session.render_pct = 0.0

    try:
        await loop.run_in_executor(
            None,
            _render_worker,
            frozen_tl,
            session.library,
            session.analysis,
            n_frames,
            fps,
            out_path,
            show_hash,
            progress_fn,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(
            f"[offline_render] Error en _render_worker: {e}", exc_info=True
        )
    finally:
        session.render_in_progress = False
        session.render_pct = 100.0
        if hub:
            asyncio.ensure_future(
                hub.broadcast_json({"type": "render_progress", "pct": 100.0, "done": True})
            )
