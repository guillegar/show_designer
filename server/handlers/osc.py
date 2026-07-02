"""
handlers/osc.py — E2: OSC bridge (estado + config) (ADR-005).
"""
from __future__ import annotations

from src._paths import PROJECT_DIR

# ── E2 — OSC bridge (ROADMAP v3) ─────────────────────────────────────────────

def _h_osc_get_state(session, params):
    """osc_get_state() → estado completo del bridge OSC."""
    osc = getattr(session, "osc_bridge", None)
    if osc is None:
        return {"ok": True, "enabled": False, "available": False,
                "port_in": 8001, "port_out": 8002,
                "clients_out": [], "recv_log": [], "active": False}
    return {"ok": True, **osc.get_state()}


def _h_osc_set_config(session, params):
    """osc_set_config(port_in?, port_out?, enabled?, clients_out?) → {ok}.

    clients_out: lista de {ip, port}.
    Persiste en output_targets.json. Reinicia el servidor IN si cambia el puerto o enabled.
    """
    osc = getattr(session, "osc_bridge", None)
    if osc is None:
        return {"ok": False, "error": "OSC bridge no disponible"}

    changed_server = False
    if "port_in" in params and params["port_in"] != osc.port_in:
        osc.port_in = int(params["port_in"])
        changed_server = True
    if "port_out" in params:
        osc.port_out = int(params["port_out"])
    if "enabled" in params and bool(params["enabled"]) != osc.enabled:
        osc.enabled = bool(params["enabled"])
        changed_server = True
    if "clients_out" in params:
        raw = params["clients_out"]
        osc.set_clients_out([(c["ip"], int(c["port"])) for c in raw if "ip" in c and "port" in c])

    # Guardar config (atómico vía output_targets.json).
    # OJO (ADR-005): anclado a PROJECT_DIR — el viejo Path(__file__).parent.parent
    # dejó de apuntar a la raíz al mover este código un nivel más adentro.
    osc.save_config(PROJECT_DIR / "output_targets.json")

    # Reiniciar servidor IN si cambiaron port_in o enabled
    if changed_server:
        import asyncio
        asyncio.create_task(osc.restart())

    return {"ok": True, **osc.get_state()}


HANDLERS = {
    "osc_get_state": _h_osc_get_state,
    "osc_set_config": _h_osc_set_config,
}
