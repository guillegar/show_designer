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
    "load_sequence",  # intercambiar la secuencia por la de otro proyecto
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
    "save_rig", "load_show", "update_fixture", "duplicate_fixture",
    "apply_rig",  # intercambiar el rig por el de otro proyecto
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


def _compute_waveform(audio_path, n=_WAVEFORM_N_BUCKETS, bpm=120.0):
    """Cálculo puro y pesado de la forma de onda (librosa.load + min/max/rms por
    cubo). BLOQUEANTE (~2-5 s) → debe correr en un executor, NUNCA en el event
    loop. Devuelve el dict de datos, o None si librosa no está disponible."""
    try:
        import librosa as _librosa
        import numpy as _np
    except ImportError:
        return None

    y, sr = _librosa.load(str(audio_path), sr=None, mono=True)
    total = len(y)
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

    return {
        "peaks_max": peaks_max,
        "peaks_min": peaks_min,
        "rms": rms_vals,
        "n_buckets": n,
        "duration_sec": round(float(total / sr), 3),
        "bpm": float(bpm),
    }


def _ensure_waveform_cached(session):
    """Garantiza que <analysis_dir>/waveform.json existe y devuelve sus datos.

    Es la parte BLOQUEANTE (pensada para correr en un executor). Idempotente: si
    el cache ya está, lo lee; si no, calcula y lo escribe atómicamente
    (.tmp → replace). Devuelve el dict de datos, o None (sin librosa o sin audio).
    """
    import json as _json
    from pathlib import Path as _Path

    analysis_dir = session.analysis.analysis_dir
    cache_path = analysis_dir / "waveform.json"
    if cache_path.is_file():
        try:
            return _json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass  # cache corrupto → recomputar

    audio_path = _Path(session.project.audio_path)
    if not audio_path.is_file():
        return None

    data = _compute_waveform(audio_path, _WAVEFORM_N_BUCKETS,
                             float(getattr(session, "bpm", 120)))
    if data is None:
        return None

    analysis_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(_json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(cache_path)
    return data


def _h_get_waveform(session, params):
    """Forma de onda del audio en _WAVEFORM_N_BUCKETS cubos.

    El cálculo (librosa.load) tarda ~2-5 s y `dispatcher.handle` corre en el hilo
    del event loop (el MISMO del tick): bloquearlo congela el show en vivo. Por
    eso: si el cache existe se devuelve al instante; si no, se lanza el cálculo en
    un executor y se devuelve {status:'computing'} — el frontend recibe el evento
    'waveform_ready' por el stream y vuelve a pedirlo (ya cache hit). En contextos
    SIN event loop (tests / compat MCP síncrona) se calcula inline.
    """
    import asyncio
    import json as _json

    analysis_dir = session.analysis.analysis_dir
    cache_path = analysis_dir / "waveform.json"
    if cache_path.is_file():
        try:
            return {"ok": True, **_json.loads(cache_path.read_text(encoding="utf-8"))}
        except Exception:
            pass  # cache corrupto → recomputar abajo

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        # Sin event loop (tests / compat MCP síncrona): calcular inline.
        data = _ensure_waveform_cached(session)
        if data is None:
            return {"ok": False, "error": "librosa no disponible o audio no encontrado"}
        return {"ok": True, **data}

    # Contexto web: NO bloquear el loop. Calcular en background y avisar por stream.
    if getattr(session, "_waveform_computing", False):
        return {"ok": True, "status": "computing"}
    session._waveform_computing = True
    hub = getattr(session, "hub", None)

    def _job():
        try:
            data = _ensure_waveform_cached(session)
        finally:
            session._waveform_computing = False
        if data is not None and hub is not None:
            try:
                asyncio.run_coroutine_threadsafe(
                    hub.broadcast_json({"type": "waveform_ready"}), loop)
            except Exception:
                pass

    loop.run_in_executor(None, _job)
    return {"ok": True, "status": "computing"}


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

    from uuid import uuid4

    from src.core.automation import AutomationLane

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
    import json
    from pathlib import Path

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


# ── Menú de gestión de proyectos: galería + componentes + crear/copiar ───────
# Un proyecto = paquete de archivos intercambiables (canción/rig/secuencia/
# presets/auto-VJ). Estos handlers exponen ese paquete para verlo, cargar piezas
# sueltas sobre el proyecto activo, y componer/copiar proyectos nuevos.

import json as _json  # noqa: E402
import re as _re  # noqa: E402
import shutil as _shutil  # noqa: E402


def _pm_of(session):
    return getattr(session, "pm", None) or getattr(session, "_pm", None)


def _read_json_safe(path):
    try:
        with open(path, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None


def _song_meta(analysis_slug):
    """{title, bpm, duration_s} de un análisis. Lazy: AnalysisService.summary solo
    lee analysis.json (no el .npz), así que es barato para listar varias canciones."""
    out = {"analysis_slug": analysis_slug, "title": analysis_slug or "—",
           "bpm": None, "duration_s": None}
    if not analysis_slug:
        return out
    try:
        from src.analysis.analyzer_service import ANALIZADAS_DIR, AnalysisService
        d = ANALIZADAS_DIR / analysis_slug
        if not d.is_dir():
            return out
        s = AnalysisService(d).summary or {}
        out["bpm"] = s.get("bpm")
        out["duration_s"] = s.get("duration_s")
        f = s.get("file")
        if f:
            out["title"] = str(f).rsplit(".", 1)[0]
    except Exception:
        pass
    return out


def _safe_project_slug(raw, projects_dir):
    """Slug seguro (sin path traversal) + sin colisiones. Mismo criterio que el
    import de bundles en server/show_bundle.py."""
    base = _re.sub(r"[^a-z0-9_-]", "_", str(raw or "").strip().lower())
    base = _re.sub(r"_+", "_", base).strip("_") or "proyecto"
    slug, suffix = base, 1
    while (projects_dir / slug).exists():
        slug = f"{base}_{suffix}"
        suffix += 1
    return slug


def _h_list_projects_detailed(session, params):
    """list_projects_detailed() → galería: cada proyecto con su canción, rig y
    secuencia resumidos. Lecturas JSON ligeras; NO sustituye a list_projects."""
    pm = _pm_of(session)
    if pm is None:
        return {"ok": True, "projects": [], "current": None}
    current_slug = session.project.slug if getattr(session, "project", None) else None
    out = []
    for p in pm.list_projects():
        rig = _read_json_safe(p.rig_file) or {}
        show = _read_json_safe(p.show_file) or {}
        song = _song_meta(p.analysis_slug)
        out.append({
            "slug": p.slug,
            "name": p.name,
            "is_current": p.slug == current_slug,
            "notes": p.notes,
            "created": p.created,
            "song": {"title": song["title"], "bpm": song["bpm"],
                     "duration_s": song["duration_s"],
                     "analysis_slug": p.analysis_slug, "audio_path": str(p.audio_path)},
            "rig": {"fixture_count": len(rig.get("fixtures") or [])},
            "sequence": {"clip_count": len(show.get("clips") or [])},
            "has_presets": (p.folder / "presets.json").is_file(),
            "has_autovj": (p.folder / "autovj.json").is_file(),
        })
    return {"ok": True, "projects": out, "current": current_slug}


def _h_list_components(session, params):
    """list_components() → {rigs, songs, sequences, presets, autovj} agregados de
    todos los proyectos (+ canciones de analizadas/ aún sin usar)."""
    pm = _pm_of(session)
    empty = {"ok": True, "current": None, "rigs": [], "songs": [],
             "sequences": [], "presets": [], "autovj": []}
    if pm is None:
        return empty
    current_slug = session.project.slug if getattr(session, "project", None) else None
    rigs, sequences, presets, autovj = [], [], [], []
    song_used = {}    # analysis_slug -> [project slugs]
    song_audio = {}   # analysis_slug -> audio_path (de algún proyecto que la use)
    for p in pm.list_projects():
        rig = _read_json_safe(p.rig_file) or {}
        show = _read_json_safe(p.show_file) or {}
        rigs.append({"source_slug": p.slug, "source_name": p.name,
                     "fixture_count": len(rig.get("fixtures") or []),
                     "is_current": p.slug == current_slug})
        sequences.append({"source_slug": p.slug, "source_name": p.name,
                          "clip_count": len(show.get("clips") or []),
                          "pattern_count": len(show.get("patterns") or []),
                          "duration_ms": show.get("duration_ms"),
                          "is_current": p.slug == current_slug})
        pf = p.folder / "presets.json"
        if pf.is_file():
            presets.append({"source_slug": p.slug, "source_name": p.name,
                            "count": len(_read_json_safe(pf) or []),
                            "is_current": p.slug == current_slug})
        af = p.folder / "autovj.json"
        if af.is_file():
            data = _read_json_safe(af) or {}
            rules = data.get("rules") if isinstance(data, dict) else None
            autovj.append({"source_slug": p.slug, "source_name": p.name,
                           "rule_count": len(rules) if rules else 0,
                           "is_current": p.slug == current_slug})
        if p.analysis_slug:
            song_used.setdefault(p.analysis_slug, []).append(p.slug)
            song_audio.setdefault(p.analysis_slug, str(p.audio_path))
    songs = []
    try:
        from src.analysis.analyzer_service import ANALIZADAS_DIR
        if ANALIZADAS_DIR.is_dir():
            for d in sorted(ANALIZADAS_DIR.iterdir()):
                if not d.is_dir() or not (d / "analysis.json").is_file():
                    continue
                meta = _song_meta(d.name)
                # Si no hay audio_path de un proyecto que use esta canción,
                # intenta leerlo desde analysis.json
                audio_path = song_audio.get(d.name, "")
                if not audio_path:
                    analysis_data = _read_json_safe(d / "analysis.json") or {}
                    # Si analysis.json tiene el campo "file", úsalo como audio_path
                    if "file" in analysis_data:
                        audio_path = str(analysis_data["file"])
                songs.append({"analysis_slug": d.name, "title": meta["title"],
                              "bpm": meta["bpm"], "duration_s": meta["duration_s"],
                              "audio_path": audio_path,
                              "used_by": song_used.get(d.name, [])})
    except Exception:
        pass
    return {"ok": True, "current": current_slug, "rigs": rigs, "songs": songs,
            "sequences": sequences, "presets": presets, "autovj": autovj}


def _h_apply_rig(session, params):
    """apply_rig(from_slug) → carga el rig de otro proyecto en el activo y lo
    persiste en su rig.json. Mutador de rig (regenera rig_layout para el visor 3D)."""
    pm = _pm_of(session)
    from_slug = str(params.get("from_slug", "") or "")
    src = pm.get_project(from_slug) if pm else None
    if src is None or not src.rig_file.is_file():
        return {"ok": False, "error": f"rig no encontrado: {from_slug!r}"}
    try:
        n = session.load_rig(src.rig_file)
    except Exception as e:
        return {"ok": False, "error": f"no se pudo cargar el rig: {e}"}
    try:
        session.fixture_rig.save(session.project.rig_file)
    except Exception as e:
        _log.warning(f"[apply_rig] no se pudo persistir rig.json: {e}")
    session.notify_changed("rig")
    return {"ok": True, "from_slug": from_slug, "fixtures": n}


def _h_load_sequence(session, params):
    """load_sequence(from_slug) → intercambia la secuencia (clips/grupos/cues) por
    la de otro proyecto. En memoria (undo lo cubre); se persiste al guardar/autosave,
    como cualquier edición del timeline. Reutiliza _h_load_show del bridge."""
    pm = _pm_of(session)
    from_slug = str(params.get("from_slug", "") or "")
    src = pm.get_project(from_slug) if pm else None
    if src is None or not src.show_file.is_file():
        return {"ok": False, "error": f"secuencia no encontrada: {from_slug!r}"}
    res = bridge._h_load_show(session, {"path": str(src.show_file)})
    if res.get("ok"):
        session.notify_changed("model")
        res["from_slug"] = from_slug
    return res


def _h_apply_presets(session, params):
    """apply_presets(from_slug) → copia el banco de presets de otro proyecto al
    presets.json del activo y recrea el PresetBank."""
    pm = _pm_of(session)
    from_slug = str(params.get("from_slug", "") or "")
    src = pm.get_project(from_slug) if pm else None
    if src is None:
        return {"ok": False, "error": f"proyecto no encontrado: {from_slug!r}"}
    src_file = src.folder / "presets.json"
    if not src_file.is_file():
        return {"ok": False, "error": f"{from_slug!r} no tiene presets"}
    dst_file = session.project.folder / "presets.json"
    try:
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(src_file, dst_file)
        from server.presets import PresetBank
        session.presets = PresetBank(session.library, session.channel_lib,
                                     project_file=dst_file)
        n = len(session.presets.list())
    except Exception as e:
        return {"ok": False, "error": str(e)}
    session.notify_changed("model")
    return {"ok": True, "from_slug": from_slug, "presets": n}


def _h_apply_autovj(session, params):
    """apply_autovj(from_slug) → copia las reglas Auto-VJ de otro proyecto al
    autovj.json del activo y las carga en el motor."""
    pm = _pm_of(session)
    from_slug = str(params.get("from_slug", "") or "")
    src = pm.get_project(from_slug) if pm else None
    if src is None:
        return {"ok": False, "error": f"proyecto no encontrado: {from_slug!r}"}
    src_file = src.folder / "autovj.json"
    if not src_file.is_file():
        return {"ok": False, "error": f"{from_slug!r} no tiene auto-VJ"}
    dst_file = session.project.folder / "autovj.json"
    try:
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(src_file, dst_file)
        session.autovj_engine.load(dst_file)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    session.notify_changed("model")
    return {"ok": True, "from_slug": from_slug}


def _h_apply_song(session, params):
    """apply_song(analysis_slug, audio_path) → cambia la canción del proyecto activo
    (actualiza project.json + recarga análisis/audio + reajusta duración).
    AVISO: re-temporiza el show (los beats/duración de la nueva canción difieren)."""
    from src._paths import ANALIZADAS_DIR

    analysis_slug = str(params.get("analysis_slug", "") or "")
    audio_path = str(params.get("audio_path", "") or "")
    if not analysis_slug and not audio_path:
        return {"ok": False, "error": "analysis_slug o audio_path requerido"}
    proj = getattr(session, "project", None)
    if proj is None:
        return {"ok": False, "error": "sin proyecto activo"}

    # Si audio_path es solo un nombre de archivo (sin rutas), intenta buscarlo en ANALIZADAS_DIR
    if audio_path and "/" not in audio_path and "\\" not in audio_path:
        candidate = ANALIZADAS_DIR / analysis_slug / audio_path if analysis_slug else None
        if candidate and candidate.is_file():
            audio_path = str(candidate)

    try:
        if analysis_slug:
            proj.analysis_slug = analysis_slug
        if audio_path:
            proj.audio_path = audio_path
        proj.save_meta()
    except Exception as e:
        return {"ok": False, "error": f"no se pudo actualizar project.json: {e}"}
    dur_ms = session.load_song(proj.audio_path, proj.analysis_slug)
    try:
        session.timeline.duration_ms = dur_ms
    except Exception:
        pass
    session.notify_changed("model")
    return {"ok": True, "analysis_slug": proj.analysis_slug,
            "audio_path": str(proj.audio_path), "duration_ms": dur_ms}


def _h_update_project(session, params):
    """update_project(slug, name?, notes?, analysis_slug?) → actualiza metadatos de un
    proyecto (incluso si no es activo). Solo campos no-vacíos se actualizan."""
    pm = _pm_of(session)
    if pm is None:
        return {"ok": False, "error": "sin project manager"}
    slug = str(params.get("slug", "") or "").strip()
    if not slug:
        return {"ok": False, "error": "slug requerido"}
    proj = pm.get_project(slug)
    if proj is None:
        return {"ok": False, "error": f"proyecto {slug} no existe"}

    # Actualizar campos si están presentes
    name = params.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            return {"ok": False, "error": "nombre no puede estar vacío"}
        proj.name = name

    notes = params.get("notes")
    if notes is not None:
        proj.notes = str(notes).strip()

    analysis_slug = params.get("analysis_slug")
    if analysis_slug is not None:
        analysis_slug = str(analysis_slug).strip()
        # Validar que existe en analizadas/ si no es vacío
        if analysis_slug:
            from pathlib import Path

            from src._paths import ANALIZADAS_DIR
            analysis_file = Path(ANALIZADAS_DIR) / analysis_slug / "analysis.json"
            if not analysis_file.exists():
                return {"ok": False, "error": f"análisis {analysis_slug} no encontrado en analizadas/"}
        proj.analysis_slug = analysis_slug

    # Persistir
    try:
        proj.save_meta()
    except Exception as e:
        return {"ok": False, "error": f"error al guardar project.json: {e}"}

    # Notificar si es proyecto activo
    current = getattr(session, "project", None)
    if current and current.slug == slug:
        session.notify_changed("model")

    return {
        "ok": True,
        "slug": proj.slug,
        "name": proj.name,
        "notes": proj.notes,
        "audio_path": str(proj.audio_path),
        "analysis_slug": proj.analysis_slug,
    }


def _h_list_available_analyses(session, params):
    """list_available_analyses() → enumera todos los análisis disponibles en analizadas/."""
    import json
    from pathlib import Path

    from src._paths import ANALIZADAS_DIR

    analyses = []
    analizadas_path = Path(ANALIZADAS_DIR)

    if analizadas_path.exists():
        for analysis_dir in sorted(analizadas_path.iterdir()):
            if not analysis_dir.is_dir():
                continue
            analysis_file = analysis_dir / "analysis.json"
            if not analysis_file.exists():
                continue
            try:
                with open(analysis_file, encoding="utf-8") as f:
                    data = json.load(f)
                    title = data.get("file", analysis_dir.name)
                    bpm = data.get("global", {}).get("bpm_librosa") or data.get("global", {}).get("bpm_madmom")
                    duration_s = data.get("duration_s")
                    analyses.append({
                        "analysis_slug": analysis_dir.name,
                        "title": title,
                        "bpm": bpm,
                        "duration_s": duration_s,
                    })
            except Exception:
                # ignorar análisis corruptos
                pass

    return {"ok": True, "analyses": analyses}


# Componentes copiables y sus archivos (para crear/duplicar)
_COMPONENT_FILES = {
    "rig": ["rig.json", "rig_layout.json"],
    "sequence": ["show.json"],
    "presets": ["presets.json"],
    "autovj": ["autovj.json"],
    # "song" no es un archivo: vive en project.json (audio_path + analysis_slug)
}


def _h_create_project_from_components(session, params):
    """create_project_from_components(name, slug?, song_from?, rig_from?,
    sequence_from?, presets_from?, autovj_from?) → crea un proyecto nuevo copiando
    cada componente elegido del proyecto origen indicado. NO carga el proyecto
    (el frontend puede llamar a switch_project después si el usuario lo pide)."""
    pm = _pm_of(session)
    if pm is None:
        return {"ok": False, "error": "sin project manager"}
    name = str(params.get("name", "") or "").strip()
    if not name:
        return {"ok": False, "error": "name requerido"}
    from src.io.project_manager import PROJECTS_DIR
    slug = _safe_project_slug(params.get("slug") or name, PROJECTS_DIR)

    # Canción: del proyecto origen (audio_path + analysis_slug)
    audio_path, analysis_slug = "", ""
    song_from = str(params.get("song_from", "") or "")
    if song_from:
        sp = pm.get_project(song_from)
        if sp is not None:
            audio_path, analysis_slug = str(sp.audio_path), sp.analysis_slug

    try:
        proj = pm.create_project(slug=slug, name=name, audio_path=audio_path,
                                 analysis_slug=analysis_slug,
                                 notes=str(params.get("notes", "") or ""))
    except Exception as e:
        return {"ok": False, "error": f"no se pudo crear: {e}"}
    # create_project pone pm._current = proj; restaurar el proyecto realmente activo
    try:
        pm._current = session.project
    except Exception:
        pass

    def _copy_component(comp_from, files):
        if not comp_from:
            return
        sp = pm.get_project(comp_from)
        if sp is None:
            return
        for fname in files:
            srcf = sp.folder / fname
            if srcf.is_file():
                _shutil.copy2(srcf, proj.folder / fname)

    _copy_component(str(params.get("rig_from", "") or ""), _COMPONENT_FILES["rig"])
    _copy_component(str(params.get("sequence_from", "") or ""), _COMPONENT_FILES["sequence"])
    _copy_component(str(params.get("presets_from", "") or ""), _COMPONENT_FILES["presets"])
    _copy_component(str(params.get("autovj_from", "") or ""), _COMPONENT_FILES["autovj"])
    return {"ok": True, "slug": slug, "name": name}


def _h_duplicate_project(session, params):
    """duplicate_project(from_slug, new_name?, new_slug?, swap?) → copia un proyecto
    a un slug nuevo (solo archivos de contenido) y, opcionalmente, sustituye UN
    componente por el de otro proyecto. swap = {component, source_slug}."""
    pm = _pm_of(session)
    if pm is None:
        return {"ok": False, "error": "sin project manager"}
    from_slug = str(params.get("from_slug", "") or "")
    src = pm.get_project(from_slug) if from_slug else None
    if src is None:
        return {"ok": False, "error": f"proyecto no encontrado: {from_slug!r}"}
    from src.io.project_manager import PROJECTS_DIR, Project
    new_name = str(params.get("new_name", "") or "").strip() or f"{src.name} (copia)"
    slug = _safe_project_slug(params.get("new_slug") or new_name, PROJECTS_DIR)
    dst = PROJECTS_DIR / slug
    # Copia limpia: solo contenido (sin autosave/render/exports)
    ignore = _shutil.ignore_patterns("autosave", "render.npz", "render_meta.json",
                                     "preview.gif", "preview.mp4", "patch.pdf",
                                     "dmx_export.csv", "feedback.json")
    try:
        _shutil.copytree(src.folder, dst, ignore=ignore)
    except Exception as e:
        return {"ok": False, "error": f"no se pudo copiar: {e}"}

    def _set_meta(name, audio=None, analysis=None):
        p = Project.from_folder(dst)
        if p is None:
            return
        p.slug, p.name = slug, name
        if audio is not None:
            p.audio_path = audio
        if analysis is not None:
            p.analysis_slug = analysis
        p.save_meta()

    _set_meta(new_name)

    swap = params.get("swap") or {}
    comp = str(swap.get("component", "") or "")
    source_slug = str(swap.get("source_slug", "") or "")
    if comp and source_slug:
        sp = pm.get_project(source_slug)
        if sp is not None:
            if comp == "song":
                _set_meta(new_name, audio=str(sp.audio_path), analysis=sp.analysis_slug)
            else:
                for fname in _COMPONENT_FILES.get(comp, []):
                    srcf = sp.folder / fname
                    if srcf.is_file():
                        _shutil.copy2(srcf, dst / fname)
    return {"ok": True, "slug": slug, "name": new_name}


def _h_get_fixture_pan_tilt(session, params):
    """get_fixture_pan_tilt(fixture_id?) → {ok, fixtures: [{fixture_id, pan, tilt}]}

    Devuelve pan/tilt de todos los movers (o del fixture_id indicado) en el instante actual.
    Valores 0..1 (normalizado). Útil para el preview 2D en la UI.
    """
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
    from uuid import uuid4

    from src.core.timeline_model import CueEntry
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
            _log.error(f"[export_video] error: {e}")
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


# ── J1 — Editor de patch visual 2D ───────────────────────────────────────────

# Escenario 3D (coincide con session.sync_rig_layout → layout["stage"]).
# El Patch 2D (patch_x/patch_y ∈ 0..1) mapea al plano del suelo del escenario:
#   x_mundo = (patch_x - 0.5) * STAGE_W   ;   z_mundo = (patch_y - 0.5) * STAGE_D
# La ALTURA (position.y) NO se toca aquí: solo se edita desde el panel 3D.
STAGE_W = 12.0
STAGE_D = 6.0


def _update_layout_floor(proj, fixture_id, x, z):
    """Si existe el rig_layout.json K1 (posiciones 3D explícitas que SOBREESCRIBEN
    fx.position en el visor), actualiza x/z de este fixture preservando su altura
    (y) y rotación. Así el visor 3D refleja el arrastre del Patch 2D aunque haya
    override K1. No-op si no hay archivo K1."""
    if proj is None:
        return
    import json as _json
    lf = getattr(proj, "rig_layout_file", None)
    if lf is None or not lf.is_file():
        return
    try:
        with open(lf, encoding="utf-8") as f:
            data = _json.load(f)
        fixtures = data.get("fixtures", [])
        ent = next((e for e in fixtures if e.get("id") == fixture_id), None)
        if ent is None:
            fixtures.append({"id": fixture_id, "x": x, "y": 0.0, "z": z,
                             "rx": 0.0, "ry": 0.0, "rz": 0.0})
        else:
            ent["x"] = x
            ent["z"] = z
        data["fixtures"] = fixtures
        tmp = lf.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(data, f, indent=2)
        tmp.replace(lf)
    except Exception:
        pass


def _h_move_fixture(session, params):
    """move_fixture(fixture_id, x, y) → {ok, fixture}.

    Mueve el fixture en el canvas 2D de patch. x/y normalizados 0.0..1.0.
    Persiste el rig a disco (project/rig.json). Devuelve el fixture actualizado
    (Invariante I3: actualización optimista en el UI).

    Acepta también position=[x,y,z] (legado bridge) para compatibilidad.
    En ese caso actualiza también fx.position y guarda patch_x/patch_y como la
    proyección XZ normalizada (0.5 si sólo hay un fixture).
    """
    fixture_id = params.get("fixture_id")
    if not fixture_id:
        return {"ok": False, "error": "fixture_id requerido"}
    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}
    fx = rig.by_id(fixture_id)
    if fx is None:
        return {"ok": False, "error": f"Fixture no encontrado: {fixture_id}"}

    if "x" in params and "y" in params:
        px = max(0.0, min(1.0, float(params["x"])))
        py = max(0.0, min(1.0, float(params["y"])))
        fx.patch_x, fx.patch_y = px, py
        # Acoplar al 3D: el plano del suelo (x,z) sigue al Patch 2D; la ALTURA
        # (position.y) se preserva (solo se edita desde el panel 3D).
        oy = fx.position[1] if (fx.position and len(fx.position) > 1) else 0.0
        fx.position = ((px - 0.5) * STAGE_W, oy, (py - 0.5) * STAGE_D)
        _update_layout_floor(getattr(session, "project", None),
                             fixture_id, fx.position[0], fx.position[2])
    elif "position" in params:
        # Path legado (puente MCP): patch_x/patch_y = proyección XZ normalizada
        # sobre el bbox del rig (comportamiento histórico, no se toca).
        pos = list(params["position"])
        fx.position = tuple(float(v) for v in pos[:3])
        all_xs = [f.position[0] for f in rig.fixtures]
        all_zs = [f.position[2] for f in rig.fixtures]
        min_x, max_x = min(all_xs), max(all_xs)
        min_z, max_z = min(all_zs), max(all_zs)
        fx.patch_x = 0.5 if max_x == min_x else (fx.position[0] - min_x) / (max_x - min_x)
        fx.patch_y = 0.5 if max_z == min_z else (fx.position[2] - min_z) / (max_z - min_z)
    else:
        return {"ok": False, "error": "Parámetros requeridos: x/y o position"}

    rig.save(session.project.rig_file)

    return {"ok": True, "fixture": fx.to_dict()}


# ── J3 — Biblioteca GDTF: browser y búsqueda ─────────────────────────────────

_gdtf_cache: dict = {}   # path_str → {name, manufacturer, modes, channel_count, path}


def _gdtf_metadata(gdtf_path) -> dict:
    """Extrae metadatos ligeros de un .gdtf sin cargar el profile completo."""
    from pathlib import Path as _Path
    key = str(gdtf_path)
    if key in _gdtf_cache:
        return _gdtf_cache[key]
    try:
        import pygdtf
        ft = pygdtf.FixtureType(path=str(gdtf_path))
        modes = [m.name or "(unnamed)" for m in ft.dmx_modes]
        # Canal count del primer modo
        channel_count = 0
        first_modes = list(ft.dmx_modes)
        if first_modes:
            chs = list(getattr(first_modes[0], "_dmx_channels", None) or
                       getattr(first_modes[0], "dmx_channels", None) or [])
            offsets = []
            for ch in chs:
                offs = getattr(ch, "offset", None) or []
                if offs:
                    offsets.extend(offs)
            channel_count = max(offsets) if offsets else 0
        meta = {
            "name": ft.name or _Path(gdtf_path).stem,
            "manufacturer": getattr(ft, "manufacturer", "") or "",
            "modes": modes,
            "channel_count": channel_count,
            "path": str(gdtf_path),
        }
    except Exception as e:
        meta = {
            "name": _Path(gdtf_path).stem,
            "manufacturer": "",
            "modes": [],
            "channel_count": 0,
            "path": str(gdtf_path),
            "_error": str(e),
        }
    _gdtf_cache[key] = meta
    return meta


def _h_list_gdtf_profiles(session, params):
    """list_gdtf_profiles() → {ok, profiles: [{name, manufacturer, modes, channel_count, path}]}.

    Escanea PROFILES_DIR/*.gdtf y devuelve metadatos de cada perfil.
    Caché en memoria (_gdtf_cache) para llamadas repetidas.
    """
    from src._paths import PROFILES_DIR
    profiles = []
    if PROFILES_DIR.is_dir():
        for p in sorted(PROFILES_DIR.glob("*.gdtf")):
            profiles.append(_gdtf_metadata(p))
    return {"ok": True, "profiles": profiles}


def _h_add_fixture_from_gdtf(session, params):
    """add_fixture_from_gdtf(profile_path, universe, start_channel, name="") → {ok, fixture}.

    Carga el GDTF en profile_path, crea un Fixture en el rig y lo persiste.
    profile_path: ruta al .gdtf (relativa a PROFILES_DIR o absoluta).
    Invariante I3: devuelve el fixture creado.
    """
    from pathlib import Path as _Path

    from src._paths import PROFILES_DIR
    from src.core.fixtures import Fixture
    from src.io.loaders.gdtf_profile import load_gdtf_profile

    profile_path = params.get("profile_path")
    universe = int(params.get("universe", 1))
    start_channel = int(params.get("start_channel", 1))
    name = str(params.get("name", "")).strip()
    mode_name = params.get("mode_name")

    if not profile_path:
        return {"ok": False, "error": "profile_path requerido"}

    p = _Path(profile_path)
    if not p.is_absolute():
        p = PROFILES_DIR / p
    if not p.is_file():
        return {"ok": False, "error": f"Perfil GDTF no encontrado: {profile_path}"}

    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}

    try:
        profile = load_gdtf_profile(p, mode_name=mode_name)
    except Exception as e:
        return {"ok": False, "error": f"Error cargando GDTF: {e}"}

    # Generar fixture_id único
    base = (name or profile.name or p.stem).lower().replace(" ", "_").replace("/", "_")
    import re as _re
    base = _re.sub(r"[^a-z0-9_]", "", base)[:30] or "fixture"
    existing_ids = {fx.fixture_id for fx in rig.fixtures}
    fixture_id = base
    counter = 1
    while fixture_id in existing_ids:
        fixture_id = f"{base}_{counter}"
        counter += 1

    fx = Fixture(
        fixture_id=fixture_id,
        profile_id=profile.profile_id,
        universe=universe,
        dmx_start=start_channel,
        label=name or profile.name,
    )
    rig.fixtures.append(fx)
    rig.save(session.project.rig_file)

    return {"ok": True, "fixture": fx.to_dict()}


# ── J2 — Soporte DMX completo por canal ──────────────────────────────────────

_DMX_KINDS = {"dimmer", "rgb", "rgb_par", "moving_head", "strobe", "led_strip", "wled_bar"}


def _h_set_fixture_type(session, params):
    """set_fixture_type(fixture_id, fixture_type) → {ok, fixture}.

    Cambia el kind_override del fixture (dimmer/rgb/moving_head/strobe/led_strip).
    Persiste rig.json. Devuelve el fixture actualizado (I3).
    """
    fixture_id = params.get("fixture_id")
    fixture_type = params.get("fixture_type") or params.get("kind")
    if not fixture_id:
        return {"ok": False, "error": "fixture_id requerido"}
    if not fixture_type or fixture_type not in _DMX_KINDS:
        return {"ok": False, "error": f"fixture_type inválido: {fixture_type!r}. Válidos: {sorted(_DMX_KINDS)}"}
    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}
    fx = rig.by_id(fixture_id)
    if fx is None:
        return {"ok": False, "error": f"Fixture no encontrado: {fixture_id}"}

    fx.kind_override = fixture_type
    rig.save(session.project.rig_file)
    return {"ok": True, "fixture": fx.to_dict()}


# ── E4 — Test de output y patch visual ───────────────────────────────────────

def _h_identify_fixture(session, params):
    """identify_fixture(fixture_id, color=(255,255,255), duration_ms=2000) → {ok}.

    Enciende el fixture al color dado durante duration_ms ms.
    Estado efímero en session._identify (fixture_id → {t_expires, color}).
    Backwards-compatible: sin color → blanco; sin duration_ms → 2000 ms.
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

    # J4: color configurable (r,g,b) 0..255 — por defecto blanco
    raw_color = params.get("color", [255, 255, 255])
    if isinstance(raw_color, (list, tuple)) and len(raw_color) >= 3:
        color = tuple(max(0, min(255, int(v))) for v in raw_color[:3])
    else:
        color = (255, 255, 255)

    t_expires = time.monotonic() + duration_ms / 1000.0
    if not hasattr(session, '_identify'):
        session._identify = {}
    session._identify[fixture_id] = {"t_expires": t_expires, "color": color}

    async def _auto_off():
        await asyncio.sleep(duration_ms / 1000.0)
        if hasattr(session, '_identify'):
            session._identify.pop(fixture_id, None)

    try:
        asyncio.ensure_future(_auto_off())
    except RuntimeError:
        pass  # sin event loop (tests)

    return {"ok": True, "fixture_id": fixture_id, "duration_ms": duration_ms,
            "color": list(color)}


# J4 — Chase automático de fixtures ──────────────────────────────────────────

_CHASE_SEQUENCE = [
    (255, 0, 0),    # rojo
    (0, 255, 0),    # verde
    (0, 0, 255),    # azul
    (255, 255, 255),# blanco
]
_CHASE_STEP_MS = 500


def _h_chase_test(session, params):
    """chase_test(universe) → {ok, chase_id}.

    Cicla rojo→verde→azul→blanco por los fixtures del universo, 500 ms cada color.
    Estado efímero en session._active_chases: {universe: asyncio.Task}.
    """
    import asyncio

    universe = int(params.get("universe", 0))
    if universe < 1:
        return {"ok": False, "error": "universe debe ser >= 1"}

    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}

    fixtures_in_uni = [fx for fx in rig.fixtures if fx.universe == universe]
    if not fixtures_in_uni:
        return {"ok": False, "error": f"No hay fixtures en el universo {universe}"}

    if not hasattr(session, "_active_chases"):
        session._active_chases = {}

    # Cancelar chase anterior en este universo
    prev = session._active_chases.pop(universe, None)
    if prev is not None:
        try:
            prev.cancel()
        except Exception:
            pass

    if not hasattr(session, "_identify"):
        session._identify = {}

    chase_id = f"chase_u{universe}"

    async def _run_chase():
        step = 0
        while True:
            color = _CHASE_SEQUENCE[step % len(_CHASE_SEQUENCE)]
            for fx in fixtures_in_uni:
                import time as _time
                session._identify[fx.fixture_id] = {
                    "t_expires": _time.monotonic() + _CHASE_STEP_MS / 1000.0 + 0.05,
                    "color": color,
                }
            await asyncio.sleep(_CHASE_STEP_MS / 1000.0)
            step += 1

    try:
        task = asyncio.ensure_future(_run_chase())
        session._active_chases[universe] = task
    except RuntimeError:
        pass  # sin event loop (tests)

    return {"ok": True, "chase_id": chase_id, "universe": universe}


def _h_chase_stop(session, params):
    """chase_stop(universe) → {ok}.

    Cancela el chase activo del universo y apaga sus fixtures.
    """
    universe = int(params.get("universe", 0))
    if universe < 1:
        return {"ok": False, "error": "universe debe ser >= 1"}

    chases = getattr(session, "_active_chases", {})
    task = chases.pop(universe, None)
    if task is not None:
        try:
            task.cancel()
        except Exception:
            pass

    # Apagar identify de todos los fixtures del universo
    rig = getattr(session, "fixture_rig", None)
    if rig is not None and hasattr(session, "_identify"):
        for fx in rig.fixtures:
            if fx.universe == universe:
                session._identify.pop(fx.fixture_id, None)

    return {"ok": True, "universe": universe}


# ── L2 — Webhooks de eventos ─────────────────────────────────────────────────

def _h_webhook_get_config(session, params):
    """webhook_get_config() → {ok, webhooks: [{url, events, secret?}]}."""
    wh = getattr(session, "_webhook_dispatcher", None)
    if wh is None:
        return {"ok": True, "webhooks": []}
    return {"ok": True, "webhooks": wh.get_configs()}


def _h_webhook_set_config(session, params):
    """webhook_set_config(webhooks: list) → {ok}.

    Guarda la lista en output_targets.json (escritura atómica) y recarga
    el dispatcher en memoria.
    """
    import json
    webhooks = params.get("webhooks", [])
    if not isinstance(webhooks, list):
        return {"ok": False, "error": "webhooks debe ser una lista"}

    # Validar entradas básicas + FIX 5: SSRF guard on webhook URLs
    from server.webhooks import _validate_webhook_url
    for entry in webhooks:
        if not isinstance(entry, dict) or "url" not in entry:
            return {"ok": False, "error": "Cada webhook requiere campo 'url'"}
        if "events" not in entry or not isinstance(entry["events"], list):
            return {"ok": False, "error": "Cada webhook requiere campo 'events' (lista)"}
        try:
            _validate_webhook_url(entry["url"])
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    # Actualizar dispatcher en memoria
    wh = getattr(session, "_webhook_dispatcher", None)
    if wh is not None:
        wh.set_configs(webhooks)

    # Persistir en output_targets.json (atómico)
    from src._paths import PROJECT_DIR
    targets_file = PROJECT_DIR / "output_targets.json"
    if targets_file.is_file():
        try:
            with open(targets_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}
    data["webhooks"] = webhooks
    tmp = targets_file.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(targets_file)
    except Exception as e:
        return {"ok": False, "error": f"Error guardando config: {e}"}

    return {"ok": True, "count": len(webhooks)}


# ── K1 — Viewer 3D: posicionamiento de fixtures ──────────────────────────────

def _h_get_rig_layout(session, params):
    """get_rig_layout() → {ok, fixtures: [{id, x, y, z, rx, ry, rz}]}.

    Lee el archivo rig_layout.json del proyecto activo (posiciones 3D explícitas).
    Si el archivo no existe, devuelve lista vacía.
    """
    import json
    proj = getattr(session, "project", None)
    if proj is None:
        return {"ok": True, "fixtures": []}
    layout_file = proj.rig_layout_file
    if not layout_file.is_file():
        return {"ok": True, "fixtures": []}
    try:
        with open(layout_file, encoding="utf-8") as f:
            data = json.load(f)
        return {"ok": True, "fixtures": data.get("fixtures", [])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _h_set_fixture_3d(session, params):
    """set_fixture_3d(fixture_id, x, y, z, rx?, ry?, rz?) → {ok, fixture}.

    Guarda la posición 3D del fixture en el rig_layout.json del proyecto.
    Coordenadas en metros (espacio de escenario), rotación en grados (euler XYZ).
    Escribe atómicamente (.tmp → replace). Actualiza el viewer vía sync_rig_layout.
    """
    import json
    fixture_id = require_key(params, "fixture_id")
    try:
        x = float(params.get("x", 0.0))
        y = float(params.get("y", 4.0))
        z = float(params.get("z", 0.0))
        rx = float(params.get("rx", 0.0))
        ry = float(params.get("ry", 0.0))
        rz = float(params.get("rz", 0.0))
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": f"Coordenada inválida: {e}"}

    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": False, "error": "rig no disponible"}
    fx = next((f for f in rig.fixtures if f.fixture_id == fixture_id), None)
    if fx is None:
        return {"ok": False, "error": f"fixture_id no encontrado: {fixture_id!r}"}

    proj = getattr(session, "project", None)
    if proj is None:
        return {"ok": False, "error": "proyecto no disponible"}

    layout_file = proj.rig_layout_file
    # Leer existente o empezar vacío
    if layout_file.is_file():
        try:
            with open(layout_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"fixtures": []}
    else:
        data = {"fixtures": []}

    # Actualizar o insertar
    entry = {"id": fixture_id, "x": x, "y": y, "z": z, "rx": rx, "ry": ry, "rz": rz}
    fixtures_list = data.get("fixtures", [])
    idx = next((i for i, e in enumerate(fixtures_list) if e.get("id") == fixture_id), None)
    if idx is not None:
        fixtures_list[idx] = entry
    else:
        fixtures_list.append(entry)
    data["fixtures"] = fixtures_list

    # Escritura atómica
    tmp = layout_file.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(layout_file)
    except Exception as e:
        return {"ok": False, "error": f"Error guardando rig_layout.json: {e}"}

    # Acople inverso: x/z afectan también al Patch 2D (la altura y, solo 3D).
    fx.position = (x, y, z)
    fx.patch_x = max(0.0, min(1.0, x / STAGE_W + 0.5))
    fx.patch_y = max(0.0, min(1.0, z / STAGE_D + 0.5))
    try:
        rig.save(proj.rig_file)
    except Exception:
        pass

    # Regenerar viewer layout (merge automático de posiciones K1)
    try:
        session.sync_rig_layout()
    except Exception:
        pass

    return {"ok": True, "fixture": fx.to_dict()}


# ── K2 — Pixel mapping imagen/vídeo → LEDs ───────────────────────────────────

def _h_set_clip_pixel_map(session, params):
    """set_clip_pixel_map(clip_id, source_path, x?, y?, width?, height?,
                          fit_mode?, speed?) → {ok, clip}.

    Actualiza los params de un clip para que use PixelMapEffect (id=1010).
    Sobrescribe parcialmente los params: solo los campos proporcionados se
    actualizan; el resto se conserva de los params actuales del clip.
    """
    clip_id = require_key(params, "clip_id")
    clip = session.find_clip_by_id(clip_id)
    if clip is None:
        return {"ok": False, "error": f"clip_id no encontrado: {clip_id!r}"}

    source_path = params.get("source_path", "")
    updates = {"source_path": str(source_path)}
    for k in ("x", "y", "width", "height"):
        if k in params:
            try:
                updates[k] = int(params[k])
            except (TypeError, ValueError):
                return {"ok": False, "error": f"Parámetro inválido: {k}"}
    if "fit_mode" in params:
        fm = str(params["fit_mode"])
        if fm not in ("stretch", "crop", "tile"):
            return {"ok": False, "error": "fit_mode debe ser stretch, crop o tile"}
        updates["fit_mode"] = fm
    if "speed" in params:
        try:
            updates["speed"] = float(params["speed"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "speed inválido"}

    clip.params = {**clip.params, **updates}
    # Asignar PixelMapEffect como efecto del clip
    clip.effect_id = 1010
    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


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


# ── M1 — Tap BPM + key detection ─────────────────────────────────────────────

def _h_tap_bpm(session, params):
    """tap_bpm() → {bpm, taps, ready}.
    Registra un tap de tempo; tras 4+ taps calcula BPM por mediana.
    """
    import time as _time
    ts = getattr(session, "tempo_sync", None)
    if ts is None:
        return {"ok": False, "error": "TempoSyncService no disponible"}
    result = ts.tap(_time.perf_counter())
    result["ok"] = True
    return result


def _h_get_key_info(session, params):
    """get_key_info() → {ok, status, key?, mode?, confidence?}.
    Si ya calculado → devuelve desde caché. Si no → lanza en executor
    y devuelve {status: 'computing'}. El resultado llegará como evento del stream.
    """
    cache = getattr(session, "_key_cache", None)
    if cache is not None:
        return {"ok": True, "status": "ready", **cache}

    # Lanzar detección en executor (no bloquea el event loop)
    import asyncio
    import concurrent.futures

    audio_path = getattr(session, "audio_path", None) or ""
    if not audio_path:
        return {"ok": False, "error": "No hay audio cargado"}

    loop = asyncio.get_event_loop()
    hub = getattr(session, "hub", None)

    def _detect_and_cache():
        from server.key_detector import detect_key
        result = detect_key(audio_path)
        session._key_cache = result
        if hub is not None:
            import asyncio as _aio
            try:
                _aio.run_coroutine_threadsafe(
                    hub.broadcast_json({"type": "key_detected", **result}),
                    loop,
                )
            except Exception:
                pass

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    loop.run_in_executor(executor, _detect_and_cache)
    return {"ok": True, "status": "computing"}


# ── M2 — Generación automática de show ───────────────────────────────────────

def _h_generate_show(session, params):
    """generate_show(style?, density?, replace?) → {ok, clips_created: int}.

    Genera clips automáticamente desde el análisis de audio. Sin IA externa.
    Toma snapshot antes de mutar (deshaciable con Ctrl+Z) — I1.
    Corre en executor si los datos son voluminosos — I6.
    """
    from server.show_generator import STYLES, generate_show

    style = params.get("style", "club")
    if style not in STYLES:
        return {"ok": False, "error": f"style debe ser uno de {STYLES}"}
    density = float(params.get("density", 0.5))
    density = max(0.0, min(1.0, density))
    replace = bool(params.get("replace", False))

    # Obtener datos de análisis
    analysis = getattr(session, "analysis", None)
    if analysis is None:
        return {"ok": False, "error": "No hay análisis disponible para este show"}

    try:
        beats = analysis.list_beats()
        downbeats = analysis.list_downbeats()
        sections = analysis.list_sections()
    except Exception as e:
        return {"ok": False, "error": f"Error leyendo análisis: {e}"}

    if not beats and not downbeats:
        return {"ok": False, "error": "El análisis no tiene beats detectados"}

    bpm = getattr(session, "bpm", None) or 120.0

    # I1: snapshot para undo
    try:
        session.snapshot()
    except Exception:
        pass

    # Limpiar timeline si replace=True
    if replace:
        session.timeline.clips.clear()

    # Generar clips
    new_clips = generate_show(beats, downbeats, sections, style, density, bpm)

    # Añadir clips al timeline
    from src.core.timeline_model import Clip
    for cd in new_clips:
        clip = Clip(
            track=cd["track"],
            start_ms=cd["start_ms"],
            end_ms=cd["end_ms"],
            effect_id=cd["effect_id"],
            scope=cd.get("scope", "per_bar"),
            params=cd.get("params", {}),
            color=cd.get("color", "#3a7acc"),
            label=cd.get("label", "GEN"),
            layer=cd.get("layer", 0),
            uid=cd.get("uid") or None,
        )
        if cd.get("uid"):
            clip.uid = cd["uid"]
        session.timeline.clips.append(clip)

    session.invalidate_caches()
    return {"ok": True, "clips_created": len(new_clips)}


# ── M3 — Historial de gestos y replay ────────────────────────────────────────

def _h_list_gesture_history(session, params):
    """list_gesture_history(last?: int) → {ok, gestures: [...]}."""
    gl = getattr(session, "_gesture_log", None)
    if gl is None:
        return {"ok": True, "gestures": []}
    last = int(params.get("last", 200))
    return {"ok": True, "gestures": gl.list(last)}


def _h_replay_gesture(session, params):
    """replay_gesture(idx: int) → resultado del handler re-ejecutado."""
    from server.validators import require_int
    idx = require_int(params, "idx")
    gl = getattr(session, "_gesture_log", None)
    if gl is None:
        return {"ok": False, "error": "GestureLog no disponible"}
    entry = gl.get(idx)
    if entry is None:
        return {"ok": False, "error": f"Gesto {idx} no encontrado"}
    handler_name = entry["handler"]
    handler_params = entry.get("params") or {}
    if handler_name in _LOCAL:
        try:
            return _LOCAL[handler_name](session, handler_params)
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": f"Handler {handler_name!r} no re-ejecutable"}


def _h_clear_gesture_history(session, params):
    """clear_gesture_history() → {ok}."""
    gl = getattr(session, "_gesture_log", None)
    if gl is not None:
        gl.clear()
    return {"ok": True}


# ── N1 — Marketplace de plugins ───────────────────────────────────────────────

_DEFAULT_MARKETPLACE_URL = (
    "https://raw.githubusercontent.com/example/sd-plugins/main/manifest.json"
)


def _get_marketplace_url(session) -> str:
    try:
        import json
        from pathlib import Path as _Path
        data = json.loads(_Path("output_targets.json").read_text("utf-8"))
        return data.get("marketplace_url", _DEFAULT_MARKETPLACE_URL)
    except Exception:
        return _DEFAULT_MARKETPLACE_URL


async def _h_list_marketplace_plugins(session, params):
    """list_marketplace_plugins() → {ok, plugins: [...], cached: bool}.
    FIX 3: async to avoid blocking the event loop during HTTP fetch."""
    from server.marketplace import fetch_manifest
    url = _get_marketplace_url(session)
    try:
        plugins, cached = await fetch_manifest(url)
        return {"ok": True, "plugins": plugins, "cached": cached}
    except TimeoutError:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _h_install_plugin(session, params):
    """install_plugin(download_url) → {ok, name} or {ok: false, error}.
    FIX 3: async to avoid blocking; FIX 2: URL validated against manifest."""
    from pathlib import Path as _Path

    from server.marketplace import install_plugin
    from server.validators import require_key
    download_url = require_key(params, "download_url")
    plugins_dir = _Path("plugins/effects")
    return await install_plugin(download_url, plugins_dir)


# ── N2 — Backup y restauración de show ───────────────────────────────────────

def _h_export_show_bundle(session, params):
    """export_show_bundle(include_audio?) → {ok, path}."""
    include_audio = bool(params.get("include_audio", False))
    from server.show_bundle import export_show_bundle
    try:
        path = export_show_bundle(session, include_audio=include_audio)
        return {"ok": True, "path": path}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _h_import_show_bundle(session, params):
    """import_show_bundle(zip_path) → {ok, slug, warnings} or {ok: false, error}."""
    from pathlib import Path as _Path

    from server.show_bundle import import_show_bundle
    from server.validators import require_key
    zip_path = require_key(params, "zip_path")
    try:
        slug, warnings = import_show_bundle(zip_path, _Path("projects"))
        return {"ok": True, "slug": slug, "warnings": warnings}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── ROADMAP v4 — Editor completo de fixture ──────────────────────────────────

def _get_artnet_ip_for_universe(universe: int):
    """Deriva la IP Art-Net de un universo leyendo output_targets.json."""
    import json

    from src._paths import PROJECT_DIR
    targets_file = PROJECT_DIR / "output_targets.json"
    if not targets_file.is_file():
        return None
    try:
        data = json.loads(targets_file.read_text("utf-8"))
        entry = data.get(str(universe))
        if isinstance(entry, dict):
            return entry.get("ip")
    except Exception:
        pass
    return None


def _update_rig_layout_height(session, fixture_id: str, height_m: float):
    """Persiste height_m como `y` en rig_layout.json, sin perder x/z existentes."""
    import json
    proj = getattr(session, "project", None)
    if proj is None:
        return
    layout_file = getattr(proj, "rig_layout_file", None)
    if layout_file is None:
        return
    if layout_file.is_file():
        try:
            with open(layout_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"fixtures": []}
    else:
        data = {"fixtures": []}
    fixtures_list = data.get("fixtures", [])
    idx = next((i for i, e in enumerate(fixtures_list) if e.get("id") == fixture_id), None)
    if idx is not None:
        fixtures_list[idx]["y"] = height_m
    else:
        fixtures_list.append({
            "id": fixture_id, "x": 0.0, "y": height_m, "z": 0.0,
            "rx": 0.0, "ry": 0.0, "rz": 0.0,
        })
    data["fixtures"] = fixtures_list
    tmp = layout_file.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(layout_file)
    except Exception:
        pass


def _h_update_fixture(session, params):
    """update_fixture(fixture_id, **fields, dry_run=False) → {ok, fixture?, conflicts}.

    Acepta: name, start_address, universe, mode, kind_override, channel_map,
    notes, patch_x, patch_y, height_m, dry_run.
    dry_run=True: valida conflictos y devuelve {ok, conflicts} SIN persistir.
    dry_run=False con conflicto: devuelve {ok: False, error, conflicts}.
    dry_run=False sin conflicto: persiste, sync_rig_layout si cambia pos/altura,
    snapshot(), devuelve {ok, fixture, conflicts: []}.
    """
    fixture_id = params.get("fixture_id")
    if not fixture_id:
        return {"ok": False, "error": "fixture_id requerido"}
    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}
    fx = rig.by_id(fixture_id)
    if fx is None:
        return {"ok": False, "error": f"Fixture no encontrado: {fixture_id}"}

    dry_run = bool(params.get("dry_run", False))

    # Compute new universe/address for conflict check
    new_universe = int(params["universe"]) if "universe" in params else fx.universe
    new_start = int(params["start_address"]) if "start_address" in params else fx.dmx_start
    prof = rig.get_profile(fx.profile_id)
    num_channels = prof.num_channels if prof else 1

    conflicts = []
    for other in rig.fixtures:
        if other.fixture_id == fixture_id:
            continue
        if other.universe != new_universe:
            continue
        other_prof = rig.get_profile(other.profile_id)
        other_channels = other_prof.num_channels if other_prof else 1
        if (new_start <= other.dmx_start + other_channels - 1
                and other.dmx_start <= new_start + num_channels - 1):
            conflicts.append({
                "fixture_id": other.fixture_id,
                "name": other.label or other.fixture_id,
                "address_range": f"ch {other.dmx_start}-{other.dmx_start + other_channels - 1}",
            })

    if dry_run:
        return {"ok": True, "conflicts": conflicts}

    if conflicts:
        return {"ok": False, "error": "Conflicto DMX detectado", "conflicts": conflicts}

    # I1 — snapshot antes de mutar
    try:
        session.snapshot()
    except Exception:
        pass

    pos_height_changed = False
    if "name" in params:
        fx.label = str(params["name"])
    if "start_address" in params:
        fx.dmx_start = int(params["start_address"])
    if "universe" in params:
        fx.universe = int(params["universe"])
    if "kind_override" in params:
        fx.kind_override = params["kind_override"] or None
    if "mode" in params:
        fx.kind_override = params["mode"] or None
    if "channel_map" in params:
        fx.channel_map = params["channel_map"]
    if "notes" in params:
        fx.notes = params["notes"]
    if "patch_x" in params and params["patch_x"] is not None:
        fx.patch_x = float(params["patch_x"])
        pos_height_changed = True
    if "patch_y" in params and params["patch_y"] is not None:
        fx.patch_y = float(params["patch_y"])
        pos_height_changed = True
    if "height_m" in params and params["height_m"] is not None:
        fx.height_m = float(params["height_m"])
        _update_rig_layout_height(session, fixture_id, fx.height_m)
        pos_height_changed = True

    rig.save(session.project.rig_file)

    if pos_height_changed:
        try:
            session.sync_rig_layout()
        except Exception:
            pass

    try:
        session.notify_changed("rig")
    except Exception:
        pass

    return {"ok": True, "fixture": fx.to_dict(), "conflicts": []}


def _h_get_fixture_detail(session, params):
    """get_fixture_detail(fixture_id) → {ok, fixture: {…, num_channels, artnet_ip, height_m}}."""
    fixture_id = params.get("fixture_id")
    if not fixture_id:
        return {"ok": False, "error": "fixture_id requerido"}
    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}
    fx = rig.by_id(fixture_id)
    if fx is None:
        return {"ok": False, "error": f"Fixture no encontrado: {fixture_id}"}

    prof = rig.get_profile(fx.profile_id)
    num_channels = prof.num_channels if prof else 0

    artnet_ip = _get_artnet_ip_for_universe(fx.universe)

    # height_m: preferir campo del fixture; fallback a rig_layout.json[y]
    height_m = fx.height_m
    if height_m is None:
        proj = getattr(session, "project", None)
        if proj is not None:
            layout_file = getattr(proj, "rig_layout_file", None)
            if layout_file is not None and layout_file.is_file():
                try:
                    import json
                    with open(layout_file, encoding="utf-8") as f:
                        k1_data = json.load(f)
                    for e in k1_data.get("fixtures", []):
                        if e.get("id") == fixture_id:
                            height_m = float(e.get("y", 0))
                            break
                except Exception:
                    pass

    d = fx.to_dict()
    d["height_m"] = height_m
    d["artnet_ip"] = artnet_ip
    d["num_channels"] = num_channels

    return {"ok": True, "fixture": d}


def _h_list_fixture_types(session, params):
    """list_fixture_types() → {ok, types: [{id, name, modes: [{name, channels}]}]}.

    Combina tipos built-in (dimmer/rgb/moving_head/led_bar) + perfiles GDTF/JSON
    cargados en profiles/.
    """
    from src.core.fixtures import list_available_profiles, load_profile

    types = [
        {"id": "dimmer", "name": "Dimmer",
         "modes": [{"name": "1ch", "channels": 1}]},
        {"id": "rgb", "name": "RGB Par",
         "modes": [{"name": "RGB", "channels": 3}, {"name": "RGBA", "channels": 4}]},
        {"id": "moving_head", "name": "Moving Head",
         "modes": [{"name": "Basic", "channels": 7}, {"name": "Extended", "channels": 15}]},
        {"id": "led_bar", "name": "LED Bar",
         "modes": [{"name": "pixel", "channels": 279}, {"name": "RGB", "channels": 3}]},
    ]
    seen_ids = {t["id"] for t in types}
    for profile_id in list_available_profiles():
        if profile_id in seen_ids:
            continue
        try:
            prof = load_profile(profile_id)
        except Exception:
            prof = None
        if prof:
            types.append({
                "id": profile_id,
                "name": prof.name,
                "modes": [{"name": prof.kind, "channels": prof.num_channels}],
            })
            seen_ids.add(profile_id)
    return {"ok": True, "types": types}


# ── Patch UX: dirección libre, duplicar, mapa de canales, output targets ─────

def _h_next_free_address(session, params):
    """next_free_address(universe, num_channels) → {ok, address: int}.

    Devuelve la primera dirección DMX libre en el universo dado que tenga
    espacio para num_channels canales consecutivos.
    """
    universe = int(params.get("universe", 1))
    num_channels = max(1, int(params.get("num_channels", 1)))
    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": True, "address": 1}

    used: list[tuple[int, int]] = []
    for f in rig.fixtures:
        if f.universe != universe:
            continue
        prof = rig.get_profile(f.profile_id)
        nch = prof.num_channels if prof else 1
        used.append((f.dmx_start, f.dmx_start + nch - 1))
    used.sort()

    addr = 1
    for start, end in used:
        if addr + num_channels - 1 < start:
            break
        if addr <= end:
            addr = end + 1

    if addr + num_channels - 1 > 512:
        return {"ok": False, "error": "Sin espacio libre en el universo"}
    return {"ok": True, "address": addr}


def _h_duplicate_fixture(session, params):
    """duplicate_fixture(fixture_id) → {ok, fixture}.

    Clona el fixture dado con un nuevo ID y la primera dirección libre
    en el mismo universo. patch_x/patch_y se dejan a None para que
    aparezca en posición por defecto en el canvas.
    """
    fixture_id = params.get("fixture_id")
    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}
    fx = rig.by_id(fixture_id)
    if fx is None:
        return {"ok": False, "error": f"Fixture no encontrado: {fixture_id}"}

    prof = rig.get_profile(fx.profile_id)
    num_channels = prof.num_channels if prof else 1

    res = _h_next_free_address(session, {"universe": fx.universe, "num_channels": num_channels})
    if not res.get("ok"):
        return res

    import time
    from dataclasses import replace
    base = fx.fixture_id.rstrip("0123456789").rstrip("_")
    new_id = f"{base}_{int(time.time() * 1000) % 100000}"
    while rig.by_id(new_id):
        new_id = f"{base}_{int(time.time() * 1000 + 1) % 100000}"

    new_fx = replace(
        fx,
        fixture_id=new_id,
        dmx_start=res["address"],
        label=f"{fx.label or fx.fixture_id} (copia)",
        patch_x=None,
        patch_y=None,
    )

    try:
        session.snapshot()
    except Exception:
        pass
    rig.fixtures.append(new_fx)
    rig.save(session.project.rig_file)
    try:
        session.notify_changed("rig")
    except Exception:
        pass
    return {"ok": True, "fixture": new_fx.to_dict()}


def _h_get_universe_channel_map(session, params):
    """get_universe_channel_map() → {ok, universes: {str(u): [{fixture_id, label, start, end, num_channels}]}}.

    Devuelve los rangos de canales usados por universo, ordenados por start.
    """
    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": True, "universes": {}}

    by_universe: dict[int, list] = {}
    for fx in rig.fixtures:
        u = fx.universe
        prof = rig.get_profile(fx.profile_id)
        nch = prof.num_channels if prof else 1
        by_universe.setdefault(u, []).append({
            "fixture_id": fx.fixture_id,
            "label": fx.label or fx.fixture_id,
            "start": fx.dmx_start,
            "end": fx.dmx_start + nch - 1,
            "num_channels": nch,
        })

    for u in by_universe:
        by_universe[u].sort(key=lambda x: x["start"])

    return {"ok": True, "universes": {str(u): v for u, v in by_universe.items()}}


def _h_get_output_targets(session, params):
    """get_output_targets() → {ok, targets: {str(universe): {type, ip?}}}.

    Lee output_targets.json y devuelve las entradas numéricas (universos).
    """
    import json
    from pathlib import Path
    _ot = Path(__file__).resolve().parent.parent / "output_targets.json"
    try:
        if _ot.is_file():
            raw = json.loads(_ot.read_text(encoding="utf-8"))
            targets = {k: v for k, v in raw.items() if k.isdigit() and isinstance(v, dict)}
            return {"ok": True, "targets": targets}
    except Exception:
        pass
    return {"ok": True, "targets": {}}


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
    # Menú de gestión de proyectos: galería + componentes + crear/copiar
    "list_projects_detailed": _h_list_projects_detailed,
    "list_components": _h_list_components,
    "apply_rig": _h_apply_rig,
    "load_sequence": _h_load_sequence,
    "apply_presets": _h_apply_presets,
    "apply_autovj": _h_apply_autovj,
    "apply_song": _h_apply_song,
    "update_project": _h_update_project,
    "list_available_analyses": _h_list_available_analyses,
    "create_project_from_components": _h_create_project_from_components,
    "duplicate_project": _h_duplicate_project,
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
    # J3 — Biblioteca GDTF: browser y búsqueda
    "list_gdtf_profiles": _h_list_gdtf_profiles,
    "add_fixture_from_gdtf": _h_add_fixture_from_gdtf,
    # J1 — Editor de patch visual 2D
    "move_fixture": _h_move_fixture,
    # J2 — Soporte DMX completo por canal
    "set_fixture_type": _h_set_fixture_type,
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
    # J4 — Chase test de fixtures
    "chase_test": _h_chase_test,
    "chase_stop": _h_chase_stop,
    # L2 — Webhooks de eventos
    "webhook_get_config": _h_webhook_get_config,
    "webhook_set_config": _h_webhook_set_config,
    # K1 — Viewer 3D: posicionamiento de fixtures
    "get_rig_layout": _h_get_rig_layout,
    "set_fixture_3d": _h_set_fixture_3d,
    # K2 — Pixel mapping imagen/vídeo
    "set_clip_pixel_map": _h_set_clip_pixel_map,
    # F2 — Plugin UI auto-generada (ROADMAP v3)
    "get_effect_schema": _h_get_effect_schema,
    # F4 — Live preview en el inspector (ROADMAP v3)
    "preview_effect_frame": _h_preview_effect_frame,
    # L3 — Multiusuario: rol del token actual
    "auth_get_role": lambda session, params: {"ok": True, "role": "operator"},
    # M1 — Tap BPM + key detection
    "tap_bpm": _h_tap_bpm,
    "get_key_info": _h_get_key_info,
    # M2 — Generación automática de show
    "generate_show": _h_generate_show,
    # M3 — Historial de gestos
    "list_gesture_history": _h_list_gesture_history,
    "replay_gesture": _h_replay_gesture,
    "clear_gesture_history": _h_clear_gesture_history,
    # N1 — Marketplace de plugins
    "list_marketplace_plugins": _h_list_marketplace_plugins,
    "install_plugin": _h_install_plugin,
    # N2 — Backup y restauración de show
    "export_show_bundle": _h_export_show_bundle,
    "import_show_bundle": _h_import_show_bundle,
    # ROADMAP v4 — Editor completo de fixture
    "update_fixture": _h_update_fixture,
    "get_fixture_detail": _h_get_fixture_detail,
    "list_fixture_types": _h_list_fixture_types,
    # Patch UX — dirección libre, duplicar, mapa de canales, output targets
    "next_free_address": _h_next_free_address,
    "duplicate_fixture": _h_duplicate_fixture,
    "get_universe_channel_map": _h_get_universe_channel_map,
    "get_output_targets": _h_get_output_targets,
}


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
