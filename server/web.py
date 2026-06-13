"""
web.py — Servidor web FastAPI (estáticos + WebSockets).

Endpoints:
  GET  /                 → frontend web (web/dist) o página placeholder
  WS   /ws/control       → JSON-RPC 2.0 (los 52 métodos del dispatcher)
  WS   /ws/stream        → broadcast de frames RGB + estado + DMX (desde el tick)

Además, en el MISMO event loop, arranca el servidor de compatibilidad
ws://127.0.0.1:9876 que ya habla `mcp_show_server.py` (Claude), usando el MISMO
dispatcher → continuidad MCP sin tocar el server MCP.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from server.session import ShowSession
from server.dispatcher import Dispatcher
from server.tick import StreamHub, TickLoop
from server.json_rpc import parse_json_rpc_message

_ROOT = Path(__file__).parent.parent
_DIST = _ROOT / "web" / "dist"
_VIEWER3D = _ROOT / "src" / "viewer3d"

MCP_COMPAT_HOST = "127.0.0.1"
MCP_COMPAT_PORT = 9876


_PLACEHOLDER = """<!doctype html><html><head><meta charset=utf-8>
<title>LUCES — backend web</title>
<style>body{background:#0d0f12;color:#f3f4f6;font-family:system-ui;padding:40px;line-height:1.6}
code{background:#1d2127;padding:2px 6px;border-radius:5px;color:#1fe39a}
b{color:#1fe39a}</style></head><body>
<h1>LUC<span style=color:#1fe39a>ES</span> · backend web activo</h1>
<p>El backend headless está corriendo. El frontend todavía no está compilado.</p>
<p>Para construirlo: <code>cd web</code> y <code>npm install &amp;&amp; npm run build</code>,
o en desarrollo <code>npm run dev</code> (que proxea a este backend).</p>
<ul>
<li>Control JSON-RPC: <code>ws://localhost:8000/ws/control</code></li>
<li>Stream de frames/estado: <code>ws://localhost:8000/ws/stream</code></li>
<li>Compat MCP (Claude): <code>ws://127.0.0.1:9876</code></li>
</ul></body></html>"""


def create_app() -> FastAPI:
    app = FastAPI(title="Luces Web Backend")
    app.state.session = None
    app.state.dispatcher = None
    app.state.hub = StreamHub()
    app.state.tick = None

    @app.on_event("startup")
    async def _startup():
        hub: StreamHub = app.state.hub
        # on_change: marca un rev; el tick ya difunde rev en cada 'state'
        # Proyecto de arranque: LUCES_PROJECT (slug) si está definido, si no el default.
        startup_slug = os.environ.get("LUCES_PROJECT") or None
        session = ShowSession(slug=startup_slug, on_change=lambda kind: None)
        session.hub = hub  # B3: para que render offline emita progress events al stream
        dispatcher = Dispatcher(session)
        app.state.session = session
        app.state.dispatcher = dispatcher

        tick = TickLoop(session, hub)
        app.state.tick = tick
        asyncio.create_task(tick.run())

        # B4: tarea de autosave (I/O pesado — no en el tick de 30 FPS)
        asyncio.create_task(session.start_autosave_task())

        # B4: emitir evento autosave_available si hay un autosave más nuevo que show.json
        async def _emit_autosave_banner():
            await asyncio.sleep(1.5)  # esperar a que los clientes conecten
            event = session.check_autosave_at_startup()
            if event:
                await hub.broadcast_json(event)
        asyncio.create_task(_emit_autosave_banner())

        # Compat MCP en :9876, mismo loop, mismo dispatcher
        # (se puede desactivar en tests con LUCES_NO_MCP_COMPAT=1)
        if not os.environ.get("LUCES_NO_MCP_COMPAT"):
            asyncio.create_task(_start_mcp_compat(dispatcher))
        print(f"[web] backend listo · stream + control en :8000 · MCP compat en :{MCP_COMPAT_PORT}")

    @app.on_event("shutdown")
    async def _shutdown():
        if app.state.tick:
            app.state.tick.stop()
        # Liberar recursos: socket Art-Net + OutputRouter (ANALYSIS hallazgo 18).
        sess = app.state.session
        eng = getattr(sess, "show_engine", None) if sess else None
        if eng is not None and hasattr(eng, "close"):
            try:
                eng.close()
            except Exception:
                pass

    # ── WS control (JSON-RPC) ────────────────────────────────────────────────
    @app.websocket("/ws/control")
    async def ws_control(ws: WebSocket):
        await ws.accept()
        disp: Dispatcher = app.state.dispatcher
        try:
            while True:
                raw = await ws.receive_text()
                msg, err = parse_json_rpc_message(raw)
                if err:
                    await ws.send_text(json.dumps(err))
                    continue
                resp = disp.handle(msg)
                await ws.send_text(json.dumps(resp))
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"[web] /ws/control cerrado: {type(e).__name__}: {e}")

    # ── WS stream (frames + estado) ──────────────────────────────────────────
    @app.websocket("/ws/stream")
    async def ws_stream(ws: WebSocket):
        await ws.accept()
        hub: StreamHub = app.state.hub
        hub.add(ws)
        try:
            # El cliente no necesita mandar nada; mantenemos viva la conexión.
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            hub.remove(ws)

    # ── Estáticos / SPA ──────────────────────────────────────────────────────
    # Viewer 3D legacy está en web/dist/v3d/ (copiado de src/viewer3d)
    # y es servido por StaticFiles en la montadura /

    if _DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="static")
    else:
        @app.get("/", response_class=HTMLResponse)
        async def _root():
            return _PLACEHOLDER

    return app


async def _start_mcp_compat(dispatcher: Dispatcher):
    """Servidor ws://127.0.0.1:9876 con el protocolo JSON-RPC del bridge."""
    import websockets

    async def _handle(ws):
        try:
            async for raw in ws:
                msg, err = parse_json_rpc_message(raw)
                if err:
                    await ws.send(json.dumps(err))
                    continue
                resp = dispatcher.handle(msg)
                await ws.send(json.dumps(resp))
        except Exception:
            pass

    try:
        await websockets.serve(_handle, MCP_COMPAT_HOST, MCP_COMPAT_PORT, ping_interval=20)
        print(f"[web] MCP compat escuchando en ws://{MCP_COMPAT_HOST}:{MCP_COMPAT_PORT}")
    except Exception as e:
        print(f"[web] No se pudo abrir MCP compat :{MCP_COMPAT_PORT}: {e}")
