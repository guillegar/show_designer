"""
handlers/autovj.py — D1 auto-VJ por reglas + D2 análisis en vivo (entrada de audio) (ADR-005).
"""
from __future__ import annotations

from server.validators import ValidationError, require_int, require_key

# ── D1 — Auto-VJ por reglas ─────────────────────────────────────────────────

def _h_autovj_get_state(session, params):
    """autovj_get_state() → {ok, ruleset|null, presets: [{uid, name, rules}]}.

    Estado completo del motor AutoVJ: ruleset activo + presets disponibles.
    """
    from src.core.autovj import PRESETS
    ruleset = session.autovj_engine.ruleset
    return {
        "ok": True,
        "ruleset": ruleset.to_dict() if ruleset is not None else None,
        "presets": [
            {"uid": p.uid, "name": p.name, "rules": len(p.rules)}
            for p in PRESETS.values()
        ],
    }


def _h_autovj_set_ruleset(session, params):
    """autovj_set_ruleset(ruleset|null) → {ok, ruleset|null}.

    Reemplaza el ruleset activo. Pasar null desactiva el AutoVJ.
    """
    from src.core.autovj import RuleSet
    ruleset_dict = params.get("ruleset")
    if ruleset_dict is None:
        session.autovj_engine.ruleset = None
        return {"ok": True, "ruleset": None}
    try:
        rs = RuleSet.from_dict(ruleset_dict)
        session.autovj_engine.ruleset = rs
        return {"ok": True, "ruleset": rs.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _h_autovj_activate_preset(session, params):
    """autovj_activate_preset(preset_uid) → {ok, ruleset}.

    Carga un preset integrado como ruleset activo (copia fresca, estado
    runtime reseteado).
    """
    from src.core.autovj import PRESETS, RuleSet
    preset_uid = params.get("preset_uid", "")
    preset = PRESETS.get(preset_uid)
    if preset is None:
        return {"ok": False, "error": f"Preset no encontrado: {preset_uid!r}. "
                f"Válidos: {list(PRESETS)}"}
    # from_dict crea objetos Rule nuevos con _last_fired_ms=-inf y _above=False
    rs = RuleSet.from_dict(preset.to_dict())
    session.autovj_engine.ruleset = rs
    return {"ok": True, "ruleset": rs.to_dict()}


def _h_autovj_update_rule(session, params):
    """autovj_update_rule(rule_uid, enabled?, cooldown_ms?, trigger?, action?) → {ok, rule}.

    Actualiza campos de una regla en el ruleset activo. Devuelve la regla (I3).
    """
    try:
        rule_uid = require_key(params, "rule_uid")
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    rs = session.autovj_engine.ruleset
    if rs is None:
        return {"ok": False, "error": "No hay ruleset activo"}
    rule = next((r for r in rs.rules if r.uid == rule_uid), None)
    if rule is None:
        return {"ok": False, "error": "rule_uid no encontrado"}

    if "enabled" in params:
        rule.enabled = bool(params["enabled"])
    if "cooldown_ms" in params:
        rule.cooldown_ms = max(0, int(params["cooldown_ms"]))
    if "trigger" in params:
        rule.trigger = str(params["trigger"])
    if "action" in params:
        rule.action = str(params["action"])

    return {"ok": True, "rule": rule.to_dict()}


def _h_autovj_save(session, params):
    """autovj_save() → {ok, path}.

    Guarda el ruleset activo en projects/<slug>/autovj.json (guardado atómico).
    No-op si no hay ruleset activo.
    """
    path = session.project.folder / "autovj.json"
    session.autovj_engine.save(path)
    ruleset = session.autovj_engine.ruleset
    return {
        "ok": True,
        "path": str(path),
        "saved": ruleset is not None,
    }


def _h_autovj_load(session, params):
    """autovj_load() → {ok, ruleset|null}.

    Carga el ruleset desde projects/<slug>/autovj.json.
    No-op si el archivo no existe.
    """
    path = session.project.folder / "autovj.json"
    session.autovj_engine.load(path)
    ruleset = session.autovj_engine.ruleset
    return {
        "ok": True,
        "ruleset": ruleset.to_dict() if ruleset is not None else None,
    }


# ── D2 — Análisis en vivo (entrada de audio) ─────────────────────────────────

def _h_live_input_list_devices(session, params):
    """live_input_list_devices() → {ok, devices: [{index, name, channels, default_sr}]}"""
    from server.live_input import LiveInput
    return {"ok": True, "devices": LiveInput.list_devices()}


def _h_live_input_start(session, params):
    """live_input_start(device_index?) → {ok, device_index, bpm}

    Arranca la captura de audio desde el dispositivo de entrada seleccionado
    (por defecto el dispositivo del SO) y activa el modo live: _get_audio_context
    usará las features del ring buffer en vez del análisis offline.
    """
    device = params.get("device_index", None)
    if device is not None:
        device = require_int(params, "device_index")
    if session.live_input is None:
        from server.live_input import LiveInput
        session.live_input = LiveInput()
    try:
        session.live_input.start(device=device)
    except Exception as e:
        return {"ok": False, "error": f"No se pudo abrir el dispositivo: {e}"}
    session._live_mode = True
    return {
        "ok": True,
        "device_index": device,
        "bpm": session.live_input.summary.get("bpm"),
    }


def _h_live_input_stop(session, params):
    """live_input_stop() → {ok}

    Detiene la captura y desactiva el modo live.
    El sistema vuelve a usar el análisis offline para actx y AutoVJ.
    """
    if session.live_input is not None:
        session.live_input.stop()
    session._live_mode = False
    return {"ok": True}


def _h_live_input_get_state(session, params):
    """live_input_get_state() → {ok, active, live_mode, bpm?, duration_s}"""
    li = session.live_input
    active = li is not None and li.is_active
    summary = li.summary if li is not None else {}
    return {
        "ok": True,
        "active": active,
        "live_mode": bool(getattr(session, '_live_mode', False)),
        "bpm": summary.get("bpm"),
        "duration_s": summary.get("duration_s", 0.0),
    }

HANDLERS = {
    "autovj_get_state": _h_autovj_get_state,
    "autovj_set_ruleset": _h_autovj_set_ruleset,
    "autovj_activate_preset": _h_autovj_activate_preset,
    "autovj_update_rule": _h_autovj_update_rule,
    "autovj_save": _h_autovj_save,
    "autovj_load": _h_autovj_load,
    "live_input_list_devices": _h_live_input_list_devices,
    "live_input_start": _h_live_input_start,
    "live_input_stop": _h_live_input_stop,
    "live_input_get_state": _h_live_input_get_state,
}
