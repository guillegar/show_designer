"""
exporters.py — Template reutilizable para exporters que usan tempfiles.

Elimina duplicación en _h_export_csv y _h_export_qlc (dispatcher.py).
"""
from __future__ import annotations

import os
import tempfile
from typing import Callable


def export_to_memory(
    session,
    exporter_func: Callable,
    suffix: str,
    filename_template: str,
) -> dict:
    """
    Patrón común: exporter func → tempfile → read UTF-8 → cleanup → JSON response.

    Args:
        session: ShowSession (expone .project.slug y .timeline / .fixture_rig)
        exporter_func: callable(session, path) que escribe el archivo temporal
        suffix: extensión de tempfile (ej ".csv" o ".qxw")
        filename_template: template con placeholder {slug} (ej "{slug}_clips.csv")

    Returns:
        {"ok": True, "filename": ..., "content": ...} si éxito
        {"ok": False, "error": ...} si falla
    """
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        exporter_func(session, path)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        filename = filename_template.format(slug=session.project.slug)
        return {"ok": True, "filename": filename, "content": content}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
