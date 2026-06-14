"""
dispatcher.py — Capa JSON-RPC Qt-free reutilizando los 52 handlers del bridge.

En vez de re-escribir los handlers de `src/mcp/mcp_bridge.py` (riesgo de
divergencia), los **reutilizamos** tal cual:

  * Los handlers son funciones de módulo `_h_<name>(app, params)` que acceden al
    modelo SOLO vía atributos de `app` (timeline/show_engine/fixture_rig/
    analysis/library/audio). `ShowSession` expone exactamente esos atributos
    (+ shims `tl_view`/`props`/`_pm`/`_project`), así que es un `app` válido.
  * El marshalling de mutaciones del bridge (`_qt_call`/`_qt_call_dual`) lo provee
    la sesión vía `_qt_call_impl`/`_qt_call_dual_impl`: ejecuta `fn()` inline
    (estamos en un único loop asyncio) y dispara `session.notify_changed()` para
    que el stream avise al navegador (los `_dual` además notifican cambios de rig).
    La rama Qt original (QTimer) se retiró en la Fase 8.

Resultado: `Dispatcher.handle(msg)` procesa un mensaje JSON-RPC 2.0 idéntico al
del bridge — el MISMO protocolo que ya habla `mcp_show_server.py` (Claude).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Setup MINIMAL de sys.path ANTES de importar src._setup_paths
# (necesario porque src._setup_paths es lo que configura sys.path correctamente)
_root = Path(__file__).resolve().parent.parent  # server/dispatcher.py → show-director/
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Setup centralizado de sys.path (única fuente de verdad)
from src._setup_paths import *

import src.mcp.mcp_bridge as bridge  # noqa: E402
from server.exporters import export_to_memory  # noqa: E402
from server.validators import ValidationError, require_int, require_order, require_key  # noqa: E402
from server.toggles import toggle_set_membership  # noqa: E402


# ── Desacople (B1) ───────────────────────────────────────────────────────────
# Antes aquí se parcheaba el módulo global `bridge._qt_call`/`_qt_call_dual`.
# Ahora la política headless vive en ShowSession (`_qt_call_impl` /
# `_qt_call_dual_impl`) y el bridge la detecta vía getattr sobre `app`. Esto
# elimina la mutación de estado global del módulo (más robusto y testeable).


# Métodos de debug que dependen de widgets Qt concretos (tabs, canvas): se
# excluyen del dispatcher web (no aplican sin la ventana PyQt5).
_EXCLUDED = {"debug_switch_tab", "debug_analyzer"}


# ── Handlers locales (web-only) — no existen en el bridge MCP ────────────────
# Operan directamente sobre el ShowSession. Tienen prioridad sobre HANDLERS.
def _h_set_loop(session, params):
    session.loop = bool(params.get("on", not session.loop))
    return {"ok": True, "loop": session.loop}


def _h_set_rec(session, params):
    session.rec = bool(params.get("on", not session.rec))
    return {"ok": True, "rec": session.rec}


def _h_set_volume(session, params):
    session.audio.set_volume(float(params.get("value", 1.0)))
    return {"ok": True}


def _h_set_track_mute(session, params):
    try:
        track = require_int(params, "track")
        on = toggle_set_membership(session.muted_tracks, track, params.get("on"))
        session.notify_changed("tracks")
        return {"ok": True, "muted": sorted(session.muted_tracks)}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}


def _h_set_track_solo(session, params):
    try:
        track = require_int(params, "track")
        on = toggle_set_membership(session.solo_tracks, track, params.get("on"))
        session.notify_changed("tracks")
        return {"ok": True, "solo": sorted(session.solo_tracks)}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}


def _h_get_tracks_state(session, params):
    return {"muted": sorted(session.muted_tracks), "solo": sorted(session.solo_tracks)}


def _h_undo(session, params):
    ok = session.undo()
    return {"ok": ok, "clip_count": len(session.timeline.clips)}


def _h_redo(session, params):
    ok = session.redo()
    return {"ok": ok, "clip_count": len(session.timeline.clips)}


# Métodos que mutan los clips del timeline → snapshot para undo
_TIMELINE_MUTATORS = {
    "add_clip", "delete_clip", "move_clip", "set_clip_color", "set_clip_params",
    "set_clip_mute", "set_clip_lock", "set_clip_scope", "set_clip_effect",
    "add_channel_clip", "add_preset_clip", "duplicate_clip", "split_clip",
    "delete_range",  # I4 — Arranger
    "set_clip_preset",
    "generate_section", "mirror_clips_lr", "apply_palette_to_range", "load_show",
    # A3 — mutadores de patterns/instances (el snapshot se hace dentro del handler,
    # no en el dispatcher, porque necesitan snapshotear ANTES de resolver lookup)
    # create_pattern_from_clips y los demás llaman session.snapshot() internamente.
    # I2 — mutadores de marcadores de timeline
    "add_marker", "delete_marker", "update_marker",
}

# Métodos que mutan el rig de fixtures → regenerar rig_layout.json para el visor 3D
# (si no, el visor muestra posiciones obsoletas tras mover/editar fixtures en Patch).
_RIG_MUTATORS = {
    "move_fixture", "set_fixture_property", "add_fixture", "delete_fixture",
    "save_rig", "load_show",
}


def _h_get_effect_schema(session, params):
    """get_effect_schema(effect_id) → {ok, schema: dict}
    Devuelve el PARAM_SCHEMA del efecto indicado. Schema vacío ({}) si no tiene."""
    try:
        effect_id = require_int(params, "effect_id", min_val=0)
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    lib = getattr(session, "library", None)
    effect = lib.get_effect(effect_id) if lib else None
    if effect is None:
        return {"ok": False, "error": f"effect_id {effect_id} no encontrado"}
    return {"ok": True, "schema": getattr(effect, "PARAM_SCHEMA", {})}


def _h_preview_effect_frame(session, params):
    """preview_effect_frame(effect_id, params={}, t_ms=0) → {ok, frame_b64: str}
    Renderiza un frame del efecto con los params dados y lo devuelve como PNG base64.
    Sin estado en la sesión, sin tocar el timeline. < 50 ms (síncrono OK).
    Fallback sin Pillow: devuelve el array raw como lista JSON."""
    try:
        effect_id = require_int(params, "effect_id", min_val=0)
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    lib = getattr(session, "library", None)
    effect = lib.get_effect(effect_id) if lib else None
    if effect is None:
        return {"ok": False, "error": f"effect_id {effect_id} no encontrado"}

    import numpy as np
    from src.core.effects_engine import EffectScope, NUM_BARS, LEDS_PER_BAR

    t_ms = float(params.get("t_ms", 0))
    effect_params = dict(params.get("params") or {})
    bars_state = np.zeros((NUM_BARS, LEDS_PER_BAR, 3), dtype=np.uint8)
    audio_ctx: dict = {}

    try:
        frame = effect.render(t_ms, bars_state, audio_ctx, **effect_params)
    except Exception as e:
        return {"ok": False, "error": f"render error: {e}"}

    # Normalizar shape a (rows, LEDS_PER_BAR, 3)
    if frame.ndim == 3 and frame.shape[0] == 1:
        img_arr = frame[0:1]   # PER_BAR → 1 fila
    else:
        img_arr = frame        # ALL_BARS → 10 filas

    import os as _os
    no_pillow = _os.environ.get("LUCES_NO_PILLOW") == "1"
    if no_pillow:
        return {"ok": True, "frame_raw": img_arr.tolist()}

    try:
        import base64, io
        from PIL import Image
        # Escalar 2× para visibilidad mínima
        scale = 2
        h, w = img_arr.shape[:2]
        pil = Image.fromarray(img_arr.astype(np.uint8), "RGB")
        pil = pil.resize((w * scale, h * scale), Image.NEAREST)
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {"ok": True, "frame_b64": b64, "width": w * scale, "height": h * scale}
    except ImportError:
        return {"ok": True, "frame_raw": img_arr.tolist()}


def _h_set_clip_effect(session, params):
    """Cambia el efecto (effect_id) de un clip pixel. No existe en el bridge."""
    try:
        clip_id = require_key(params, "clip_id")
        effect_id = require_int(params, "effect_id", min_val=0)
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    c = session.find_clip_by_id(clip_id)
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    # Validar params opcionales contra el schema del efecto destino
    extra_params = params.get("params")
    if extra_params:
        lib = getattr(session, "library", None)
        effect = lib.get_effect(effect_id) if lib else None
        schema = getattr(effect, "PARAM_SCHEMA", {}) if effect else {}
        try:
            from server.validators import validate_params_against_schema
            validate_params_against_schema(extra_params, schema)
        except ValidationError as e:
            return {"ok": False, "error": str(e)}
        c.params = dict(extra_params)
    c.effect_id = effect_id
    if params.get("label") is not None:
        c.label = params["label"]
    session.invalidate_caches()
    return {"ok": True}


def _h_set_clip_preset(session, params):
    """Aplica un preset (pixel o canal) a un clip EXISTENTE, conservando su
    posición (start/end/track/layer). Espeja la asignación de _h_add_preset_clip.
    Permite 'pintar' presets con click en modo draw."""
    try:
        clip_id = require_key(params, "clip_id")
        preset_id = require_key(params, "preset_id")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    c = session.find_clip_by_id(clip_id)
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    p = session.presets.get(preset_id)
    if p is None:
        return {"ok": False, "error": "preset no encontrado"}
    # Validar params del preset contra el schema del efecto destino
    if p.params and p.kind != "channel":
        lib = getattr(session, "library", None)
        effect = lib.get_effect(p.base_effect_id) if lib else None
        schema = getattr(effect, "PARAM_SCHEMA", {}) if effect else {}
        try:
            from server.validators import validate_params_against_schema
            validate_params_against_schema(p.params, schema)
        except ValidationError as e:
            return {"ok": False, "error": f"preset params inválidos: {e}"}
    c.params = dict(p.params)
    c.color = p.color
    c.label = p.name
    c.preset_id = p.preset_id
    if getattr(p, "param_links", None):
        c.param_links = list(p.param_links)
    if p.kind == "channel":
        c.category = p.category
        c.channel_effect_id = p.channel_effect_id
    else:
        c.effect_id = p.base_effect_id
        c.category = "pixel"
        c.channel_effect_id = None
    session.invalidate_caches()
    return {"ok": True, "clip": c.to_dict()}


def _h_duplicate_clip(session, params):
    """Duplica un clip (mismo efecto/params), desplazado o en otra capa/track."""
    from core.timeline_model import Clip
    c = session.find_clip_by_id(params["clip_id"])
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    dur = c.end_ms - c.start_ms
    start = int(params.get("start_ms", c.start_ms + dur))
    nc = Clip(
        track=int(params.get("track", c.track)),
        start_ms=start, end_ms=start + dur,
        effect_id=c.effect_id, scope=c.scope, color=c.color,
        layer=int(params.get("layer", c.layer)), label=c.label,
        muted=c.muted, params=dict(c.params or {}),
        category=getattr(c, "category", "pixel"),
        channel_effect_id=getattr(c, "channel_effect_id", None),
    )
    session.timeline.add(nc)
    session.invalidate_caches()
    return {"ok": True, "clip": nc.to_dict()}


def _h_split_clip(session, params):
    """Parte un clip en dos en t_ms (cursor)."""
    from core.timeline_model import Clip
    c = session.find_clip_by_id(params["clip_id"])
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    t_ms = int(params["t_ms"])
    if not (c.start_ms < t_ms < c.end_ms):
        return {"ok": False, "error": "el cursor no está dentro del clip"}
    orig_end = c.end_ms
    c.end_ms = t_ms
    nc = Clip(
        track=c.track, start_ms=t_ms, end_ms=orig_end,
        effect_id=c.effect_id, scope=c.scope, color=c.color,
        layer=c.layer, label=c.label, muted=c.muted, params=dict(c.params or {}),
        category=getattr(c, "category", "pixel"),
        channel_effect_id=getattr(c, "channel_effect_id", None),
    )
    session.timeline.add(nc)
    session.invalidate_caches()
    return {"ok": True}


# ── Feedback log (vista Live) — persiste en projects/<slug>/feedback.json ────
def _feedback_path(session):
    return session.project.folder / "feedback.json"


def _h_list_feedback(session, params):
    import json
    p = _feedback_path(session)
    if not p.is_file():
        return {"entries": []}
    try:
        with open(p, encoding="utf-8") as f:
            return {"entries": json.load(f)}
    except Exception:
        return {"entries": []}


def _h_add_feedback(session, params):
    import json
    p = _feedback_path(session)
    entries = _h_list_feedback(session, {})["entries"]
    entry = {
        "t": float(params.get("t", session.time)),
        "section": params.get("section", session.section_name_at(session.time)),
        "text": params.get("text", ""),
        "cats": params.get("cats", {}),
        "pos": bool(params.get("pos", True)),
    }
    entries.append(entry)
    entries.sort(key=lambda e: e["t"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    return {"ok": True, "entry": entry, "count": len(entries)}


# ── Waveform peaks (vista Analyzer) ─────────────────────────────────────────
def _h_analyzer_waveform_peaks(session, params):
    buckets = int(params.get("buckets", 1100))
    try:
        dur = session.duration or session.analysis.summary.get("duration_s", 0)
        rng = session.analysis.features_range(0.0, dur, downsample_to=buckets, names=["rms"])
        rms = rng.get("features", {}).get("rms", []) or []
        if rms:
            mx = max(rms) or 1.0
            peaks = [round(min(1.0, v / mx), 4) for v in rms]
        else:
            peaks = []
        return {"peaks": peaks, "duration": dur, "bpm": session.bpm}
    except Exception as e:
        return {"peaks": [], "error": str(e)}


# ── Banco de presets (v1.10) ────────────────────────────────────────────────
def _h_list_presets(session, params):
    all_presets = session.presets.list()
    effect_id = params.get("effect_id")
    if effect_id is not None:
        try:
            eid = int(effect_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "effect_id debe ser entero"}
        all_presets = [p for p in all_presets if p.kind == "pixel" and p.base_effect_id == eid]
    return {"presets": [p.to_dict() for p in all_presets]}


def _h_create_preset(session, params):
    p = session.presets.create(
        name=params.get("name", "Preset"),
        params=params.get("params", {}),
        color=params.get("color", "#3a7acc"),
        scope=params.get("scope", "project"),
        kind=params.get("kind", "pixel"),
        base_effect_id=int(params.get("base_effect_id", 0)),
        channel_effect_id=params.get("channel_effect_id"),
    )
    session.notify_changed("presets")
    return {"ok": True, "preset": p.to_dict()}


def _h_update_preset(session, params):
    p = session.presets.update(
        params["preset_id"], name=params.get("name"), params=params.get("params"),
        color=params.get("color"), base_effect_id=params.get("base_effect_id"))
    if p is None:
        return {"ok": False, "error": "preset no encontrado"}
    # Enlace vivo: refrescar el snapshot (effect_id/params/color/label) de los
    # clips ligados, para que el fallback Qt y las etiquetas sigan al preset.
    n = 0
    for c in session.timeline.clips:
        if getattr(c, "preset_id", None) == p.preset_id:
            if p.kind == "channel":
                c.channel_effect_id = p.channel_effect_id
                c.category = p.category
            else:
                c.effect_id = p.base_effect_id
            c.params = dict(p.params)
            c.color = p.color
            c.label = p.name
            n += 1
    session.invalidate_caches()   # invalida cache de render → recompute
    session.notify_changed("presets")
    return {"ok": True, "preset": p.to_dict(), "clips_updated": n}


def _h_delete_preset(session, params):
    ok = session.presets.delete(params["preset_id"])
    session.notify_changed("presets")
    return {"ok": ok}


def _h_add_preset_clip(session, params):
    from core.timeline_model import Clip

    try:
        preset_id = params["preset_id"]
        start = require_int(params, "start_ms")
        end = require_int(params, "end_ms")
        require_order(start, end, "start_ms", "end_ms")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    p = session.presets.get(preset_id)
    if p is None:
        return {"ok": False, "error": "preset no encontrado"}

    if p.kind == "channel":
        fixture_id = params.get("fixture_id")
        if not fixture_id:
            return {"ok": False, "error": "falta fixture_id para un preset de canal"}
        clip = Clip(
            track=-1, start_ms=start, end_ms=end, effect_id=0,
            scope=f"fixture:{fixture_id}", params=dict(p.params),
            label=p.name, color=p.color, layer=int(params.get("layer", 0)),
            category=p.category, channel_effect_id=p.channel_effect_id,
            preset_id=p.preset_id,
        )
    else:
        clip = Clip(
            track=int(params.get("track", 0)), start_ms=start, end_ms=end,
            effect_id=p.base_effect_id, scope=params.get("scope", "per_bar"),
            params=dict(p.params), label=p.name, color=p.color,
            layer=int(params.get("layer", 0)), preset_id=p.preset_id,
        )
    session.timeline.add(clip)
    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


def _h_export_csv(session, params):
    from src.io.exporter import export_clips_csv

    def _exporter(sess, path):
        export_clips_csv(sess.timeline, path)

    return export_to_memory(session, _exporter, ".csv", "{slug}_clips.csv")


def _h_export_qlc(session, params):
    from src.io.exporter import export_qlc_workspace

    def _exporter(sess, path):
        export_qlc_workspace(sess.timeline, sess.fixture_rig, path)

    return export_to_memory(session, _exporter, ".qxw", "{slug}.qxw")


# A2 — Automatización: curvas de parámetro sobre timeline
def _h_add_automation_lane(session, params):
    """Añade una nueva lane de automatización."""
    try:
        target = require_key(params, "target")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    from src.core.automation import AutomationLane
    from uuid import uuid4
    lane = AutomationLane(uid=uuid4().hex[:12], target=target, points=[], enabled=True)
    session.timeline.automation.append(lane.to_dict())
    session.invalidate_caches()
    return {"ok": True, "lane": lane.to_dict()}


def _h_delete_automation_lane(session, params):
    """Borra una lane de automatización por uid."""
    try:
        uid = require_key(params, "uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    automation = [d for d in session.timeline.automation if d.get('uid') != uid]
    if len(automation) == len(session.timeline.automation):
        return {"ok": False, "error": "lane uid no encontrada"}
    session.timeline.automation = automation
    session.invalidate_caches()
    return {"ok": True}


def _h_set_automation_points(session, params):
    """Reemplaza todos los puntos de una lane."""
    try:
        uid = require_key(params, "uid")
        points = require_key(params, "points")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    if not isinstance(points, list):
        return {"ok": False, "error": "points debe ser una lista"}
    # Buscar la lane
    lane_dict = None
    for d in session.timeline.automation:
        if d.get('uid') == uid:
            lane_dict = d
            break
    if lane_dict is None:
        return {"ok": False, "error": "lane uid no encontrada"}
    # Validar y setear puntos (son dicts con t_ms, value, shape)
    from src.core.automation import AutomationPoint
    try:
        validated_points = []
        for pt_dict in points:
            pt = AutomationPoint.from_dict(pt_dict)
            validated_points.append(pt.to_dict())
        # Ordenar por t_ms
        validated_points.sort(key=lambda p: p['t_ms'])
        lane_dict['points'] = validated_points
    except Exception as e:
        return {"ok": False, "error": f"Punto inválido: {e}"}
    session.invalidate_caches()
    return {"ok": True, "lane": lane_dict}


def _h_list_automation_lanes(session, params):
    """Lista todas las lanes de automatización."""
    return {"ok": True, "lanes": list(session.timeline.automation)}


# A1 — Modulación: vinculación parámetro ← señal
def _h_set_clip_param_links(session, params):
    """Establece los param_links de un clip (modulación de audio)."""
    try:
        clip_id = require_key(params, "clip_id")
        links = require_key(params, "links")  # lista de {param, source, gain, offset, curve, min_v, max_v}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    c = session.find_clip_by_id(clip_id)
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    if not isinstance(links, list):
        return {"ok": False, "error": "links debe ser una lista"}
    # Validación básica de links
    from src.core.modulation import ParamLink
    try:
        parsed_links = []
        for link_dict in links:
            link = ParamLink.from_dict(link_dict)
            parsed_links.append(link.to_dict())
        c.param_links = parsed_links
    except Exception as e:
        return {"ok": False, "error": f"Link inválido: {e}"}
    session.invalidate_caches()
    return {"ok": True, "clip": c.to_dict()}


def _h_list_modulation_sources(session, params):
    """Devuelve el catálogo de señales disponibles para modulación."""
    sources = [
        # Escalares
        {"name": "rms", "description": "Energy (RMS) del audio"},
        {"name": "centroid", "description": "Spectral centroid (Hz)"},
        {"name": "flux", "description": "Spectral flux (delta)"},
        {"name": "zcr", "description": "Zero crossing rate"},
        {"name": "rolloff", "description": "Spectral rolloff"},
        {"name": "bandwidth", "description": "Spectral bandwidth"},
        {"name": "flatness", "description": "Spectral flatness"},
        {"name": "dtempo", "description": "Tempo derivado"},
        # Vectores con índice: mfcc (13), chroma (12), tonnetz (6), contrast (7), mel_bands (8)
    ]
    # Añadir elementos vectoriales
    for i in range(13):
        sources.append({"name": f"mfcc.{i}", "description": f"MFCC coeficiente {i}"})
    for i in range(12):
        sources.append({"name": f"chroma.{i}", "description": f"Chroma bin {i}"})
    for i in range(6):
        sources.append({"name": f"tonnetz.{i}", "description": f"Tonnetz componente {i}"})
    for i in range(7):
        sources.append({"name": f"contrast.{i}", "description": f"Spectral contrast {i}"})
    for i in range(8):
        sources.append({"name": f"mel_bands.{i}", "description": f"Mel band {i}"})
    return {"ok": True, "sources": sources}


# A3 — Patterns: bloques reutilizables de clips

def _h_create_pattern_from_clips(session, params):
    """Agrupa clips seleccionados en un Pattern reutilizable.

    Borra los clips originales del timeline y crea una PatternInstance
    en su lugar con los tiempos/tracks relativos. Los handlers de undo
    incluyen patterns en el snapshot (invariante I1) antes de mutar.
    """
    try:
        clip_ids = require_key(params, "clip_ids")
        if not isinstance(clip_ids, list) or not clip_ids:
            return {"ok": False, "error": "clip_ids debe ser lista no vacía"}
        name = str(params.get("name", "Pattern"))
        color = str(params.get("color", "#8855cc"))
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    clips = [session.find_clip_by_id(cid) for cid in clip_ids]
    clips = [c for c in clips if c is not None]
    if not clips:
        return {"ok": False, "error": "Ningún clip_id encontrado"}

    from src.core.timeline_model import Pattern, PatternInstance
    from uuid import uuid4

    session.snapshot()

    start_ref = min(c.start_ms for c in clips)
    track_ref = min(c.track for c in clips)

    # Clips con tiempos/tracks relativos al origen del pattern
    relative_clips = []
    for c in clips:
        import copy
        rc = copy.copy(c)
        rc.start_ms = c.start_ms - start_ref
        rc.end_ms = c.end_ms - start_ref
        rc.track = c.track - track_ref
        relative_clips.append(rc)

    pat = Pattern(uid=uuid4().hex[:12], name=name, color=color, clips=relative_clips)
    session.timeline.patterns.append(pat.to_dict())

    # Borrar clips originales del timeline
    uid_set = {c.uid for c in clips}
    session.timeline.clips = [
        c for c in session.timeline.clips if c.uid not in uid_set
    ]

    inst = PatternInstance(
        uid=uuid4().hex[:12],
        pattern_uid=pat.uid,
        start_ms=start_ref,
        track_offset=track_ref,
    )
    session.timeline.pattern_instances.append(inst.to_dict())
    session.invalidate_pattern_cache()
    return {"ok": True, "pattern": pat.to_dict(), "instance": inst.to_dict()}


def _h_add_pattern_instance(session, params):
    """Añade una nueva instancia de un pattern en el timeline."""
    try:
        pattern_uid = require_key(params, "pattern_uid")
        start_ms = require_int(params, "start_ms", min_val=0)
        track_offset = int(params.get("track_offset", 0))
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    pat_d = next(
        (p for p in session.timeline.patterns if p.get("uid") == pattern_uid), None
    )
    if pat_d is None:
        return {"ok": False, "error": "pattern_uid no encontrado"}

    from src.core.timeline_model import PatternInstance
    from uuid import uuid4

    session.snapshot()

    inst = PatternInstance(
        uid=uuid4().hex[:12],
        pattern_uid=pattern_uid,
        start_ms=start_ms,
        track_offset=track_offset,
    )
    session.timeline.pattern_instances.append(inst.to_dict())
    session.invalidate_pattern_cache()
    return {"ok": True, "instance": inst.to_dict()}


def _h_move_pattern_instance(session, params):
    """Mueve (reposiciona) una PatternInstance. Retorna la instancia actualizada (I3)."""
    try:
        instance_uid = require_key(params, "instance_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    inst_d = next(
        (i for i in session.timeline.pattern_instances if i.get("uid") == instance_uid),
        None,
    )
    if inst_d is None:
        return {"ok": False, "error": "instance_uid no encontrado"}

    session.snapshot()

    if params.get("new_start_ms") is not None:
        inst_d["start_ms"] = max(0, int(params["new_start_ms"]))
    if params.get("new_track_offset") is not None:
        inst_d["track_offset"] = int(params["new_track_offset"])

    session.invalidate_pattern_cache()
    return {"ok": True, "instance": dict(inst_d)}


def _h_delete_pattern_instance(session, params):
    """Elimina una PatternInstance del timeline."""
    try:
        instance_uid = require_key(params, "instance_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    instances = [
        i for i in session.timeline.pattern_instances if i.get("uid") != instance_uid
    ]
    if len(instances) == len(session.timeline.pattern_instances):
        return {"ok": False, "error": "instance_uid no encontrado"}

    session.snapshot()
    session.timeline.pattern_instances = instances
    session.invalidate_pattern_cache()
    return {"ok": True}


def _h_update_pattern(session, params):
    """Actualiza nombre, color y/o clips de un Pattern.

    Pasar 'clips' (lista de clip dicts relativos) edita los clips del pattern,
    lo que propagará a todas sus instancias en el próximo frame (enlace vivo).
    """
    try:
        pattern_uid = require_key(params, "pattern_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    pat_d = next(
        (p for p in session.timeline.patterns if p.get("uid") == pattern_uid), None
    )
    if pat_d is None:
        return {"ok": False, "error": "pattern_uid no encontrado"}

    session.snapshot()

    if params.get("name") is not None:
        pat_d["name"] = str(params["name"])
    if params.get("color") is not None:
        pat_d["color"] = str(params["color"])
    if params.get("clips") is not None:
        from src.core.timeline_model import Pattern
        try:
            p = Pattern.from_dict({**pat_d, "clips": params["clips"]})
            pat_d["clips"] = [c.to_dict() for c in p.clips]
        except Exception as e:
            return {"ok": False, "error": f"clips inválidos: {e}"}

    session.invalidate_pattern_cache()
    return {"ok": True, "pattern": dict(pat_d)}


def _h_delete_pattern(session, params):
    """Elimina un Pattern y todas sus instancias (cascada I2)."""
    try:
        pattern_uid = require_key(params, "pattern_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    if not any(p.get("uid") == pattern_uid for p in session.timeline.patterns):
        return {"ok": False, "error": "pattern_uid no encontrado"}

    session.snapshot()

    session.timeline.patterns = [
        p for p in session.timeline.patterns if p.get("uid") != pattern_uid
    ]
    instances_before = len(session.timeline.pattern_instances)
    session.timeline.pattern_instances = [
        i for i in session.timeline.pattern_instances
        if i.get("pattern_uid") != pattern_uid
    ]
    deleted_instances = instances_before - len(session.timeline.pattern_instances)
    # I2: limpiar live_slots que referencien el pattern borrado
    changed = False
    for slot in session.live_engine.slots:
        if slot.pattern_uid == pattern_uid:
            slot.pattern_uid = None
            session.live_engine._active.pop(slot.uid, None)
            session.live_engine._armed.pop(slot.uid, None)
            changed = True
    if changed:
        session.timeline.live_slots = session.live_engine.slots_to_dicts()
    session.invalidate_pattern_cache()
    return {"ok": True, "deleted_instances": deleted_instances}


def _h_list_patterns(session, params):
    """Lista todos los patterns del banco."""
    return {"ok": True, "patterns": list(session.timeline.patterns)}


def _h_list_pattern_instances(session, params):
    """Lista todas las instancias de patterns en el timeline."""
    return {"ok": True, "instances": list(session.timeline.pattern_instances)}


def _h_dissolve_instance(session, params):
    """Convierte una PatternInstance en clips reales en el timeline.

    Los clips se crean con posiciones absolutas y se pueden editar
    individualmente a partir de ese momento.
    """
    try:
        instance_uid = require_key(params, "instance_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    inst_d = next(
        (i for i in session.timeline.pattern_instances if i.get("uid") == instance_uid),
        None,
    )
    if inst_d is None:
        return {"ok": False, "error": "instance_uid no encontrado"}

    from src.core.timeline_model import Pattern, PatternInstance, Clip
    from uuid import uuid4

    session.snapshot()

    inst = PatternInstance.from_dict(inst_d)
    pat_d = next(
        (p for p in session.timeline.patterns if p.get("uid") == inst.pattern_uid),
        None,
    )
    if pat_d is None:
        return {"ok": False, "error": "pattern del que depende la instancia no encontrado"}

    pat = Pattern.from_dict(pat_d)
    new_clips = []
    for clip in pat.clips:
        nc = Clip(
            track=max(0, min(9, clip.track + inst.track_offset)),
            start_ms=inst.start_ms + clip.start_ms,
            end_ms=inst.start_ms + clip.end_ms,
            effect_id=clip.effect_id,
            scope=clip.scope,
            params=dict(clip.params),
            color=clip.color,
            label=clip.label,
            layer=clip.layer,
            locked=clip.locked,
            muted=clip.muted,
            category=clip.category,
            channel_effect_id=clip.channel_effect_id,
            preset_id=clip.preset_id,
            uid=uuid4().hex[:12],  # uid NUEVO (clip real, editable)
            param_links=list(clip.param_links),
        )
        new_clips.append(nc)

    session.timeline.clips.extend(new_clips)
    session.timeline.pattern_instances = [
        i for i in session.timeline.pattern_instances if i.get("uid") != instance_uid
    ]
    session.invalidate_pattern_cache()
    session.invalidate_clip_index()
    return {"ok": True, "clips": [c.to_dict() for c in new_clips]}


# ── A5 — Ergonomía: duplicar sección ────────────────────────────────────────

def _h_duplicate_range(session, params):
    """Copia todos los clips cuyo start_ms ∈ [t0_ms, t1_ms) al offset dest_ms.

    El desplazamiento aplicado es `dest_ms - t0_ms`. Los clips con start_ms en
    [t0_ms, t1_ms) se duplican con nuevos UIDs; los originales no se tocan.
    Llama snapshot() antes de mutar (invariante I1).
    """
    from src.core.timeline_model import Clip
    t0_ms = require_int(params, "t0_ms")
    t1_ms = require_int(params, "t1_ms")
    dest_ms = require_int(params, "dest_ms")
    if t0_ms >= t1_ms:
        return {"ok": False, "error": "t0_ms debe ser menor que t1_ms"}

    session.snapshot()
    offset = dest_ms - t0_ms
    new_clips = []
    for c in list(session.timeline.clips):
        if t0_ms <= c.start_ms < t1_ms:
            nc = Clip(
                track=c.track,
                start_ms=c.start_ms + offset,
                end_ms=c.end_ms + offset,
                effect_id=c.effect_id,
                scope=c.scope,
                color=c.color,
                layer=c.layer,
                label=c.label,
                muted=c.muted,
                params=dict(c.params or {}),
                category=getattr(c, "category", "pixel"),
                channel_effect_id=getattr(c, "channel_effect_id", None),
                param_links=list(getattr(c, "param_links", []) or []),
            )
            new_clips.append(nc)
    for nc in new_clips:
        session.timeline.add(nc)
    session.invalidate_caches()
    return {"ok": True, "clips": [c.to_dict() for c in new_clips]}


def _h_delete_range(session, params):
    """delete_range(start_ms: int, end_ms: int) → {ok, deleted: int}.

    Borra todos los clips que se solapan con el intervalo [start_ms, end_ms).
    Un clip se solapa si su rango (start_ms, end_ms) intersecta el intervalo
    especificado — condición: clip.start_ms < end_ms AND clip.end_ms > start_ms.
    Llama snapshot() antes de mutar (invariante I1). Usado por la vista Arranger (I4).
    """
    start_ms = require_int(params, "start_ms")
    end_ms = require_int(params, "end_ms")
    if start_ms >= end_ms:
        return {"ok": False, "error": "start_ms debe ser menor que end_ms"}
    session.snapshot()
    before = len(session.timeline.clips)
    session.timeline.clips = [
        c for c in session.timeline.clips
        if not (c.start_ms < end_ms and c.end_ms > start_ms)
    ]
    deleted = before - len(session.timeline.clips)
    session.invalidate_caches()
    return {"ok": True, "deleted": deleted}


# ── A4 — Micro-eventos ──────────────────────────────────────────────────────

def _h_add_micro_event(session, params):
    """Añade un micro-evento al clip. Devuelve el clip actualizado (I3)."""
    from src.core.micro_events import MicroEvent
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    t_ms_rel = int(params.get("t_ms_rel", 0))
    duration_ms = int(params.get("duration_ms", 100))
    if duration_ms < 1:
        return {"ok": False, "error": "duration_ms debe ser >= 1"}
    ev = MicroEvent(
        t_ms_rel=max(0, t_ms_rel),
        duration_ms=duration_ms,
        params_override=dict(params.get("params_override") or {}),
    )
    session.snapshot()
    clip.events = list(clip.events) + [ev.to_dict()]
    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


def _h_delete_micro_event(session, params):
    """Elimina un micro-evento del clip por event_uid."""
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    event_uid = require_key(params, "event_uid")
    before = len(clip.events)
    session.snapshot()
    clip.events = [e for e in clip.events if e.get("uid") != event_uid]
    if len(clip.events) == before:
        return {"ok": False, "error": "event_uid no encontrado"}
    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


def _h_update_micro_event(session, params):
    """Actualiza campos de un micro-evento (t_ms_rel, duration_ms, params_override)."""
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    event_uid = require_key(params, "event_uid")
    ev_list = list(clip.events)
    idx = next((i for i, e in enumerate(ev_list) if e.get("uid") == event_uid), None)
    if idx is None:
        return {"ok": False, "error": "event_uid no encontrado"}
    ev = dict(ev_list[idx])
    if "t_ms_rel" in params:
        ev["t_ms_rel"] = max(0, int(params["t_ms_rel"]))
    if "duration_ms" in params:
        dur = int(params["duration_ms"])
        if dur < 1:
            return {"ok": False, "error": "duration_ms debe ser >= 1"}
        ev["duration_ms"] = dur
    if "params_override" in params:
        ev["params_override"] = dict(params["params_override"])
    session.snapshot()
    ev_list[idx] = ev
    clip.events = ev_list
    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


# ── B2 — Mixer: cadena por pista + master ────────────────────────────────────
# Throttle en el cliente: los sliders no deben disparar más de ~20 req/s
# (cada llamada < 50 ms). Implementar en la UI con un ref de timestamp:
#   if (Date.now() - lastSent) < 50 ms → no enviar; actualizar solo en mouseUp.

_MIXER_CHAIN_KEYS = {'brightness', 'gamma', 'hue_shift', 'white_limit'}
_MASTER_KEYS = _MIXER_CHAIN_KEYS | {'blackout_fade'}


def _h_set_track_chain(session, params):
    """set_track_chain(track, chain) — actualiza la cadena postfx de una pista.

    chain = {brightness?:0..1, gamma?:0.5..2.2, hue_shift?:-180..180,
             white_limit?:0..1}
    Devuelve {ok, track, chain} (invariante I3).
    Throttle en el cliente: máx ~20 req/s (< 50 ms entre llamadas).
    """
    try:
        track = require_int(params, "track", min_val=0)
        if track > 9:
            return {"ok": False, "error": "'track' debe ser 0..9"}
        chain_in = params.get("chain", {})
        if not isinstance(chain_in, dict):
            return {"ok": False, "error": "chain debe ser un dict"}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    mixer = session.timeline.mixer
    if "tracks" not in mixer:
        mixer["tracks"] = {}

    current = dict(mixer["tracks"].get(str(track), {}))
    current.update({k: float(v) for k, v in chain_in.items()
                    if k in _MIXER_CHAIN_KEYS})
    mixer["tracks"][str(track)] = current

    session.notify_changed("mixer")
    return {"ok": True, "track": track, "chain": current}


def _h_set_master(session, params):
    """set_master(master) — actualiza el strip master del mixer.

    master = {brightness?:0..1, gamma?:0.5..2.2, hue_shift?:-180..180,
               white_limit?:0..1, blackout_fade?:0..1}
    Devuelve {ok, master} (invariante I3).
    Throttle en el cliente: máx ~20 req/s (< 50 ms entre llamadas).
    El blackout_fade es animable con una lane de A2 (target 'master:blackout_fade').
    """
    master_in = params.get("master", params)
    if not isinstance(master_in, dict):
        return {"ok": False, "error": "master debe ser un dict"}

    mixer = session.timeline.mixer
    current = dict(mixer.get("master", {}))
    current.update({k: float(v) for k, v in master_in.items()
                    if k in _MASTER_KEYS})
    mixer["master"] = current

    session.notify_changed("mixer")
    return {"ok": True, "master": current}


def _h_get_mixer(session, params):
    """get_mixer() — devuelve el estado completo del mixer."""
    mixer = session.timeline.mixer
    return {
        "ok": True,
        "mixer": {
            "tracks": dict(mixer.get("tracks", {})),
            "master": dict(mixer.get("master", {})),
        },
    }


# ── B1 — Waveform en el timeline ─────────────────────────────────────────────

_WAVEFORM_N_BUCKETS = 8000


def _h_get_waveform(session, params):
    """Devuelve la forma de onda del audio en _WAVEFORM_N_BUCKETS cubos.

    Cachea el resultado en <analysis_dir>/waveform.json (escritura atómica).
    La primera llamada tarda ~2-5 s (librosa); las siguientes son inmediatas.
    """
    import json as _json
    from pathlib import Path as _Path

    analysis_dir = session.analysis.analysis_dir
    cache_path = analysis_dir / "waveform.json"

    if cache_path.is_file():
        with open(cache_path, "r", encoding="utf-8") as _f:
            _data = _json.load(_f)
        return {"ok": True, **_data}

    try:
        import librosa as _librosa
        import numpy as _np
    except ImportError:
        return {"ok": False, "error": "librosa no disponible"}

    audio_path = _Path(session.project.audio_path)
    if not audio_path.is_file():
        return {"ok": False, "error": f"Audio no encontrado: {audio_path}"}

    y, sr = _librosa.load(str(audio_path), sr=None, mono=True)
    total = len(y)
    n = _WAVEFORM_N_BUCKETS
    chunk = max(1, total // n)

    peaks_max, peaks_min, rms_vals = [], [], []
    for i in range(n):
        s = i * chunk
        e = s + chunk if i < n - 1 else total
        block = y[s:e]
        if len(block) == 0:
            peaks_max.append(0.0)
            peaks_min.append(0.0)
            rms_vals.append(0.0)
        else:
            peaks_max.append(round(float(_np.max(block)), 5))
            peaks_min.append(round(float(_np.min(block)), 5))
            rms_vals.append(round(float(_np.sqrt(_np.mean(block ** 2))), 5))

    data = {
        "peaks_max": peaks_max,
        "peaks_min": peaks_min,
        "rms": rms_vals,
        "n_buckets": n,
        "duration_sec": round(float(total / sr), 3),
        "bpm": float(getattr(session, "bpm", 120)),
    }

    analysis_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as _f:
        _json.dump(data, _f, separators=(",", ":"))
    tmp.replace(cache_path)

    return {"ok": True, **data}


# ── B3 — Render offline + playback baked ────────────────────────────────────

def _h_render_offline(session, params):
    """render_offline() — lanza el render del timeline completo en background.

    Corre en loop.run_in_executor (thread pool) — no bloquea el tick (I4).
    El progreso se emite como {type:'render_progress', pct:float} en el stream.
    Devuelve {ok, message} inmediatamente (el render continúa en background).
    """
    if getattr(session, 'render_in_progress', False):
        return {"ok": False, "error": "Ya hay un render en curso"}
    import asyncio
    from server.offline_render import start_render
    try:
        asyncio.ensure_future(start_render(session))
    except RuntimeError as e:
        return {"ok": False, "error": f"No se pudo lanzar render: {e}"}
    return {"ok": True, "message": "Render iniciado en background"}


# ── B4 — Autosave + versiones de show ────────────────────────────────────────

def _h_list_autosaves(session, params):
    """list_autosaves() → {ok, autosaves: [{filename, ts, size_kb}]} desc por fecha."""
    import os
    d = session.project.folder / "autosave"
    if not d.is_dir():
        return {"ok": True, "autosaves": []}
    files = sorted(d.glob("show_*.json"), key=lambda p: p.name, reverse=True)
    result = []
    for f in files:
        try:
            size_kb = round(os.path.getsize(f) / 1024, 1)
        except OSError:
            size_kb = 0
        ts = f.stem[5:]  # "show_YYYYMMDDTHHMMSS" → "YYYYMMDDTHHMMSS"
        result.append({"filename": f.name, "ts": ts, "size_kb": size_kb})
    return {"ok": True, "autosaves": result}


def _h_restore_autosave(session, params):
    """restore_autosave(filename) → {ok}.

    Carga el autosave como timeline activo. Valida que el filename esté
    DENTRO de projects/<slug>/autosave/ para evitar path traversal.
    """
    try:
        filename = require_key(params, "filename")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    # Defensa path traversal: solo nombres de archivo simples con patrón seguro
    from pathlib import Path as _Path
    safe_name = _Path(filename).name  # elimina cualquier separador de directorio
    if safe_name != filename or "/" in filename or "\\" in filename:
        return {"ok": False, "error": "filename inválido (path traversal bloqueado)"}
    if not safe_name.startswith("show_") or not safe_name.endswith(".json"):
        return {"ok": False, "error": "filename debe ser show_<ts>.json"}

    autosave_path = session.project.folder / "autosave" / safe_name
    if not autosave_path.is_file():
        return {"ok": False, "error": "autosave no encontrado"}

    try:
        from src.core.timeline_model import Timeline
        new_tl = Timeline.load(autosave_path)
        # Preservar duration_ms del show activo (viene del audio, no del autosave)
        new_tl.duration_ms = session.timeline.duration_ms
        session.snapshot()
        session.timeline = new_tl
        session.invalidate_caches()
    except Exception as e:
        return {"ok": False, "error": f"Error al cargar autosave: {e}"}
    return {"ok": True, "filename": safe_name}


def _h_discard_autosave_prompt(session, params):
    """discard_autosave_prompt() → {ok}. Solo cierra el banner en el frontend."""
    return {"ok": True}


def _h_toggle_baked(session, params):
    """toggle_baked(enabled: bool) → {ok, baked: bool}.

    Si enabled=True: intenta cargar los frames bakeados del npz en memoria.
    Si no hay render válido (hash no coincide o no existe), devuelve error.
    Si enabled=False: descarga los frames de memoria (vuelve al modo live).
    """
    enabled = bool(params.get("enabled", True))

    if not enabled:
        session.baked_frames = None
        session.baked_hash = None
        return {"ok": True, "baked": False}

    ok = session.load_baked_frames()
    if not ok:
        return {
            "ok": False,
            "error": "Sin render válido. Lanza render_offline primero.",
            "baked": False,
        }
    return {"ok": True, "baked": True}


# ── C1 — Performance grid: lanzar patterns en vivo ──────────────────────────

def _live_emit(session, state: dict) -> None:
    """Emite {type:'live_state_changed'} al stream hub si está disponible."""
    import asyncio
    hub = getattr(session, "hub", None)
    if hub:
        try:
            asyncio.ensure_future(
                hub.broadcast_json({"type": "live_state_changed", **state})
            )
        except Exception:
            pass


def _h_live_assign_slot(session, params):
    """live_assign_slot(slot_idx, pattern_uid?, key?, quantize?, mode?) → {ok, slot}.

    Asigna o actualiza la configuración de un slot del performance grid.
    Limpia el slot en live_slots del timeline y toma snapshot para undo (I1).
    """
    try:
        slot_idx = require_int(params, "slot_idx", min_val=0)
        if slot_idx > 15:
            return {"ok": False, "error": "slot_idx debe ser 0..15"}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    pattern_uid = params.get("pattern_uid")
    key = params.get("key")
    quantize = params.get("quantize")
    mode = params.get("mode")

    # Validar que el pattern existe (si se pasa uno)
    if pattern_uid:
        if not any(p.get("uid") == pattern_uid for p in session.timeline.patterns):
            return {"ok": False, "error": "pattern_uid no encontrado"}

    session.snapshot()
    try:
        slot = session.live_engine.assign_slot(
            slot_idx,
            pattern_uid=pattern_uid,
            key=key,
            quantize=quantize,
            mode=mode,
        )
    except IndexError as e:
        return {"ok": False, "error": str(e)}

    session.timeline.live_slots = session.live_engine.slots_to_dicts()
    state = session.live_engine.get_state(session.analysis)
    _live_emit(session, state)
    return {"ok": True, "slot": slot.to_dict()}


def _h_live_trigger(session, params):
    """live_trigger(slot_idx) → {ok, slot, armed_at_ms}.

    Dispara un slot: lo arma hasta el próximo límite de cuantización.
    Si quantize='bar' pero no hay downbeats → degrada a 'free' (armed_at_ms = t_actual).
    """
    try:
        slot_idx = require_int(params, "slot_idx", min_val=0)
        if slot_idx > 15:
            return {"ok": False, "error": "slot_idx debe ser 0..15"}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    t_ms = float(params.get("t_ms", session.time * 1000))
    slot, t_armed = session.live_engine.trigger(slot_idx, t_ms, session.analysis)
    state = session.live_engine.get_state(session.analysis)
    _live_emit(session, state)
    return {"ok": True, "slot": slot.to_dict(), "armed_at_ms": t_armed}


def _h_live_release(session, params):
    """live_release(slot_idx) → {ok}.

    Detiene un slot. Solo relevante para mode='hold'; libera también los demás modos.
    """
    try:
        slot_idx = require_int(params, "slot_idx", min_val=0)
        if slot_idx > 15:
            return {"ok": False, "error": "slot_idx debe ser 0..15"}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    slot = session.live_engine.release(slot_idx)
    state = session.live_engine.get_state(session.analysis)
    _live_emit(session, state)
    return {"ok": True, "slot": slot.to_dict()}


def _h_live_stop_all(session, params):
    """live_stop_all() → {ok}.

    Botón de pánico: detiene todos los slots activos y armados.
    """
    session.live_engine.stop_all()
    state = session.live_engine.get_state(session.analysis)
    _live_emit(session, state)
    return {"ok": True}


def _h_get_live_state(session, params):
    """get_live_state() → {ok, slots, active, armed}.

    Estado completo de los 16 slots con flags active/armed/degraded.
    """
    state = session.live_engine.get_state(session.analysis)
    return {"ok": True, **state}


# C2 — Macros en vivo
_MACRO_RANGES: dict = {
    "brightness_mul": (0.0, 2.0),
    "speed_mul":      (0.0, 4.0),
    "hue_shift":      (-180.0, 180.0),
    "strobe_rate":    (0.0, 30.0),
}


def _h_set_macro(session, params):
    """set_macro(name, value) → {ok, macros}.

    Modifica una macro en vivo (estado de sesión, no del show.json).
    Throttle recomendado en el cliente: ≤ 20 llamadas/s.
    """
    name = params.get("name")
    if name not in _MACRO_RANGES:
        return {"ok": False, "error": f"Macro desconocida: {name!r}. "
                f"Válidas: {list(_MACRO_RANGES)}"}
    lo, hi = _MACRO_RANGES[name]
    try:
        value = float(params["value"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "value requerido (float)"}
    if not (lo <= value <= hi):
        return {"ok": False, "error": f"{name} debe estar en [{lo}, {hi}], recibido {value}"}
    session.macros[name] = value
    return {"ok": True, "macros": dict(session.macros)}


# ── I1 — Grabación en vivo de macros ────────────────────────────────────────

def _h_start_record(session, params):
    """start_record() → {ok, recording: True}.

    Activa la grabación de macros. Limpia puntos anteriores y registra el
    tiempo de inicio. Mientras graba, compute_frame captura cada cambio de
    macro con throttle 50ms.
    """
    session._recorded_lanes = {}
    session._record_last_ms = {}
    session._record_start_ms = float(session._current_t_ms)
    session._recording = True
    return {"ok": True, "recording": True}


def _h_stop_record(session, params):
    """stop_record() → {ok, recording: False, lanes_created: int, lane_uids: [str]}.

    Detiene la grabación y convierte los puntos capturados en AutomationLanes
    en session.timeline.automation. Es idempotente: llamar sin grabación activa
    devuelve lanes_created=0. Las lanes son undoables (I1).
    """
    if not session._recording and not session._recorded_lanes:
        return {"ok": True, "recording": False, "lanes_created": 0, "lane_uids": []}

    session._recording = False

    from src.core.automation import AutomationLane, AutomationPoint
    from uuid import uuid4

    start_ms = session._record_start_ms
    lane_uids = []

    # Snapshot ANTES de mutar → undo revierte las lanes creadas (I1)
    session.snapshot()

    for macro_name, points in session._recorded_lanes.items():
        if not points:
            continue
        target = f"master:{macro_name}"
        auto_points = [
            {"t_ms": int(pt["t_ms"] - start_ms), "value": float(pt["value"]), "shape": "linear"}
            for pt in points
        ]
        uid = uuid4().hex[:12]
        lane = AutomationLane(uid=uid, target=target, points=auto_points, enabled=True)
        session.timeline.automation.append(lane.to_dict())
        lane_uids.append(uid)

    session._recorded_lanes = {}
    session._record_last_ms = {}
    session.invalidate_caches()
    return {
        "ok": True,
        "recording": False,
        "lanes_created": len(lane_uids),
        "lane_uids": lane_uids,
    }


def _h_get_record_state(session, params):
    """get_record_state() → {ok, recording, elapsed_ms, points_captured}."""
    recording = getattr(session, '_recording', False)
    elapsed = (float(session._current_t_ms) - session._record_start_ms) if recording else 0.0
    points = sum(len(v) for v in getattr(session, '_recorded_lanes', {}).values())
    return {
        "ok": True,
        "recording": recording,
        "elapsed_ms": elapsed,
        "points_captured": points,
    }


# ── I2 — Marcadores de timeline con nombre, color y categoría ────────────────

_VALID_MARKER_CATS = frozenset({"intro", "verso", "estribillo", "bridge", "outro", "custom"})


def _h_list_markers(session, params):
    """list_markers(category=None) → {ok, markers: [...]}.

    Devuelve los marcadores ordenados por t_ms. Si se pasa `category`, filtra
    por esa categoría.
    """
    from src.core.timeline_model import Marker  # noqa: F401 — para type hint
    cat = params.get("category")
    mkrs = session.timeline.markers
    if cat:
        mkrs = [m for m in mkrs if m.category == cat]
    return {"ok": True, "markers": [m.to_dict() for m in mkrs]}


def _h_add_marker(session, params):
    """add_marker(time_ms, name='', color='#888888', category='custom') → {ok, marker}.

    Añade un marcador en t_ms (reemplaza si ya existe uno exactamente en ese punto).
    Devuelve el marcador creado (I3).
    """
    from src.core.timeline_model import Marker
    t_ms = int(params.get("time_ms", params.get("t_ms", 0)))
    name = str(params.get("name", ""))
    color = str(params.get("color", "#888888"))
    cat = str(params.get("category", "custom"))
    if cat not in _VALID_MARKER_CATS:
        cat = "custom"
    session.timeline.markers = [m for m in session.timeline.markers if m.t_ms != t_ms]
    marker = Marker(t_ms=t_ms, name=name, color=color, category=cat)
    session.timeline.markers.append(marker)
    session.timeline.markers.sort(key=lambda m: m.t_ms)
    return {"ok": True, "marker": marker.to_dict()}


def _h_delete_marker(session, params):
    """delete_marker(time_ms) → {ok, deleted: int}."""
    t_ms = int(params.get("time_ms", params.get("t_ms", 0)))
    before = len(session.timeline.markers)
    session.timeline.markers = [m for m in session.timeline.markers if m.t_ms != t_ms]
    return {"ok": True, "deleted": before - len(session.timeline.markers)}


def _h_update_marker(session, params):
    """update_marker(t_ms, name?, color?, category?) → {ok, marker}.

    Actualiza los campos del marcador en la posición t_ms. Devuelve el marcador
    actualizado (invariante I3). Undo revierte la mutación (invariante I1).
    """
    t_ms = int(params.get("t_ms", params.get("time_ms", 0)))
    marker = next((m for m in session.timeline.markers if m.t_ms == t_ms), None)
    if marker is None:
        return {"ok": False, "error": f"Marcador en {t_ms}ms no encontrado"}
    if "name" in params:
        marker.name = str(params["name"])
    if "color" in params:
        marker.color = str(params["color"])
    if "category" in params:
        cat = str(params["category"])
        marker.category = cat if cat in _VALID_MARKER_CATS else "custom"
    return {"ok": True, "marker": marker.to_dict()}


# ── I3 — Grupos colapsables: clips de un grupo ───────────────────────────────

def _h_get_group_clips(session, params):
    """get_group_clips(group_name) → {ok, clips: [...]}.

    Devuelve los clips de tipo pixel (scope=per_bar) cuya pista (track) está
    incluida en el grupo indicado. Lee los grupos del timeline para obtener
    la lista de barras del grupo. Read-only.
    """
    name = str(params.get("group_name", ""))
    tl = session.timeline
    grp = next((g for g in tl.groups if g.name == name), None)
    if grp is None:
        return {"ok": False, "error": f"Grupo '{name}' no encontrado"}
    bar_set = set(grp.bars)
    pixel_clips = [
        c.to_dict()
        for c in tl.clips
        if getattr(c, "track", None) in bar_set
        and (getattr(c, "category", "pixel") or "pixel") == "pixel"
    ]
    return {"ok": True, "clips": pixel_clips}


# ── D1 — Auto-VJ por reglas ─────────────────────────────────────────────────

def _h_autovj_get_state(session, params):
    """autovj_get_state() → {ok, ruleset|null, presets: [{uid, name, rules}]}.

    Estado completo del motor AutoVJ: ruleset activo + presets disponibles.
    """
    from src.core.autovj import PRESETS
    ruleset = session.autovj_engine.ruleset
    return {
        "ok": True,
        "ruleset": ruleset.to_dict() if ruleset is not None else None,
        "presets": [
            {"uid": p.uid, "name": p.name, "rules": len(p.rules)}
            for p in PRESETS.values()
        ],
    }


def _h_autovj_set_ruleset(session, params):
    """autovj_set_ruleset(ruleset|null) → {ok, ruleset|null}.

    Reemplaza el ruleset activo. Pasar null desactiva el AutoVJ.
    """
    from src.core.autovj import RuleSet
    ruleset_dict = params.get("ruleset")
    if ruleset_dict is None:
        session.autovj_engine.ruleset = None
        return {"ok": True, "ruleset": None}
    try:
        rs = RuleSet.from_dict(ruleset_dict)
        session.autovj_engine.ruleset = rs
        return {"ok": True, "ruleset": rs.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _h_autovj_activate_preset(session, params):
    """autovj_activate_preset(preset_uid) → {ok, ruleset}.

    Carga un preset integrado como ruleset activo (copia fresca, estado
    runtime reseteado).
    """
    from src.core.autovj import PRESETS, RuleSet
    preset_uid = params.get("preset_uid", "")
    preset = PRESETS.get(preset_uid)
    if preset is None:
        return {"ok": False, "error": f"Preset no encontrado: {preset_uid!r}. "
                f"Válidos: {list(PRESETS)}"}
    # from_dict crea objetos Rule nuevos con _last_fired_ms=-inf y _above=False
    rs = RuleSet.from_dict(preset.to_dict())
    session.autovj_engine.ruleset = rs
    return {"ok": True, "ruleset": rs.to_dict()}


def _h_autovj_update_rule(session, params):
    """autovj_update_rule(rule_uid, enabled?, cooldown_ms?, trigger?, action?) → {ok, rule}.

    Actualiza campos de una regla en el ruleset activo. Devuelve la regla (I3).
    """
    try:
        rule_uid = require_key(params, "rule_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    rs = session.autovj_engine.ruleset
    if rs is None:
        return {"ok": False, "error": "No hay ruleset activo"}
    rule = next((r for r in rs.rules if r.uid == rule_uid), None)
    if rule is None:
        return {"ok": False, "error": "rule_uid no encontrado"}

    if "enabled" in params:
        rule.enabled = bool(params["enabled"])
    if "cooldown_ms" in params:
        rule.cooldown_ms = max(0, int(params["cooldown_ms"]))
    if "trigger" in params:
        rule.trigger = str(params["trigger"])
    if "action" in params:
        rule.action = str(params["action"])

    return {"ok": True, "rule": rule.to_dict()}


def _h_autovj_save(session, params):
    """autovj_save() → {ok, path}.

    Guarda el ruleset activo en projects/<slug>/autovj.json (guardado atómico).
    No-op si no hay ruleset activo.
    """
    path = session.project.folder / "autovj.json"
    session.autovj_engine.save(path)
    ruleset = session.autovj_engine.ruleset
    return {
        "ok": True,
        "path": str(path),
        "saved": ruleset is not None,
    }


def _h_autovj_load(session, params):
    """autovj_load() → {ok, ruleset|null}.

    Carga el ruleset desde projects/<slug>/autovj.json.
    No-op si el archivo no existe.
    """
    path = session.project.folder / "autovj.json"
    session.autovj_engine.load(path)
    ruleset = session.autovj_engine.ruleset
    return {
        "ok": True,
        "ruleset": ruleset.to_dict() if ruleset is not None else None,
    }


# ── D2 — Análisis en vivo (entrada de audio) ─────────────────────────────────

def _h_live_input_list_devices(session, params):
    """live_input_list_devices() → {ok, devices: [{index, name, channels, default_sr}]}"""
    from server.live_input import LiveInput
    return {"ok": True, "devices": LiveInput.list_devices()}


def _h_live_input_start(session, params):
    """live_input_start(device_index?) → {ok, device_index, bpm}

    Arranca la captura de audio desde el dispositivo de entrada seleccionado
    (por defecto el dispositivo del SO) y activa el modo live: _get_audio_context
    usará las features del ring buffer en vez del análisis offline.
    """
    device = params.get("device_index", None)
    if device is not None:
        device = require_int(params, "device_index")
    if session.live_input is None:
        from server.live_input import LiveInput
        session.live_input = LiveInput()
    try:
        session.live_input.start(device=device)
    except Exception as e:
        return {"ok": False, "error": f"No se pudo abrir el dispositivo: {e}"}
    session._live_mode = True
    return {
        "ok": True,
        "device_index": device,
        "bpm": session.live_input.summary.get("bpm"),
    }


def _h_live_input_stop(session, params):
    """live_input_stop() → {ok}

    Detiene la captura y desactiva el modo live.
    El sistema vuelve a usar el análisis offline para actx y AutoVJ.
    """
    if session.live_input is not None:
        session.live_input.stop()
    session._live_mode = False
    return {"ok": True}


def _h_live_input_get_state(session, params):
    """live_input_get_state() → {ok, active, live_mode, bpm?, duration_s}"""
    li = session.live_input
    active = li is not None and li.is_active
    summary = li.summary if li is not None else {}
    return {
        "ok": True,
        "active": active,
        "live_mode": bool(getattr(session, '_live_mode', False)),
        "bpm": summary.get("bpm"),
        "duration_s": summary.get("duration_s", 0.0),
    }


# ── E2 — OSC bridge (ROADMAP v3) ─────────────────────────────────────────────

def _h_osc_get_state(session, params):
    """osc_get_state() → estado completo del bridge OSC."""
    osc = getattr(session, "osc_bridge", None)
    if osc is None:
        return {"ok": True, "enabled": False, "available": False,
                "port_in": 8001, "port_out": 8002,
                "clients_out": [], "recv_log": [], "active": False}
    return {"ok": True, **osc.get_state()}


def _h_osc_set_config(session, params):
    """osc_set_config(port_in?, port_out?, enabled?, clients_out?) → {ok}.

    clients_out: lista de {ip, port}.
    Persiste en output_targets.json. Reinicia el servidor IN si cambia el puerto o enabled.
    """
    osc = getattr(session, "osc_bridge", None)
    if osc is None:
        return {"ok": False, "error": "OSC bridge no disponible"}

    changed_server = False
    if "port_in" in params and params["port_in"] != osc.port_in:
        osc.port_in = int(params["port_in"])
        changed_server = True
    if "port_out" in params:
        osc.port_out = int(params["port_out"])
    if "enabled" in params and bool(params["enabled"]) != osc.enabled:
        osc.enabled = bool(params["enabled"])
        changed_server = True
    if "clients_out" in params:
        raw = params["clients_out"]
        osc.set_clients_out([(c["ip"], int(c["port"])) for c in raw if "ip" in c and "port" in c])

    # Guardar config (atómico vía output_targets.json)
    from pathlib import Path
    _ot = Path(__file__).resolve().parent.parent / "output_targets.json"
    osc.save_config(_ot)

    # Reiniciar servidor IN si cambiaron port_in o enabled
    if changed_server:
        import asyncio
        asyncio.create_task(osc.restart())

    return {"ok": True, **osc.get_state()}


# ── G3 — Moving heads: pan/tilt en el timeline ──────────────────────────────

def _h_list_channel_effects(session, params):
    """list_channel_effects() → {ok, effects: [{effect_id, name, category, required_channels, ...}]}"""
    lib = getattr(session, 'channel_lib', None)
    if lib is None:
        return {"ok": True, "effects": []}
    return {"ok": True, "effects": lib.describe_all()}


def _h_set_clip_channel_effect(session, params):
    """set_clip_channel_effect(clip_id, config: {id, params?}) — añade/actualiza un efecto de canal.

    El campo `config.id` es el effect_id del ChannelEffect (ej. "pos_pantilt_wave").
    Si ya existe un entry con el mismo id en clip.channel_effects, lo reemplaza.
    También actualiza legacy channel_effect_id + params del clip para compat con
    fixtures que usan el campo individual.
    """
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}

    cfg = params.get("config")
    if not cfg or not isinstance(cfg, dict):
        return {"ok": False, "error": "config requerido: {id, params?}"}

    eff_id = cfg.get("id") or cfg.get("effect_id")
    if not eff_id:
        return {"ok": False, "error": "config.id requerido"}

    # Verificar que el efecto existe
    lib = getattr(session, 'channel_lib', None)
    if lib is not None and lib.get(str(eff_id)) is None:
        return {"ok": False, "error": f"channel_effect '{eff_id}' no encontrado"}

    eff_params = dict(cfg.get("params") or {})
    entry = {"id": str(eff_id), "params": eff_params}

    # Upsert en la lista channel_effects del clip
    existing = list(getattr(clip, 'channel_effects', []) or [])
    replaced = False
    for i, e in enumerate(existing):
        if e.get("id") == str(eff_id):
            existing[i] = entry
            replaced = True
            break
    if not replaced:
        existing.append(entry)
    clip.channel_effects = existing

    # También actualizar el campo legacy para compat con show_engine legacy path
    clip.channel_effect_id = str(eff_id)
    clip.params = {**clip.params, **eff_params}

    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


def _h_delete_clip_channel_effect(session, params):
    """delete_clip_channel_effect(clip_id, channel_name_or_id) — elimina un efecto de canal.

    Elimina la entrada cuyo id == channel_name_or_id, O que controla el canal channel_name_or_id.
    """
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}

    target = require_key(params, "channel_name_or_id")
    existing = list(getattr(clip, 'channel_effects', []) or [])

    before = len(existing)
    # Eliminar por id directo
    existing = [e for e in existing if e.get("id") != target]
    if len(existing) == before:
        # Buscar si algún efecto produce el canal pedido
        lib = getattr(session, 'channel_lib', None)
        if lib is not None:
            existing = [e for e in existing
                        if target not in (lib.get(e.get("id", "")) or type('', (), {'required_channels': [], 'optional_channels': []})()).required_channels]

    clip.channel_effects = existing
    if not existing:
        clip.channel_effect_id = None

    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


def _h_list_dmx_ports(session, params):
    """list_dmx_ports() → {ok, ports: [str]} — lista puertos serie para DMX USB."""
    from src.io.outputs.router import DmxUsbTarget
    return {"ok": True, "ports": DmxUsbTarget.list_ports()}


def _h_set_output_target(session, params):
    """set_output_target(universe, type, port?, ip?, multicast?) → {ok}.

    Actualiza output_targets.json para el universo indicado y recarga el router
    en el engine de la sesión. Soporta type: wled, artnet_node, sacn, dmx_usb, sim_only.
    """
    from pathlib import Path
    import json

    uni = int(params.get("universe", 1))
    ttype = str(params.get("type", "sim_only"))

    cfg: dict = {"type": ttype}
    if ttype in ("wled", "artnet_node", "sacn"):
        ip = params.get("ip") or params.get("port") or ""
        if ip:
            cfg["ip"] = ip
        if ttype == "sacn":
            if params.get("multicast"):
                cfg["multicast"] = True
    elif ttype == "dmx_usb":
        port = params.get("port") or "COM3"
        cfg["port"] = port

    _ot = Path(__file__).resolve().parent.parent / "output_targets.json"
    try:
        data: dict = {}
        if _ot.is_file():
            data = json.loads(_ot.read_text(encoding="utf-8"))
        data[str(uni)] = cfg
        tmp = _ot.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_ot)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Recargar router en el engine
    se = getattr(session, "show_engine", None)
    if se is not None:
        try:
            from src.io.outputs.router import OutputRouter
            new_router = OutputRouter.load(_ot)
            if hasattr(se, "router") and se.router is not None:
                se.router.close()
            se.router = new_router
        except Exception as e:
            return {"ok": True, "warn": f"config guardada pero router no recargado: {e}"}

    return {"ok": True, "universe": uni, "target": cfg}


# ── H3 — Multi-show quick-switch ────────────────────────────────────────────

def _h_list_projects(session, params):
    """list_projects() → {ok, projects: [{slug, name, audio_path, ...}], current: slug}"""
    pm = getattr(session, "pm", None) or getattr(session, "_pm", None)
    if pm is None:
        return {"ok": True, "projects": [], "current": None}
    projects = pm.list_projects()
    current_slug = session.project.slug if hasattr(session, "project") and session.project else None
    return {
        "ok": True,
        "projects": [
            {
                "slug": p.slug,
                "name": p.name,
                "audio_path": str(p.audio_path),
            }
            for p in projects
        ],
        "current": current_slug,
    }


def _h_switch_project(session, params):
    """switch_project(slug) → {ok} — cambia el proyecto activo sin reiniciar el server.

    Emite event project_changed al stream. La operación es async; el cliente debe
    esperar el evento 'project_changed' antes de refetchear el timeline.
    """
    import asyncio
    slug = str(params.get("slug", ""))
    if not slug:
        return {"ok": False, "error": "slug requerido"}
    pm = getattr(session, "pm", None) or getattr(session, "_pm", None)
    if pm is not None and pm.open_project(slug) is None:
        return {"ok": False, "error": f"Proyecto no encontrado: {slug!r}"}
    asyncio.create_task(session.switch_project(slug))
    return {"ok": True, "slug": slug}


def _h_get_fixture_pan_tilt(session, params):
    """get_fixture_pan_tilt(fixture_id?) → {ok, fixtures: [{fixture_id, pan, tilt}]}

    Devuelve pan/tilt de todos los movers (o del fixture_id indicado) en el instante actual.
    Valores 0..1 (normalizado). Útil para el preview 2D en la UI.
    """
    import time as _time
    t = session.t if hasattr(session, 't') else 0.0
    actx = session._cached_actx if hasattr(session, '_cached_actx') else {}

    se = getattr(session, 'show_engine', None)
    tl = getattr(session, 'timeline', None)
    if se is None or tl is None or se.rig is None:
        return {"ok": True, "fixtures": []}

    fid_filter = params.get("fixture_id")
    result = []
    for fx in se.rig.all_fixtures():
        if fid_filter is not None and str(fx.fixture_id) != str(fid_filter):
            continue
        profile = se.rig.get_profile(fx.profile_id)
        if profile is None or 'pan' not in profile.channel_map:
            continue
        buf = se.render_channels_for_fixture(fx, t, actx, timeline=tl)
        ch_pan  = profile.channel_map.get('pan', -1)
        ch_tilt = profile.channel_map.get('tilt', -1)
        pan_v  = buf[ch_pan]  / 255.0 if 0 <= ch_pan  < len(buf) else 0.5
        tilt_v = buf[ch_tilt] / 255.0 if 0 <= ch_tilt < len(buf) else 0.5
        result.append({"fixture_id": fx.fixture_id, "pan": round(pan_v, 4), "tilt": round(tilt_v, 4)})

    return {"ok": True, "fixtures": result}


# ── G2 — Sync de tempo (Ableton Link / MIDI Clock) ──────────────────────────

def _h_tempo_sync_get_state(session, params):
    """tempo_sync_get_state() → {mode, bpm, beat_phase, midi_device, synced}"""
    ts = getattr(session, "tempo_sync", None)
    if ts is None:
        return {"mode": "off", "bpm": 0.0, "beat_phase": 0.0,
                "midi_device": None, "synced": False}
    return ts.get_state()


def _h_tempo_sync_set_mode(session, params):
    """tempo_sync_set_mode(mode, device?) — mode ∈ {"off","link","midi_clock"}.

    Activa/desactiva la sincronización de tempo. Si mode="midi_clock", device
    es el nombre del puerto MIDI (string). Si omitido, mido elige el primero disponible.
    """
    mode = require_key(params, "mode")
    device = params.get("device")
    ts = getattr(session, "tempo_sync", None)
    if ts is None:
        return {"ok": False, "error": "TempoSyncService no disponible"}
    import asyncio
    asyncio.create_task(ts.start(mode, device))
    return {"ok": True, "state": ts.get_state()}


def _h_tempo_sync_list_midi_ports(session, params):
    """tempo_sync_list_midi_ports() → {ok, ports: [str]}

    Lista los puertos MIDI disponibles para MIDI Clock.
    """
    try:
        import mido  # type: ignore
        ports = mido.get_input_names()
    except ImportError:
        ports = []
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "ports": list(ports)}


# ── E1 — Sistema de Cues profesional (ROADMAP v3) ────────────────────────────

def _h_add_cue(session, params):
    """add_cue(t_ms, name?, number?, fade_in_ms?, hold_ms?) → {ok, cue}

    Añade una CueEntry a la CueList. El number se auto-asigna si no se indica.
    La lista queda ordenada por number tras la inserción.
    """
    from src.core.timeline_model import CueEntry
    from uuid import uuid4
    try:
        t_ms = require_int(params, "t_ms", min_val=0)
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    entries = session.timeline.cue_list.entries
    number = float(params.get("number", len(entries) + 1))
    hold_ms = int(params.get("hold_ms", -1))
    auto_follow = bool(params.get("auto_follow", hold_ms >= 0))
    entry = CueEntry(
        uid=uuid4().hex[:12],
        number=number,
        name=str(params.get("name", f"Cue {number:g}")),
        t_ms=t_ms,
        fade_in_ms=int(params.get("fade_in_ms", 0)),
        hold_ms=hold_ms,
        auto_follow=auto_follow,
    )
    session.snapshot()
    entries.append(entry)
    entries.sort(key=lambda e: e.number)
    session.notify_changed("cues")
    return {"ok": True, "cue": entry.to_dict()}


def _h_delete_cue(session, params):
    """delete_cue(uid) → {ok}

    Borra una CueEntry. NO borra el CuePoint homónimo (son entidades separadas).
    """
    uid = params.get("uid")
    if not uid:
        return {"ok": False, "error": "uid requerido"}
    entries = session.timeline.cue_list.entries
    before = len(entries)
    session.snapshot()
    session.timeline.cue_list.entries = [e for e in entries if e.uid != uid]
    if len(session.timeline.cue_list.entries) == before:
        return {"ok": False, "error": "cue no encontrado"}
    if session.timeline.cue_list.active_uid == uid:
        session.timeline.cue_list.active_uid = None
    session.notify_changed("cues")
    return {"ok": True}


def _h_update_cue(session, params):
    """update_cue(uid, name?, t_ms?, number?, fade_in_ms?, hold_ms?) → {ok, cue}

    Actualiza campos de una CueEntry existente (los campos no indicados no cambian).
    """
    uid = params.get("uid")
    if not uid:
        return {"ok": False, "error": "uid requerido"}
    entry = next((e for e in session.timeline.cue_list.entries if e.uid == uid), None)
    if entry is None:
        return {"ok": False, "error": "cue no encontrado"}
    session.snapshot()
    if "name" in params:
        entry.name = str(params["name"])
    if "t_ms" in params:
        entry.t_ms = int(params["t_ms"])
    if "number" in params:
        entry.number = float(params["number"])
    if "fade_in_ms" in params:
        entry.fade_in_ms = int(params["fade_in_ms"])
    if "hold_ms" in params:
        entry.hold_ms = int(params["hold_ms"])
    if "auto_follow" in params:
        entry.auto_follow = bool(params["auto_follow"])
    session.notify_changed("cues")
    return {"ok": True, "cue": entry.to_dict()}


def _h_reorder_cues(session, params):
    """reorder_cues() → {ok, cues}

    Reordena la CueList por el campo number (llamar tras editar numbers).
    """
    session.timeline.cue_list.entries.sort(key=lambda e: e.number)
    session.notify_changed("cues")
    return {"ok": True, "cues": [e.to_dict() for e in session.timeline.cue_list.entries]}


def _h_list_cues(session, params):
    """list_cues() → {ok, cues: [...], active_uid: str|None}"""
    cue_list = session.timeline.cue_list
    return {
        "ok": True,
        "cues": [e.to_dict() for e in cue_list.entries],
        "active_uid": cue_list.active_uid,
    }


def _h_go_cue(session, params):
    """go_cue(uid) → {ok, cue}

    Salta al cue: seek al t_ms, inicia fade si fade_in_ms > 0, programa
    auto-follow si cue.auto_follow=True. Emite cue_changed al stream.
    """
    uid = params.get("uid")
    if not uid:
        return {"ok": False, "error": "uid requerido"}
    cue = session.go_cue(uid)
    if cue is None:
        return {"ok": False, "error": "cue no encontrado"}
    return {"ok": True, "cue": cue.to_dict()}


def _h_go_next_cue(session, params):
    """go_next_cue() → {ok, cue: CueEntry|None}

    Avanza al siguiente cue por número. Si ya es el último: {ok, cue: None}.
    """
    cue = session.go_next_cue()
    return {"ok": True, "cue": cue.to_dict() if cue else None}


def _h_go_prev_cue(session, params):
    """go_prev_cue() → {ok, cue: CueEntry|None}

    Retrocede al cue anterior por número. Si ya es el primero: {ok, cue: None}.
    """
    cue = session.go_prev_cue()
    return {"ok": True, "cue": cue.to_dict() if cue else None}


def _h_get_cue_state(session, params):
    """get_cue_state() → {ok, active_uid, fade_pct: 0..1, next_uid} (O(1))"""
    return {"ok": True, **session.get_cue_state()}


# ── E3 — Export de video preview ─────────────────────────────────────────────

def _h_export_video(session, params):
    """export_video(format='gif', scale=4) → {ok} + eventos export_progress.

    Lanza el export en executor (I4). Solo un export a la vez (flag
    export_in_progress en session). Emite {type:'export_progress', pct:float}
    al stream.
    Si no hay render.npz → {ok: False, error}.
    """
    import asyncio
    import shutil

    if getattr(session, 'export_in_progress', False):
        return {"ok": False, "error": "Ya hay un export en curso"}

    fmt = params.get("format", "gif")
    if fmt not in ("gif", "mp4"):
        return {"ok": False, "error": "format debe ser 'gif' o 'mp4'"}

    if fmt == "mp4" and shutil.which("ffmpeg") is None:
        return {"ok": False, "error": "ffmpeg no encontrado en PATH"}

    npz_path = session.project.folder / "render.npz"
    if not npz_path.is_file():
        return {"ok": False, "error": "Sin render. Ejecuta render_offline primero."}

    scale = int(params.get("scale", 4))
    if scale < 1 or scale > 16:
        return {"ok": False, "error": "scale debe ser 1..16"}

    out_path = session.project.folder / f"preview.{fmt}"
    session.export_in_progress = True

    async def _run():
        loop = asyncio.get_event_loop()

        def _progress_fn(pct: float):
            hub = getattr(session, "hub", None)
            if hub:
                try:
                    asyncio.run_coroutine_threadsafe(
                        hub.broadcast_json({"type": "export_progress", "pct": pct}),
                        loop,
                    )
                except Exception:
                    pass

        def _worker():
            from server.video_export import export_preview
            export_preview(str(npz_path), str(out_path), format=fmt,
                           scale=scale, progress_cb=_progress_fn)

        try:
            await loop.run_in_executor(None, _worker)
        except Exception as e:
            print(f"[export_video] error: {e}")
        finally:
            session.export_in_progress = False
            hub = getattr(session, "hub", None)
            if hub:
                try:
                    await hub.broadcast_json({"type": "export_progress", "pct": 100.0, "done": True})
                except Exception:
                    pass

    try:
        asyncio.ensure_future(_run())
    except RuntimeError as e:
        session.export_in_progress = False
        return {"ok": False, "error": f"No se pudo lanzar export: {e}"}
    return {"ok": True, "message": f"Export {fmt} iniciado"}


def _h_get_render_status(session, params):
    """get_render_status() → {ok, status, pct, hash, has_ffmpeg, render_ready}.

    Amplía la versión de B3 con has_ffmpeg (E3) para que el frontend
    sepa si mostrar el botón de MP4.
    """
    import json as _json
    import shutil
    from server.offline_render import compute_timeline_hash

    has_ffmpeg = shutil.which("ffmpeg") is not None

    if getattr(session, 'render_in_progress', False):
        return {
            "ok": True,
            "status": "rendering",
            "pct": getattr(session, 'render_pct', 0.0),
            "hash": None,
            "has_ffmpeg": has_ffmpeg,
            "render_ready": False,
        }

    out_path = session.project.folder / "render.npz"
    meta_path = session.project.folder / "render_meta.json"
    if not out_path.is_file() or not meta_path.is_file():
        return {"ok": True, "status": "idle", "pct": 0.0, "hash": None,
                "has_ffmpeg": has_ffmpeg, "render_ready": False}

    try:
        with open(meta_path, encoding='utf-8') as f:
            meta = _json.load(f)
        current_hash = compute_timeline_hash(session.timeline.to_dict())
        stored_hash = meta.get("show_hash")
        if stored_hash == current_hash:
            return {
                "ok": True,
                "status": "ready",
                "pct": 100.0,
                "hash": stored_hash,
                "n_frames": meta.get("n_frames"),
                "duration_s": meta.get("duration_s"),
                "has_ffmpeg": has_ffmpeg,
                "render_ready": True,
            }
    except Exception:
        pass

    return {"ok": True, "status": "idle", "pct": 0.0, "hash": None,
            "has_ffmpeg": has_ffmpeg, "render_ready": False}


# ── I5 — Exportación PDF patch + CSV DMX ─────────────────────────────────────

def _h_export_patch_pdf(session, params):
    """export_patch_pdf() → {ok, path}.

    Genera PDF (o TXT fallback) con clips del timeline ordenados por pista y
    tiempo. Usa fpdf2 si disponible; si no, crea un .txt equivalente.
    """
    from server.timeline_export import export_patch_pdf
    out_path = str(session.project.folder / "patch.pdf")
    try:
        path = export_patch_pdf(session, out_path)
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _h_export_dmx_csv(session, params):
    """export_dmx_csv(fps=1) → {ok, path}.

    Genera CSV con frames DMX muestreados a fps FPS.
    Cabecera: t_ms,universe,ch_1,...,ch_512.
    Reutiliza render.npz si existe y es coherente; si no, compute_frame.
    """
    from server.timeline_export import export_dmx_csv
    fps = int(params.get("fps", 1))
    if fps < 1:
        return {"ok": False, "error": "fps debe ser >= 1"}
    out_path = str(session.project.folder / "dmx_export.csv")
    try:
        path = export_dmx_csv(session, out_path, fps=fps)
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── E4 — Test de output y patch visual ───────────────────────────────────────

def _h_identify_fixture(session, params):
    """identify_fixture(fixture_id, duration_ms=2000) → {ok}.

    Enciende el fixture a blanco (255,255,255) durante duration_ms ms.
    Estado efímero en session._identify (fixture_id → t_expires).
    Tras duration_ms se auto-apaga (asyncio.create_task con sleep).
    Sin tocar el timeline.
    """
    import asyncio
    import time

    fixture_id = params.get("fixture_id")
    if not fixture_id:
        return {"ok": False, "error": "fixture_id requerido"}

    # Validar que el fixture existe
    rig = getattr(session, 'fixture_rig', None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}

    fx = None
    for f in getattr(rig, 'fixtures', []):
        if getattr(f, 'fixture_id', None) == fixture_id:
            fx = f
            break
    if fx is None:
        return {"ok": False, "error": f"Fixture '{fixture_id}' no encontrado"}

    duration_ms = int(params.get("duration_ms", 2000))
    if duration_ms < 100 or duration_ms > 30000:
        return {"ok": False, "error": "duration_ms debe ser 100..30000"}

    t_expires = time.monotonic() + duration_ms / 1000.0
    if not hasattr(session, '_identify'):
        session._identify = {}
    session._identify[fixture_id] = t_expires

    async def _auto_off():
        await asyncio.sleep(duration_ms / 1000.0)
        if hasattr(session, '_identify'):
            session._identify.pop(fixture_id, None)

    try:
        asyncio.ensure_future(_auto_off())
    except RuntimeError:
        pass  # sin event loop (tests)

    return {"ok": True, "fixture_id": fixture_id, "duration_ms": duration_ms}


def _h_test_universe(session, params):
    """test_universe(universe, r, g, b) → {ok}.

    Llena ese universo Art-Net con el color dado.
    Toggle: segunda llamada con el mismo universo lo apaga.
    universe: 1..10, r/g/b: 0..255.
    """
    try:
        universe = int(params.get("universe", 0))
        r = int(params.get("r", 255))
        g = int(params.get("g", 255))
        b = int(params.get("b", 255))
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": f"Parámetro inválido: {e}"}

    if universe < 1 or universe > 10:
        return {"ok": False, "error": "universe debe ser 1..10"}
    for name, v in [("r", r), ("g", g), ("b", b)]:
        if v < 0 or v > 255:
            return {"ok": False, "error": f"{name} debe ser 0..255"}

    if not hasattr(session, '_test_universes'):
        session._test_universes = {}

    # Toggle: si ya está activo con esos mismos datos, apagar
    current = session._test_universes.get(universe)
    if current is not None and current == (r, g, b):
        del session._test_universes[universe]
        return {"ok": True, "universe": universe, "active": False}

    session._test_universes[universe] = (r, g, b)
    return {"ok": True, "universe": universe, "active": True, "r": r, "g": g, "b": b}


def _h_blackout(session, params):
    """blackout(enabled: bool) → {ok, blackout: bool}.

    Override instantáneo de master brightness a 0 cuando enabled=True.
    No muta timeline.mixer (para no perder el valor del usuario).
    Estado en session.blackout_override (no se persiste en show.json).
    Distinto de blackout_fade (B2): este es de pánico, instantáneo.
    """
    enabled = bool(params.get("enabled", False))
    session.blackout_override = enabled

    # Emitir evento al stream
    import asyncio
    hub = getattr(session, "hub", None)
    if hub:
        try:
            asyncio.ensure_future(
                hub.broadcast_json({"type": "blackout_changed", "enabled": enabled})
            )
        except Exception:
            pass

    return {"ok": True, "blackout": enabled}


def _h_list_clips(session, params):
    """list_clips(filter?, offset?, limit?) → {ok, clips, total, next_offset?}

    H4: si hay > 1000 clips devuelve cursor (offset, limit) en vez de N clips
    en un solo JSON. offset y limit son enteros opcionales.
    filter: {track?, start_ms_min?, start_ms_max?}
    """
    flt = params.get("filter") or {}
    track_f = flt.get("track")
    t_lo = flt.get("start_ms_min")
    t_hi = flt.get("start_ms_max")

    clips = list(getattr(session, "timeline", None).clips
                 if getattr(session, "timeline", None) else [])

    if track_f is not None:
        clips = [c for c in clips if c.track == int(track_f)]
    if t_lo is not None:
        clips = [c for c in clips if c.start_ms >= int(t_lo)]
    if t_hi is not None:
        clips = [c for c in clips if c.start_ms <= int(t_hi)]

    total = len(clips)
    offset = int(params.get("offset", 0))
    limit_raw = params.get("limit")

    if limit_raw is not None:
        limit = int(limit_raw)
        page = clips[offset: offset + limit]
        next_offset = offset + limit if offset + limit < total else None
    else:
        page = clips[offset:]
        next_offset = None

    return {
        "ok": True,
        "clips": [c.to_dict() for c in page],
        "total": total,
        "count": total,       # alias para compat con test_dispatcher.py
        "next_offset": next_offset,
    }


def _h_get_output_status(session, params):
    """get_output_status() → {ok, blackout, has_ffmpeg, render_ready, active_test_universe}.

    Estado unificado de las herramientas de output de E3/E4.
    """
    import shutil

    blackout = getattr(session, 'blackout_override', False)
    has_ffmpeg = shutil.which("ffmpeg") is not None
    render_ready = (session.project.folder / "render.npz").is_file()
    test_uni = getattr(session, '_test_universes', {})
    active_test_universe = list(test_uni.keys())[0] if test_uni else None

    return {
        "ok": True,
        "blackout": blackout,
        "has_ffmpeg": has_ffmpeg,
        "render_ready": render_ready,
        "active_test_universe": active_test_universe,
    }


_LOCAL = {
    # H4 — list_clips con paginación (offset/limit)
    "list_clips": _h_list_clips,
    "undo": _h_undo,
    "redo": _h_redo,
    "export_csv": _h_export_csv,
    "export_qlc": _h_export_qlc,
    "list_presets": _h_list_presets,
    "create_preset": _h_create_preset,
    "update_preset": _h_update_preset,
    "delete_preset": _h_delete_preset,
    "add_preset_clip": _h_add_preset_clip,
    "set_loop": _h_set_loop,
    "set_rec": _h_set_rec,
    "set_volume": _h_set_volume,
    "set_track_mute": _h_set_track_mute,
    "set_track_solo": _h_set_track_solo,
    "get_tracks_state": _h_get_tracks_state,
    "list_feedback": _h_list_feedback,
    "add_feedback": _h_add_feedback,
    "analyzer_waveform_peaks": _h_analyzer_waveform_peaks,
    "set_clip_effect": _h_set_clip_effect,
    "set_clip_preset": _h_set_clip_preset,
    "duplicate_clip": _h_duplicate_clip,
    "split_clip": _h_split_clip,
    "set_clip_param_links": _h_set_clip_param_links,
    "list_modulation_sources": _h_list_modulation_sources,
    "add_automation_lane": _h_add_automation_lane,
    "delete_automation_lane": _h_delete_automation_lane,
    "set_automation_points": _h_set_automation_points,
    "list_automation_lanes": _h_list_automation_lanes,
    # A3 — Patterns
    "create_pattern_from_clips": _h_create_pattern_from_clips,
    "add_pattern_instance": _h_add_pattern_instance,
    "move_pattern_instance": _h_move_pattern_instance,
    "delete_pattern_instance": _h_delete_pattern_instance,
    "update_pattern": _h_update_pattern,
    "delete_pattern": _h_delete_pattern,
    "list_patterns": _h_list_patterns,
    "list_pattern_instances": _h_list_pattern_instances,
    "dissolve_instance": _h_dissolve_instance,
    # A4 — Micro-eventos
    "add_micro_event": _h_add_micro_event,
    "delete_micro_event": _h_delete_micro_event,
    "update_micro_event": _h_update_micro_event,
    # A5 — Ergonomía / I4 — Arranger
    "duplicate_range": _h_duplicate_range,
    "delete_range": _h_delete_range,
    # B1 — Waveform
    "get_waveform": _h_get_waveform,
    # B2 — Mixer
    "set_track_chain": _h_set_track_chain,
    "set_master": _h_set_master,
    "get_mixer": _h_get_mixer,
    # B3 — Render offline + playback baked
    "render_offline": _h_render_offline,
    "toggle_baked": _h_toggle_baked,
    # B4 — Autosave + versiones de show
    "list_autosaves": _h_list_autosaves,
    "restore_autosave": _h_restore_autosave,
    "discard_autosave_prompt": _h_discard_autosave_prompt,
    # C1 — Performance grid: lanzar patterns en vivo
    "live_assign_slot": _h_live_assign_slot,
    "live_trigger": _h_live_trigger,
    "live_release": _h_live_release,
    "live_stop_all": _h_live_stop_all,
    "get_live_state": _h_get_live_state,
    # C2 — Macros en vivo
    "set_macro": _h_set_macro,
    # I1 — Grabación en vivo de macros
    "start_record": _h_start_record,
    "stop_record": _h_stop_record,
    "get_record_state": _h_get_record_state,
    # I2 — Marcadores de timeline con nombre, color y categoría
    "list_markers": _h_list_markers,
    "add_marker": _h_add_marker,
    "delete_marker": _h_delete_marker,
    "update_marker": _h_update_marker,
    # I3 — Grupos colapsables
    "get_group_clips": _h_get_group_clips,
    # D1 — Auto-VJ por reglas
    "autovj_get_state": _h_autovj_get_state,
    "autovj_set_ruleset": _h_autovj_set_ruleset,
    "autovj_activate_preset": _h_autovj_activate_preset,
    "autovj_update_rule": _h_autovj_update_rule,
    "autovj_save": _h_autovj_save,
    "autovj_load": _h_autovj_load,
    # D2 — Análisis en vivo (entrada de audio)
    "live_input_list_devices": _h_live_input_list_devices,
    "live_input_start": _h_live_input_start,
    "live_input_stop": _h_live_input_stop,
    "live_input_get_state": _h_live_input_get_state,
    # E2 — OSC bridge (ROADMAP v3)
    "osc_get_state": _h_osc_get_state,
    "osc_set_config": _h_osc_set_config,
    # G3 — Moving heads: pan/tilt en el timeline
    "list_channel_effects": _h_list_channel_effects,
    "set_clip_channel_effect": _h_set_clip_channel_effect,
    "delete_clip_channel_effect": _h_delete_clip_channel_effect,
    "get_fixture_pan_tilt": _h_get_fixture_pan_tilt,
    # G4 — DMX USB directa
    "list_dmx_ports": _h_list_dmx_ports,
    "set_output_target": _h_set_output_target,
    # H3 — Multi-show quick-switch
    "list_projects": _h_list_projects,
    "switch_project": _h_switch_project,
    # G2 — Sync de tempo (Ableton Link / MIDI Clock)
    "tempo_sync_get_state": _h_tempo_sync_get_state,
    "tempo_sync_set_mode": _h_tempo_sync_set_mode,
    "tempo_sync_list_midi_ports": _h_tempo_sync_list_midi_ports,
    # E1 — Sistema de Cues profesional (ROADMAP v3)
    "add_cue": _h_add_cue,
    "delete_cue": _h_delete_cue,
    "update_cue": _h_update_cue,
    "reorder_cues": _h_reorder_cues,
    "list_cues": _h_list_cues,
    "go_cue": _h_go_cue,
    "go_next_cue": _h_go_next_cue,
    "go_prev_cue": _h_go_prev_cue,
    "get_cue_state": _h_get_cue_state,
    # I5 — Exportación PDF patch + CSV DMX
    "export_patch_pdf": _h_export_patch_pdf,
    "export_dmx_csv": _h_export_dmx_csv,
    # E3 — Export de video preview (ROADMAP v3)
    "export_video": _h_export_video,
    "get_render_status": _h_get_render_status,
    # E4 — Test de output y patch visual (ROADMAP v3)
    "identify_fixture": _h_identify_fixture,
    "test_universe": _h_test_universe,
    "blackout": _h_blackout,
    "get_output_status": _h_get_output_status,
    # F2 — Plugin UI auto-generada (ROADMAP v3)
    "get_effect_schema": _h_get_effect_schema,
    # F4 — Live preview en el inspector (ROADMAP v3)
    "preview_effect_frame": _h_preview_effect_frame,
}


class Dispatcher:
    """Procesa mensajes JSON-RPC contra un ShowSession."""

    def __init__(self, session):
        self.session = session

    @property
    def methods(self):
        return ([m for m in bridge.HANDLERS if m not in _EXCLUDED]
                + list(_LOCAL.keys()))

    def handle(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un mensaje JSON-RPC 2.0 completo y devuelve la respuesta."""
        import traceback
        method = msg.get("method")
        msg_id = msg.get("id")
        if method in _EXCLUDED:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601,
                              "message": f"Método no disponible en web: {method}"}}
        # Snapshot para undo antes de mutar el timeline
        if method in _TIMELINE_MUTATORS:
            try:
                self.session.snapshot()
            except Exception:
                pass
        # Handlers locales (web-only) tienen prioridad
        if method in _LOCAL:
            try:
                result = _LOCAL[method](self.session, msg.get("params") or {})
                self._maybe_sync_rig(method)
                return {"jsonrpc": "2.0", "id": msg_id, "result": result}
            except Exception as e:
                return {"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32000, "message": str(e),
                                  "data": traceback.format_exc()}}
        resp = bridge._dispatch(self.session, msg)
        self._maybe_sync_rig(method)
        return resp

    def _maybe_sync_rig(self, method: str) -> None:
        """Tras mutar el rig, regenera rig_layout.json para que el visor 3D lo
        refleje al recargar (la tab del visor re-monta el iframe al volver a ella)."""
        if method in _RIG_MUTATORS:
            try:
                self.session.sync_rig_layout()
            except Exception:
                pass

    def call(self, method: str, params: Optional[dict] = None) -> Dict[str, Any]:
        """Atajo: invoca un método y devuelve el `result` (o lanza en error)."""
        resp = self.handle({"jsonrpc": "2.0", "id": 1,
                             "method": method, "params": params or {}})
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error'].get('message')}")
        return resp["result"]
