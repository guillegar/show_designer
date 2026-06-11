import json, asyncio, sys, io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    import websockets

    # 1) Estado via MCP compat :9876
    async with websockets.connect("ws://127.0.0.1:9876/") as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "get_state"}))
        st = json.loads(await ws.recv()).get("result", {})
        print(f"[+] clip_count={st.get('clip_count')} playing={st.get('playing')} time={st.get('time_sec')}")
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "play"}))
        await ws.recv()

    # 2) Leer un frame binario real del stream :8000/ws/stream
    async with websockets.connect("ws://127.0.0.1:8000/ws/stream", max_size=None) as ws:
        frame = None
        for _ in range(60):
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            if isinstance(msg, (bytes, bytearray)) and len(msg) >= 2790:
                frame = bytes(msg[:2790])
                break
        if frame is None:
            print("[-] No llego frame binario de 2790 bytes")
            return

        def bar_rgb(b):
            base = b * 93 * 3 + 46 * 3  # LED 46 (centro) de la barra b
            return frame[base], frame[base + 1], frame[base + 2]

        print("[+] Frame recibido. Color central por barra:")
        for b in range(10):
            r, g, bl = bar_rgb(b)
            if r > 120 and g < 80:
                tag = "ROJO"
            elif r > 120 and g > 120:
                tag = "AMARILLO"
            else:
                tag = "?"
            print(f"    barra {b}: RGB=({r:3d},{g:3d},{bl:3d})  -> {tag}")

asyncio.run(main())
