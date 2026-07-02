"""Enciende todas las fixtures del proyecto activo via MCP bridge :9876."""
import asyncio
import json
import sys

sys.path.insert(0, '.')

BRIDGE = "ws://127.0.0.1:9876"

async def rpc(ws, method, params=None):
    msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    await ws.send(json.dumps(msg))
    raw = await asyncio.wait_for(ws.recv(), timeout=5)
    return json.loads(raw).get("result", {})

async def main():
    import websockets
    async with websockets.connect(BRIDGE, open_timeout=4) as ws:
        # Listar fixtures
        r = await rpc(ws, "list_fixtures")
        fixtures = r.get("fixtures", [])
        print(f"Fixtures en sesion: {len(fixtures)}")
        for fx in fixtures:
            print(f"  {fx['fixture_id']:12s}  profile={fx['profile_id']}")

        # Encender cada uno: dim=1, shutter=1
        ok = 0
        for fx in fixtures:
            fid = fx["fixture_id"]
            for ch, val in [("dim", 1.0), ("shutter", 1.0)]:
                r2 = await rpc(ws, "set_fixture_channel",
                               {"fixture_id": fid, "channel_name": ch, "value": val})
                if r2.get("ok"):
                    ok += 1
        print(f"\nCanales encendidos: {ok}")

asyncio.run(main())
