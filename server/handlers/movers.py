"""
handlers/movers.py — G3 channel effects de movers + G4 DMX USB/output targets + pan/tilt (ADR-005).
"""
from __future__ import annotations

from server.validators import require_key

# ── G3 — Moving heads: pan/tilt en el timeline ──────────────────────────────

def _h_list_channel_effects(session, params):
    """list_channel_effects() → {ok, effects: [{effect_id, name, category, required_channels, ...}]}"""
    lib = getattr(session, 'channel_lib', None)
    if lib is None:
        return {"ok": True, "effects": []}
    return {"ok": True, "effects": lib.describe_all()}


def _h_set_clip_channel_effect(session, params):
    """set_clip_channel_effect(clip_id, config: {id, params?}) — añade/actualiza un efecto de canal.

    El campo `config.id` es el effect_id del ChannelEffect (ej. "pos_pantilt_wave").
    Si ya existe un entry con el mismo id en clip.channel_effects, lo reemplaza.
    También actualiza legacy channel_effect_id + params del clip para compat con
    fixtures que usan el campo individual.
    """
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}

    cfg = params.get("config")
    if not cfg or not isinstance(cfg, dict):
        return {"ok": False, "error": "config requerido: {id, params?}"}

    eff_id = cfg.get("id") or cfg.get("effect_id")
    if not eff_id:
        return {"ok": False, "error": "config.id requerido"}

    # Verificar que el efecto existe
    lib = getattr(session, 'channel_lib', None)
    if lib is not None and lib.get(str(eff_id)) is None:
        return {"ok": False, "error": f"channel_effect '{eff_id}' no encontrado"}

    eff_params = dict(cfg.get("params") or {})
    entry = {"id": str(eff_id), "params": eff_params}

    # Upsert en la lista channel_effects del clip
    existing = list(getattr(clip, 'channel_effects', []) or [])
    replaced = False
    for i, e in enumerate(existing):
        if e.get("id") == str(eff_id):
            existing[i] = entry
            replaced = True
            break
    if not replaced:
        existing.append(entry)
    clip.channel_effects = existing

    # También actualizar el campo legacy para compat con show_engine legacy path
    clip.channel_effect_id = str(eff_id)
    clip.params = {**clip.params, **eff_params}

    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


def _h_delete_clip_channel_effect(session, params):
    """delete_clip_channel_effect(clip_id, channel_name_or_id) — elimina un efecto de canal.

    Elimina la entrada cuyo id == channel_name_or_id, O que controla el canal channel_name_or_id.
    """
    clip = session.find_clip_by_id(require_key(params, "clip_id"))
    if clip is None:
        return {"ok": False, "error": "clip_id no encontrado"}

    target = require_key(params, "channel_name_or_id")
    existing = list(getattr(clip, 'channel_effects', []) or [])

    before = len(existing)
    # Eliminar por id directo
    existing = [e for e in existing if e.get("id") != target]
    if len(existing) == before:
        # Buscar si algún efecto produce el canal pedido
        lib = getattr(session, 'channel_lib', None)
        if lib is not None:
            existing = [e for e in existing
                        if target not in (lib.get(e.get("id", "")) or type('', (), {'required_channels': [], 'optional_channels': []})()).required_channels]

    clip.channel_effects = existing
    if not existing:
        clip.channel_effect_id = None

    session.invalidate_caches()
    return {"ok": True, "clip": clip.to_dict()}


def _h_list_dmx_ports(session, params):
    """list_dmx_ports() → {ok, ports: [str]} — lista puertos serie para DMX USB."""
    from src.io.outputs.router import DmxUsbTarget
    return {"ok": True, "ports": DmxUsbTarget.list_ports()}


def _h_set_output_target(session, params):
    """set_output_target(universe, type, port?, ip?, multicast?) → {ok}.

    Actualiza output_targets.json para el universo indicado y recarga el router
    en el engine de la sesión. Soporta type: wled, artnet_node, sacn, dmx_usb, sim_only.
    """
    import json

    from src._paths import PROJECT_DIR

    uni = int(params.get("universe", 1))
    ttype = str(params.get("type", "sim_only"))

    cfg: dict = {"type": ttype}
    if ttype in ("wled", "artnet_node", "sacn"):
        ip = params.get("ip") or params.get("port") or ""
        if ip:
            cfg["ip"] = ip
        if ttype == "sacn":
            if params.get("multicast"):
                cfg["multicast"] = True
    elif ttype == "dmx_usb":
        port = params.get("port") or "COM3"
        cfg["port"] = port

    # OJO (ADR-005): anclado a PROJECT_DIR — Path(__file__).parent.parent dejó de
    # apuntar a la raíz al mover este código un nivel más adentro.
    _ot = PROJECT_DIR / "output_targets.json"
    try:
        data: dict = {}
        if _ot.is_file():
            data = json.loads(_ot.read_text(encoding="utf-8"))
        data[str(uni)] = cfg
        tmp = _ot.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_ot)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Recargar router en el engine
    se = getattr(session, "show_engine", None)
    if se is not None:
        try:
            from src.io.outputs.router import OutputRouter
            new_router = OutputRouter.load(_ot)
            if hasattr(se, "router") and se.router is not None:
                se.router.close()
            se.router = new_router
        except Exception as e:
            return {"ok": True, "warn": f"config guardada pero router no recargado: {e}"}

    return {"ok": True, "universe": uni, "target": cfg}


def _h_get_fixture_pan_tilt(session, params):
    """get_fixture_pan_tilt(fixture_id?) → {ok, fixtures: [{fixture_id, pan, tilt}]}

    Devuelve pan/tilt de todos los movers (o del fixture_id indicado) en el instante actual.
    Valores 0..1 (normalizado). Útil para el preview 2D en la UI.
    """
    t = session.t if hasattr(session, 't') else 0.0
    actx = session._cached_actx if hasattr(session, '_cached_actx') else {}

    se = getattr(session, 'show_engine', None)
    tl = getattr(session, 'timeline', None)
    if se is None or tl is None or se.rig is None:
        return {"ok": True, "fixtures": []}

    fid_filter = params.get("fixture_id")
    result = []
    for fx in se.rig.all_fixtures():
        if fid_filter is not None and str(fx.fixture_id) != str(fid_filter):
            continue
        profile = se.rig.get_profile(fx.profile_id)
        if profile is None or 'pan' not in profile.channel_map:
            continue
        buf = se.render_channels_for_fixture(fx, t, actx, timeline=tl)
        ch_pan  = profile.channel_map.get('pan', -1)
        ch_tilt = profile.channel_map.get('tilt', -1)
        pan_v  = buf[ch_pan]  / 255.0 if 0 <= ch_pan  < len(buf) else 0.5
        tilt_v = buf[ch_tilt] / 255.0 if 0 <= ch_tilt < len(buf) else 0.5
        result.append({"fixture_id": fx.fixture_id, "pan": round(pan_v, 4), "tilt": round(tilt_v, 4)})

    return {"ok": True, "fixtures": result}


HANDLERS = {
    "list_channel_effects": _h_list_channel_effects,
    "set_clip_channel_effect": _h_set_clip_channel_effect,
    "delete_clip_channel_effect": _h_delete_clip_channel_effect,
    "get_fixture_pan_tilt": _h_get_fixture_pan_tilt,
    "list_dmx_ports": _h_list_dmx_ports,
    "set_output_target": _h_set_output_target,
}
