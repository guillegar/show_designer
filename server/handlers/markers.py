"""
handlers/markers.py — I2 marcadores de timeline + I3 clips por grupo (ADR-005).
"""
from __future__ import annotations

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

HANDLERS = {
    "list_markers": _h_list_markers,
    "add_marker": _h_add_marker,
    "delete_marker": _h_delete_marker,
    "update_marker": _h_update_marker,
    "get_group_clips": _h_get_group_clips,
}
# La declaración de mutador vive junto al handler (ADR-005):
TIMELINE_MUTATORS = {"add_marker", "delete_marker", "update_marker"}
