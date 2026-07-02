"""
test_web.py — Fase 3: servidor web FastAPI (control + stream) vía TestClient.

Usa starlette TestClient (sin abrir puertos reales salvo el WS in-process).
Desactiva el compat MCP :9876 para no tocar puertos del sistema en CI.
"""
import json
import os
import sys
from pathlib import Path

import pytest

os.environ["LUCES_NO_MCP_COMPAT"] = "1"
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from server.web import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:   # dispara startup (crea ShowSession + tick)
        yield c


def test_control_get_state(client):
    with client.websocket_connect("/ws/control") as ws:
        ws.send_text(json.dumps({"jsonrpc": "2.0", "id": 1,
                                 "method": "get_state", "params": {}}))
        resp = json.loads(ws.receive_text())
        assert resp["result"]["clip_count"] > 0


def test_control_add_clip(client):
    with client.websocket_connect("/ws/control") as ws:
        ws.send_text(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "add_clip",
                                 "params": {"track": 0, "start_ms": 1000,
                                            "end_ms": 2000, "effect_id": 0}}))
        resp = json.loads(ws.receive_text())
        assert resp["result"]["ok"] is True


def test_stream_frames(client):
    # Arranca reproducción y comprueba que llegan frames binarios de 2790 bytes
    with client.websocket_connect("/ws/control") as ctrl:
        ctrl.send_text(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "play",
                                   "params": {"start_sec": 72.0}}))
        json.loads(ctrl.receive_text())
        with client.websocket_connect("/ws/stream") as stream:
            got_frame = False
            got_state = False
            for _ in range(60):
                msg = stream.receive()
                if "bytes" in msg and msg["bytes"] is not None:
                    assert len(msg["bytes"]) == 10 * 93 * 3
                    got_frame = True
                elif "text" in msg and msg["text"]:
                    d = json.loads(msg["text"])
                    if d.get("type") == "state":
                        got_state = True
                if got_frame and got_state:
                    break
            assert got_frame, "no llegaron frames binarios"
            assert got_state, "no llegó estado"
