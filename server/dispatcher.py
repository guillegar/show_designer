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
from typing import Any

# Setup MINIMAL de sys.path ANTES de importar src._setup_paths
# (necesario porque src._setup_paths es lo que configura sys.path correctamente)
_root = Path(__file__).resolve().parent.parent  # server/dispatcher.py → show-director/
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Setup centralizado de sys.path (única fuente de verdad)
import src.mcp.mcp_bridge as bridge  # noqa: E402
from server.exporters import export_to_memory  # noqa: E402
from server.toggles import toggle_set_membership  # noqa: E402
from server.validators import ValidationError, require_int, require_key, require_order  # noqa: E402
from src._setup_paths import *
from src.log import get_logger

_log = get_logger(__name__)

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
}

# Métodos que mutan el rig de fixtures → regenerar rig_layout.json para el visor 3D
# (si no, el visor muestra posiciones obsoletas tras mover/editar fixtures en Patch).
_RIG_MUTATORS = {
    "set_fixture_property", "add_fixture", "delete_fixture",
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

    from src.core.effects_engine import LEDS_PER_BAR, NUM_BARS

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
        import base64
        import io

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
    from uuid import uuid4

    from src.core.automation import AutomationLane
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

    from uuid import uuid4

    from src.core.timeline_model import Pattern, PatternInstance

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

    from uuid import uuid4

    from src.core.timeline_model import PatternInstance

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

    from uuid import uuid4

    from src.core.timeline_model import Clip, Pattern, PatternInstance

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
    # Heartbeat — keep-alive ligero (el frontend lo usa para detectar
    # conexiones medio-abiertas y forzar la reconexión).
    "ping": lambda session, params: {"ok": True},
    # F2 — Plugin UI auto-generada (ROADMAP v3)
    "get_effect_schema": _h_get_effect_schema,
    # F4 — Live preview en el inspector (ROADMAP v3)
    "preview_effect_frame": _h_preview_effect_frame,
    # L3 — Multiusuario: rol del token actual
    "auth_get_role": lambda session, params: {"ok": True, "role": "operator"},
}

# ── ADR-005: dominios extraídos a server/handlers/ ────────────────────────────
# Cada módulo de dominio define HANDLERS (+ mutadores propios); aquí se mergean.
from server import handlers as _handlers_pkg  # noqa: E402

_handlers_pkg.load_all()
_LOCAL.update(_handlers_pkg.LOCAL)
_TIMELINE_MUTATORS |= _handlers_pkg.TIMELINE_MUTATORS
_RIG_MUTATORS |= _handlers_pkg.RIG_MUTATORS

# Compat: tests y server/web.py importan estos nombres desde server.dispatcher.
from server.handlers.autosave import (  # noqa: E402,F401
    _h_discard_autosave_prompt,
    _h_list_autosaves,
    _h_restore_autosave,
)
from server.handlers.autovj import (  # noqa: E402,F401
    _h_autovj_activate_preset,
    _h_autovj_get_state,
    _h_autovj_load,
    _h_autovj_save,
    _h_autovj_set_ruleset,
    _h_autovj_update_rule,
    _h_live_input_get_state,
    _h_live_input_list_devices,
    _h_live_input_start,
    _h_live_input_stop,
)
from server.handlers.bundle_market import (  # noqa: E402,F401
    _h_export_show_bundle,
    _h_import_show_bundle,
    _h_install_plugin,
    _h_list_marketplace_plugins,
)
from server.handlers.cues import (  # noqa: E402,F401
    _h_add_cue,
    _h_delete_cue,
    _h_get_cue_state,
    _h_go_cue,
    _h_go_next_cue,
    _h_go_prev_cue,
    _h_list_cues,
    _h_reorder_cues,
    _h_update_cue,
)
from server.handlers.gdtf import (  # noqa: E402,F401
    _gdtf_cache,
    _gdtf_metadata,
    _h_add_fixture_from_gdtf,
    _h_list_gdtf_profiles,
)
from server.handlers.live import (  # noqa: E402,F401
    _h_get_live_state,
    _h_get_record_state,
    _h_live_assign_slot,
    _h_live_release,
    _h_live_stop_all,
    _h_live_trigger,
    _h_set_macro,
    _h_start_record,
    _h_stop_record,
)
from server.handlers.markers import (  # noqa: E402,F401
    _h_add_marker,
    _h_delete_marker,
    _h_get_group_clips,
    _h_list_markers,
    _h_update_marker,
)
from server.handlers.mixer import (  # noqa: E402,F401
    _h_get_mixer,
    _h_set_master,
    _h_set_track_chain,
)
from server.handlers.movers import (  # noqa: E402,F401
    _h_delete_clip_channel_effect,
    _h_get_fixture_pan_tilt,
    _h_list_channel_effects,
    _h_list_dmx_ports,
    _h_set_clip_channel_effect,
    _h_set_output_target,
)
from server.handlers.osc import (  # noqa: E402,F401
    _h_osc_get_state,
    _h_osc_set_config,
)
from server.handlers.output_test import (  # noqa: E402,F401
    _h_blackout,
    _h_chase_stop,
    _h_chase_test,
    _h_get_output_status,
    _h_identify_fixture,
    _h_test_universe,
)
from server.handlers.patch import (  # noqa: E402,F401
    _get_artnet_ip_for_universe,
    _h_duplicate_fixture,
    _h_get_fixture_detail,
    _h_get_output_targets,
    _h_get_universe_channel_map,
    _h_list_fixture_types,
    _h_next_free_address,
    _h_update_fixture,
    _update_rig_layout_height,
)
from server.handlers.patch_visual import (  # noqa: E402,F401
    _h_move_fixture,
    _h_set_fixture_type,
    _update_layout_floor,
)
from server.handlers.pixelmap import (  # noqa: E402,F401
    _h_set_clip_pixel_map,
)
from server.handlers.projects import (  # noqa: E402,F401
    _h_apply_autovj,
    _h_apply_presets,
    _h_apply_rig,
    _h_apply_song,
    _h_create_project_from_components,
    _h_duplicate_project,
    _h_list_available_analyses,
    _h_list_components,
    _h_list_projects_detailed,
    _h_load_sequence,
    _h_update_project,
    _safe_project_slug,
)
from server.handlers.render_export import (  # noqa: E402,F401
    _h_export_dmx_csv,
    _h_export_patch_pdf,
    _h_export_video,
    _h_get_render_status,
    _h_render_offline,
    _h_toggle_baked,
)
from server.handlers.showgen import (  # noqa: E402,F401
    _h_clear_gesture_history,
    _h_generate_show,
    _h_list_gesture_history,
    _h_replay_gesture,
)
from server.handlers.switch import (  # noqa: E402,F401
    _h_list_projects,
    _h_switch_project,
)
from server.handlers.tempo import (  # noqa: E402,F401
    _h_get_key_info,
    _h_tap_bpm,
    _h_tempo_sync_get_state,
    _h_tempo_sync_list_midi_ports,
    _h_tempo_sync_set_mode,
)
from server.handlers.viewer3d import (  # noqa: E402,F401
    _h_get_rig_layout,
    _h_set_fixture_3d,
)
from server.handlers.waveform import (  # noqa: E402,F401
    _compute_waveform,
    _ensure_waveform_cached,
    _h_get_waveform,
)
from server.handlers.webhooks_config import (  # noqa: E402,F401
    _h_webhook_get_config,
    _h_webhook_set_config,
)


class Dispatcher:
    """Procesa mensajes JSON-RPC contra un ShowSession."""

    def __init__(self, session):
        self.session = session

    @property
    def methods(self):
        return ([m for m in bridge.HANDLERS if m not in _EXCLUDED]
                + list(_LOCAL.keys()))

    def handle(self, msg: dict[str, Any], token: str = "") -> dict[str, Any]:
        """Procesa un mensaje JSON-RPC 2.0 completo y devuelve la respuesta."""
        import traceback
        method = msg.get("method")
        msg_id = msg.get("id")
        if method in _EXCLUDED:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601,
                              "message": f"Método no disponible en web: {method}"}}

        # L3: control de acceso por rol
        if method == "auth_get_role":
            from server.auth import role_for_token
            tokens_cfg = getattr(self.session, "_tokens_config", [])
            if not isinstance(tokens_cfg, list):
                tokens_cfg = []
            role = role_for_token(token, tokens_cfg)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"ok": True, "role": role}}

        from server.auth import check_permission
        tokens_cfg = getattr(self.session, "_tokens_config", [])
        if not isinstance(tokens_cfg, list):
            tokens_cfg = []
        perm = check_permission(token, method or "", tokens_cfg)
        if not perm["ok"]:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"ok": False, "error": perm["error"]}}
        # Snapshot para undo antes de mutar el timeline
        if method in _TIMELINE_MUTATORS:
            try:
                self.session.snapshot()
            except Exception:
                pass
        # Handlers locales (web-only) tienen prioridad
        params = msg.get("params") or {}
        if method in _LOCAL:
            try:
                import asyncio
                import concurrent.futures
                result = _LOCAL[method](self.session, params)
                # FIX 3: support async handlers (e.g. marketplace) without changing
                # the sync dispatcher contract — run in a thread when already in a loop
                if asyncio.iscoroutine(result):
                    try:
                        asyncio.get_running_loop()
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                            result = ex.submit(asyncio.run, result).result(timeout=30)
                    except RuntimeError:
                        result = asyncio.run(result)
                self._maybe_sync_rig(method)
                self._record_gesture(method, params)
                return {"jsonrpc": "2.0", "id": msg_id, "result": result}
            except Exception as e:
                return {"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32000, "message": str(e),
                                  "data": traceback.format_exc()}}
        resp = bridge._dispatch(self.session, msg)
        self._maybe_sync_rig(method)
        self._record_gesture(method, params)
        return resp

    def _record_gesture(self, method: str | None, params: dict) -> None:
        """M3: graba el gesto en el GestureLog de la sesión."""
        if not method:
            return
        gl = getattr(self.session, "_gesture_log", None)
        if gl is None:
            return
        t_ms = 0
        try:
            t_ms = self.session._current_t_ms()
        except Exception:
            pass
        gl.record(method, params, t_ms)

    def _maybe_sync_rig(self, method: str) -> None:
        """Tras mutar el rig, regenera rig_layout.json para que el visor 3D lo
        refleje al recargar (la tab del visor re-monta el iframe al volver a ella)."""
        if method in _RIG_MUTATORS:
            try:
                self.session.sync_rig_layout()
            except Exception:
                pass

    def call(self, method: str, params: dict | None = None) -> dict[str, Any]:
        """Atajo: invoca un método y devuelve el `result` (o lanza en error)."""
        resp = self.handle({"jsonrpc": "2.0", "id": 1,
                             "method": method, "params": params or {}})
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error'].get('message')}")
        return resp["result"]
