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

from server.dispatcher import Dispatcher
from server.json_rpc import parse_json_rpc_message
from server.osc_bridge import OscBridge
from server.rest_api import create_rest_router
from server.session import ShowSession
from server.tick import StreamHub, TickLoop
from src.log import get_logger

_log = get_logger(__name__)

_ROOT = Path(__file__).parent.parent
_DIST = _ROOT / "web" / "dist"
_VIEWER3D = _ROOT / "src" / "viewer3d"
_OUTPUT_TARGETS = _ROOT / "output_targets.json"

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
    app.state._rest_api_key = ""  # L1: vacío = sin auth

    # L1: cargar api_key de output_targets.json si existe
    try:
        import json as _json
        if _OUTPUT_TARGETS.is_file():
            _cfg = _json.loads(_OUTPUT_TARGETS.read_text("utf-8"))
            app.state._rest_api_key = _cfg.get("api_key", "") or ""
    except Exception:
        pass

    # L1: montar router REST /api/v1 ANTES de los estáticos
    app.include_router(create_rest_router())

    @app.on_event("startup")
    async def _startup():
        hub: StreamHub = app.state.hub
        # on_change: marca un rev; el tick ya difunde rev en cada 'state'
        # Proyecto de arranque: LUCES_PROJECT (slug) si está definido, si no el default.
        startup_slug = os.environ.get("LUCES_PROJECT") or None
        session = ShowSession(slug=startup_slug, on_change=lambda kind: None)
        session.hub = hub  # B3: para que render offline emita progress events al stream
        dispatcher = Dispatcher(session)
        # FIX 10: warn if no auth tokens configured (all handlers publicly accessible)
        from server.auth import warn_if_no_tokens
        warn_if_no_tokens(getattr(session, "_tokens_config", []))
        app.state.session = session
        app.state.dispatcher = dispatcher

        # E2: OSC bridge
        osc_cfg = OscBridge.load_config(_OUTPUT_TARGETS)
        osc = OscBridge(
            session,
            port_in=osc_cfg.get("port_in", 8001),
            port_out=osc_cfg.get("port_out", 8002),
        )
        osc.enabled = osc_cfg.get("enabled", True)
        clients_raw = osc_cfg.get("clients_out", [])
        osc.set_clients_out([(c["ip"], c["port"]) for c in clients_raw if "ip" in c and "port" in c])
        session.osc_bridge = osc
        asyncio.create_task(osc.start())

        tick = TickLoop(session, hub)
        app.state.tick = tick
        asyncio.create_task(tick.run())

        # Precalentar el cache de la waveform FUERA del loop (librosa.load tarda
        # ~2-5 s): así el primer ≋ WF no congela el tick (ver _h_get_waveform).
        async def _prewarm_waveform():
            try:
                from server.handlers.waveform import _ensure_waveform_cached
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _ensure_waveform_cached, session)
            except Exception:
                pass
        asyncio.create_task(_prewarm_waveform())

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
        _log.info(f"[web] backend listo · stream + control en :8000 · MCP compat en :{MCP_COMPAT_PORT}")

    @app.on_event("shutdown")
    async def _shutdown():
        if app.state.tick:
            app.state.tick.stop()
        sess = app.state.session
        # E2: detener OSC bridge
        osc_b = getattr(sess, "osc_bridge", None) if sess else None
        if osc_b is not None:
            await osc_b.stop()
        # Liberar recursos: socket Art-Net + OutputRouter (ANALYSIS hallazgo 18).
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
        # L3: token de autenticación desde query param ?token=
        token: str = ws.query_params.get("token", "") or ""
        try:
            while True:
                raw = await ws.receive_text()
                msg, err = parse_json_rpc_message(raw)
                if err:
                    await ws.send_text(json.dumps(err))
                    continue
                resp = disp.handle(msg, token=token)
                await ws.send_text(json.dumps(resp))
        except WebSocketDisconnect:
            pass
        except Exception as e:
            _log.warning(f"[web] /ws/control cerrado: {type(e).__name__}: {e}")

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
        _log.info(f"[web] MCP compat escuchando en ws://{MCP_COMPAT_HOST}:{MCP_COMPAT_PORT}")
    except Exception as e:
        _log.error(f"[web] No se pudo abrir MCP compat :{MCP_COMPAT_PORT}: {e}")
