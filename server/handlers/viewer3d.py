"""
handlers/viewer3d.py — K1: posicionamiento 3D de fixtures (rig_layout) (ADR-005).
"""
from __future__ import annotations

from server.handlers.patch_visual import STAGE_D, STAGE_W
from server.validators import require_key

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


HANDLERS = {
    "get_rig_layout": _h_get_rig_layout,
    "set_fixture_3d": _h_set_fixture_3d,
}
