"""
handlers/patch_visual.py — J1 editor de patch 2D (move_fixture) + J2 tipo DMX por fixture (ADR-005).
"""
from __future__ import annotations

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


HANDLERS = {
    "move_fixture": _h_move_fixture,
    "set_fixture_type": _h_set_fixture_type,
}
# La declaración de mutador vive junto al handler (ADR-005):
RIG_MUTATORS = {"move_fixture"}
