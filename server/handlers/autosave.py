"""
handlers/autosave.py — B4: autosave + versiones de show (ADR-005).
"""
from __future__ import annotations

from server.validators import ValidationError, require_key

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


HANDLERS = {
    "list_autosaves": _h_list_autosaves,
    "restore_autosave": _h_restore_autosave,
    "discard_autosave_prompt": _h_discard_autosave_prompt,
}
