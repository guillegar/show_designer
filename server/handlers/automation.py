"""
handlers/automation.py — A2 lanes de automatización + A1 param links y fuentes de modulación (ADR-005).
"""
from __future__ import annotations

from server.validators import ValidationError, require_key


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


HANDLERS = {
    "add_automation_lane": _h_add_automation_lane,
    "delete_automation_lane": _h_delete_automation_lane,
    "set_automation_points": _h_set_automation_points,
    "list_automation_lanes": _h_list_automation_lanes,
    "set_clip_param_links": _h_set_clip_param_links,
    "list_modulation_sources": _h_list_modulation_sources,
}
