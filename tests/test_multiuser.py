"""
test_multiuser.py — Tests para control de acceso multiusuario (L3).
"""
from __future__ import annotations

import pytest

from server.auth import ASSISTANT_HANDLERS, check_permission, role_for_token
from server.dispatcher import Dispatcher

# ─── fixtures de config ─────────────────────────────────────────────────────

TOKENS_CFG = [
    {"token": "op_token", "role": "operator"},
    {"token": "ass_token", "role": "assistant"},
]


# ─── tests de check_permission ──────────────────────────────────────────────

def test_assistant_token_rejects_add_clip():
    """Token assistant rechaza add_clip → permission_denied."""
    result = check_permission("ass_token", "add_clip", TOKENS_CFG)
    assert result["ok"] is False
    assert result["error"] == "permission_denied"


def test_assistant_token_accepts_go_next_cue():
    """Token assistant acepta go_next_cue (en ASSISTANT_HANDLERS)."""
    result = check_permission("ass_token", "go_next_cue", TOKENS_CFG)
    assert result["ok"] is True


def test_assistant_token_accepts_list_prefix():
    """Token assistant acepta list_clips (prefijo list_)."""
    result = check_permission("ass_token", "list_clips", TOKENS_CFG)
    assert result["ok"] is True


def test_operator_token_accepts_add_clip():
    """Token operator acepta add_clip sin restricción."""
    result = check_permission("op_token", "add_clip", TOKENS_CFG)
    assert result["ok"] is True


def test_no_tokens_configured_allows_all():
    """Sin tokens configurados → todo accesible (backwards-compat)."""
    result = check_permission("", "add_clip", [])
    assert result["ok"] is True


def test_unknown_token_returns_invalid_token():
    """Token desconocido cuando hay tokens → invalid_token."""
    result = check_permission("unknown_xyz", "list_clips", TOKENS_CFG)
    assert result["ok"] is False
    assert result["error"] == "invalid_token"


# ─── test de integración con Dispatcher ─────────────────────────────────────

def test_dispatcher_permission_denied_returns_error_in_result():
    """Dispatcher responde {ok: False, error: permission_denied} para assistant que llama add_clip."""
    from unittest.mock import MagicMock
    session = MagicMock()
    session._tokens_config = TOKENS_CFG
    # required by the dispatcher logic
    session.snapshot = MagicMock()

    disp = Dispatcher(session)
    resp = disp.handle({"jsonrpc": "2.0", "id": 1, "method": "add_clip", "params": {}}, token="ass_token")
    assert resp.get("result", {}).get("ok") is False
    assert resp.get("result", {}).get("error") == "permission_denied"


def test_dispatcher_auth_get_role_returns_correct_role():
    """auth_get_role devuelve 'assistant' para el token de asistente."""
    from unittest.mock import MagicMock
    session = MagicMock()
    session._tokens_config = TOKENS_CFG

    disp = Dispatcher(session)
    resp = disp.handle({"jsonrpc": "2.0", "id": 1, "method": "auth_get_role", "params": {}}, token="ass_token")
    assert resp.get("result", {}).get("ok") is True
    assert resp.get("result", {}).get("role") == "assistant"
