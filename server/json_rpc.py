"""
json_rpc.py — Parser JSON-RPC 2.0 reutilizable para web.py (FastAPI + websockets compat).

Elimina la duplicación del parse/error-handle en ws_control y _start_mcp_compat.
"""
from __future__ import annotations

import json


def parse_json_rpc_message(raw: str) -> tuple[dict | None, dict | None]:
    """
    Parsea un mensaje JSON-RPC 2.0. Devuelve (msg_dict, error_response).

    Args:
        raw: string JSON crudo

    Returns:
        - Si ok: (msg_dict, None)
        - Si error parse: (None, error_response_dict)

    El error_response sigue el esquema JSON-RPC 2.0:
        {"jsonrpc": "2.0", "id": null, "error": {"code": -32700, "message": "..."}}
    """
    try:
        msg = json.loads(raw)
        if not isinstance(msg, dict):
            return None, {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "mensaje no es objeto JSON"},
            }
        return msg, None
    except json.JSONDecodeError as e:
        return None, {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": f"JSON parse error: {e}"},
        }
