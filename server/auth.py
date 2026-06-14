"""
auth.py — Control de acceso multiusuario (L3).

Config en output_targets.json["tokens"]:
  [{"token": "abc123", "role": "operator"}, {"token": "xyz789", "role": "assistant"}]

Roles:
  operator  — acceso completo a todos los handlers.
  assistant — solo ASSISTANT_HANDLERS + prefijos get_/list_.
  (sin tokens configurados) → todo accesible, backwards-compat para desarrollo local.

Token desconocido cuando hay tokens configurados → error "invalid_token".
"""
from __future__ import annotations

ASSISTANT_HANDLERS: frozenset = frozenset({
    "set_macro",
    "go_cue",
    "go_next_cue",
    "go_prev_cue",
    "blackout",
    "live_trigger",
    "live_stop_all",
    "auth_get_role",
})

_ASSISTANT_PREFIXES = ("get_", "list_")


def check_permission(token: str, handler_name: str, tokens_config: list) -> dict:
    """
    Verifica si el token tiene permiso para ejecutar handler_name.

    Returns:
        {"ok": True} si permitido.
        {"ok": False, "error": "invalid_token"} si tokens configurados pero token desconocido.
        {"ok": False, "error": "permission_denied"} si rol insuficiente.

    Sin tokens configurados → todo accesible (backwards-compat).
    """
    if not tokens_config:
        return {"ok": True}

    entry = next((t for t in tokens_config if t.get("token") == token), None)
    if entry is None:
        return {"ok": False, "error": "invalid_token"}

    role = entry.get("role", "operator")
    if role == "operator":
        return {"ok": True}

    # assistant: lista exacta o prefijo permitido
    if handler_name in ASSISTANT_HANDLERS:
        return {"ok": True}
    for prefix in _ASSISTANT_PREFIXES:
        if handler_name.startswith(prefix):
            return {"ok": True}

    return {"ok": False, "error": "permission_denied"}


def role_for_token(token: str, tokens_config: list) -> str:
    """Devuelve el rol del token: "operator", "assistant" o "anonymous"."""
    if not tokens_config:
        return "operator"
    entry = next((t for t in tokens_config if t.get("token") == token), None)
    if entry is None:
        return "anonymous"
    return entry.get("role", "operator")
