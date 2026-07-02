"""
handlers/pixelmap.py — K2: pixel mapping imagen/vídeo → LEDs (ADR-005).
"""
from __future__ import annotations

from server.validators import require_key

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


HANDLERS = {
    "set_clip_pixel_map": _h_set_clip_pixel_map,
}
