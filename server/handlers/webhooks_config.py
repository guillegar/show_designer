"""
handlers/webhooks_config.py — L2: configuración de webhooks de eventos (ADR-005).
"""
from __future__ import annotations

# ── L2 — Webhooks de eventos ─────────────────────────────────────────────────

def _h_webhook_get_config(session, params):
    """webhook_get_config() → {ok, webhooks: [{url, events, secret?}]}."""
    wh = getattr(session, "_webhook_dispatcher", None)
    if wh is None:
        return {"ok": True, "webhooks": []}
    return {"ok": True, "webhooks": wh.get_configs()}


def _h_webhook_set_config(session, params):
    """webhook_set_config(webhooks: list) → {ok}.

    Guarda la lista en output_targets.json (escritura atómica) y recarga
    el dispatcher en memoria.
    """
    import json
    webhooks = params.get("webhooks", [])
    if not isinstance(webhooks, list):
        return {"ok": False, "error": "webhooks debe ser una lista"}

    # Validar entradas básicas + FIX 5: SSRF guard on webhook URLs
    from server.webhooks import _validate_webhook_url
    for entry in webhooks:
        if not isinstance(entry, dict) or "url" not in entry:
            return {"ok": False, "error": "Cada webhook requiere campo 'url'"}
        if "events" not in entry or not isinstance(entry["events"], list):
            return {"ok": False, "error": "Cada webhook requiere campo 'events' (lista)"}
        try:
            _validate_webhook_url(entry["url"])
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    # Actualizar dispatcher en memoria
    wh = getattr(session, "_webhook_dispatcher", None)
    if wh is not None:
        wh.set_configs(webhooks)

    # Persistir en output_targets.json (atómico)
    from src._paths import PROJECT_DIR
    targets_file = PROJECT_DIR / "output_targets.json"
    if targets_file.is_file():
        try:
            with open(targets_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}
    data["webhooks"] = webhooks
    tmp = targets_file.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(targets_file)
    except Exception as e:
        return {"ok": False, "error": f"Error guardando config: {e}"}

    return {"ok": True, "count": len(webhooks)}


HANDLERS = {
    "webhook_get_config": _h_webhook_get_config,
    "webhook_set_config": _h_webhook_set_config,
}
