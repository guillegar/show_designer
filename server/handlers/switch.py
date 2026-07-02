"""
handlers/switch.py — H3: multi-show quick-switch (ADR-005).
"""
from __future__ import annotations

import asyncio

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
    slug = str(params.get("slug", ""))
    if not slug:
        return {"ok": False, "error": "slug requerido"}
    pm = getattr(session, "pm", None) or getattr(session, "_pm", None)
    if pm is not None and pm.open_project(slug) is None:
        return {"ok": False, "error": f"Proyecto no encontrado: {slug!r}"}
    asyncio.create_task(session.switch_project(slug))
    return {"ok": True, "slug": slug}


HANDLERS = {
    "list_projects": _h_list_projects,
    "switch_project": _h_switch_project,
}
