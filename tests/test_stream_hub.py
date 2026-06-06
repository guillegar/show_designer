"""
test_stream_hub.py — broadcast paralelo del tick (A1) y limpieza de clientes muertos.

StreamHub acepta cualquier objeto con send_bytes/send_text → se prueba con WS
falsos, sin FastAPI ni red.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.tick import StreamHub  # noqa: E402


class FakeWS:
    def __init__(self, fail=False):
        self.fail = fail
        self.received = []

    async def send_bytes(self, data):
        if self.fail:
            raise RuntimeError("cliente muerto")
        self.received.append(data)

    async def send_text(self, text):
        if self.fail:
            raise RuntimeError("cliente muerto")
        self.received.append(text)


def test_broadcast_bytes_delivers_and_prunes_dead():
    hub = StreamHub()
    good, bad = FakeWS(), FakeWS(fail=True)
    hub.add(good)
    hub.add(bad)
    asyncio.run(hub.broadcast_bytes(b"frame"))
    assert good.received == [b"frame"]
    assert good in hub.clients
    assert bad not in hub.clients           # el muerto se descarta


def test_broadcast_json_delivers_and_prunes_dead():
    hub = StreamHub()
    good, bad = FakeWS(), FakeWS(fail=True)
    hub.add(good)
    hub.add(bad)
    asyncio.run(hub.broadcast_json({"type": "state", "t": 1.0}))
    assert len(good.received) == 1 and '"type": "state"' in good.received[0]
    assert bad not in hub.clients


def test_broadcast_no_clients_is_noop():
    hub = StreamHub()
    asyncio.run(hub.broadcast_bytes(b"x"))   # no lanza con 0 clientes
    assert len(hub.clients) == 0


def test_broadcast_all_good_survive():
    hub = StreamHub()
    a, b, c = FakeWS(), FakeWS(), FakeWS()
    for ws in (a, b, c):
        hub.add(ws)
    asyncio.run(hub.broadcast_bytes(b"z"))
    assert all(ws.received == [b"z"] for ws in (a, b, c))
    assert len(hub.clients) == 3
