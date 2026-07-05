"""
handlers/patch.py — Editor completo de fixture (ROADMAP v4) + Patch UX (ADR-005):
update/detail/tipos de fixture, dirección DMX libre, duplicar, mapa de canales
por universo y destinos de salida.
"""
from __future__ import annotations

import json

from src._paths import PROJECT_DIR

# ── ROADMAP v4 — Editor completo de fixture ──────────────────────────────────

def _get_artnet_ip_for_universe(universe: int):
    """Deriva la IP Art-Net de un universo leyendo output_targets.json."""

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
    notes, patch_x, patch_y, height_m, target_ip, rotation_y, dry_run.
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
    if "target_ip" in params:
        ip = (params["target_ip"] or "").strip() or None
        fx.target_ip = ip
    if "rotation_y" in params and params["rotation_y"] is not None:
        rx, _ry, rz = fx.rotation
        fx.rotation = (rx, float(params["rotation_y"]), rz)
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
    # OJO (ADR-005): anclado a PROJECT_DIR — Path(__file__).parent.parent dejó de
    # apuntar a la raíz al mover este código un nivel más adentro.
    _ot = PROJECT_DIR / "output_targets.json"
    try:
        if _ot.is_file():
            raw = json.loads(_ot.read_text(encoding="utf-8"))
            targets = {k: v for k, v in raw.items() if k.isdigit() and isinstance(v, dict)}
            return {"ok": True, "targets": targets}
    except Exception:
        pass
    return {"ok": True, "targets": {}}

HANDLERS = {
    "update_fixture": _h_update_fixture,
    "get_fixture_detail": _h_get_fixture_detail,
    "list_fixture_types": _h_list_fixture_types,
    "next_free_address": _h_next_free_address,
    "duplicate_fixture": _h_duplicate_fixture,
    "get_universe_channel_map": _h_get_universe_channel_map,
    "get_output_targets": _h_get_output_targets,
}
RIG_MUTATORS = {"update_fixture", "duplicate_fixture"}
