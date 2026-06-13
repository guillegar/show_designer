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
    "set_clip_preset",
    "generate_section", "mirror_clips_lr", "apply_palette_to_range", "load_show",
    # A3 — mutadores de patterns/instances (el snapshot se hace dentro del handler,
    # no en el dispatcher, porque necesitan snapshotear ANTES de resolver lookup)
    # create_pattern_from_clips y los demás llaman session.snapshot() internamente.
}

# Métodos que mutan el rig de fixtures → regenerar rig_layout.json para el visor 3D
# (si no, el visor muestra posiciones obsoletas tras mover/editar fixtures en Patch).
_RIG_MUTATORS = {
    "move_fixture", "set_fixture_property", "add_fixture", "delete_fixture",
    "save_rig", "load_show",
}


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
    c.params = dict(p.params)
    c.color = p.color
    c.label = p.name
    c.preset_id = p.preset_id
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
    return {"presets": [p.to_dict() for p in session.presets.list()]}


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


_LOCAL = {
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
    # A5 — Ergonomía
    "duplicate_range": _h_duplicate_range,
    # B1 — Waveform
    "get_waveform": _h_get_waveform,
    # B2 — Mixer
    "set_track_chain": _h_set_track_chain,
    "set_master": _h_set_master,
    "get_mixer": _h_get_mixer,
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
