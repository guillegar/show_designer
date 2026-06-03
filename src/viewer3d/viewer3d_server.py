"""
viewer3d_server.py — Servidor HTTP + WebSocket para el viewer 3D.

Se arranca como hilo desde dual_app.py. Sirve:
   - HTTP en :8080  → archivos estáticos de viewer3d/ + rig_layout.json
   - WS   en :9877  → broadcast del frame RGB cada tick (binary Uint8Array)

El frame es array de NUM_BARS * LEDS_PER_BAR * 3 bytes (RGB intercalado:
   bar0_led0_R, bar0_led0_G, bar0_led0_B, bar0_led1_R, ...).

Uso desde dual_app.py:
    from viewer3d_server import Viewer3DServer
    viewer = Viewer3DServer(num_bars=10, leds_per_bar=93)
    viewer.start()
    # Cuando hay frame nuevo:
    viewer.broadcast_frame(frame_ndarray)  # shape (10, 93, 3) uint8

Modo standalone (test sin dual_app):
    python viewer3d_server.py
"""
from __future__ import annotations
import asyncio
import http.server
import json
import logging
import os

# v1.9 F2 — silenciar tracebacks de la librería websockets cuando hay
# conexiones TCP mal formadas (Test-NetConnection, etc.). Nuestro
# set_exception_handler ya las gestiona; no queremos stderr ruidoso.
logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
logging.getLogger("websockets.asyncio.server").setLevel(logging.CRITICAL)
import socketserver
import threading
from pathlib import Path
from typing import Dict, Optional, Set

try:
    import websockets
except ImportError:
    raise SystemExit("Falta: pip install websockets")

import numpy as np

VIEWER_DIR = Path(__file__).parent / "viewer3d"
HTTP_PORT = 8080
WS_PORT = 9877


# ───────────────────────────────────────────────────────────────
# HTTP server — sirve viewer3d/ como contenido estático
# ───────────────────────────────────────────────────────────────

class _ViewerHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

    def log_message(self, format, *args):
        # Suprimir logs ruidosos por consola
        return

    def end_headers(self):
        # CORS para permitir fetch desde cualquier origen (útil para LAN)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


class _ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ───────────────────────────────────────────────────────────────
# Viewer3DServer — orquesta HTTP + WS
# ───────────────────────────────────────────────────────────────

class Viewer3DServer:
    """Levanta HTTP + WebSocket en threads daemon."""

    def __init__(self, num_bars: int = 10, leds_per_bar: int = 93):
        self.num_bars = num_bars
        self.leds_per_bar = leds_per_bar
        self.expected_bytes = num_bars * leds_per_bar * 3

        self._http_server: Optional[socketserver.TCPServer] = None
        self._http_thread: Optional[threading.Thread] = None

        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._clients: Set = set()
        self._last_frame_bytes: Optional[bytes] = None
        # v1.7 Fase 4 — último estado DMX por fixture (texto JSON)
        # Se reenvía a nuevos clientes para que no vean el rig "negro".
        self._last_dmx_state_text: Optional[str] = None

    # ── HTTP ────────────────────────────────────────────────────
    def _run_http(self):
        try:
            self._http_server = _ReusableTCPServer(
                ("0.0.0.0", HTTP_PORT), _ViewerHTTPHandler
            )
            print(f"[viewer3d] HTTP listening on http://localhost:{HTTP_PORT}/")
            self._http_server.serve_forever()
        except OSError as e:
            print(f"[viewer3d] HTTP no pudo arrancar: {e}")

    # ── WebSocket ───────────────────────────────────────────────
    async def _handle_client(self, ws):
        self._clients.add(ws)
        print(f"[viewer3d] WS client connect ({len(self._clients)} total)")
        # Mandar último frame al conectar (para que no vea negro)
        if self._last_frame_bytes is not None:
            try:
                await ws.send(self._last_frame_bytes)
            except Exception:
                pass
        # ...y el último estado DMX (movers/strobes)
        if self._last_dmx_state_text is not None:
            try:
                await ws.send(self._last_dmx_state_text)
            except Exception:
                pass
        try:
            async for _ in ws:
                pass   # no esperamos mensajes del cliente
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            # v1.9 F2: cualquier otra cosa (cliente que se va, payload roto)
            # NO debe matar el thread del WebSocket
            print(f"[viewer3d] WS client conexión cerrada por error: "
                  f"{type(e).__name__}: {e}")
        finally:
            self._clients.discard(ws)
            print(f"[viewer3d] WS client disconnect ({len(self._clients)} restantes)")

    async def _ws_serve(self):
        print(f"[viewer3d] WS listening on ws://localhost:{WS_PORT}/")
        async with websockets.serve(self._handle_client, "0.0.0.0", WS_PORT,
                                    ping_interval=20, max_size=2 * 1024 * 1024):
            await asyncio.Future()

    def _run_ws(self):
        self._ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._ws_loop)

        # v1.9 F2: exception handler para handshakes fallidos del WS.
        # Mismo patrón que mcp_bridge.py — sin esto, una conexión TCP cruda
        # al puerto 9877 mataría el thread y, por race con Qt, la app entera.
        def _exc_handler(loop, ctx):
            exc = ctx.get('exception')
            try:
                _silenciables = (websockets.exceptions.InvalidMessage,
                                 ConnectionResetError, EOFError,
                                 BrokenPipeError, OSError)
            except AttributeError:
                _silenciables = (ConnectionResetError, EOFError,
                                 BrokenPipeError, OSError)
            if exc is not None and isinstance(exc, _silenciables):
                return   # silencioso
            exc_name = type(exc).__name__ if exc else 'no-exc'
            print(f"[viewer3d] WS async error: "
                  f"{ctx.get('message', '?')} ({exc_name})")

        self._ws_loop.set_exception_handler(_exc_handler)
        try:
            self._ws_loop.run_until_complete(self._ws_serve())
        except Exception as e:
            print(f"[viewer3d] WS terminado: {e}")

    # ── API pública ─────────────────────────────────────────────
    def start(self):
        if self._http_thread is None:
            self._http_thread = threading.Thread(
                target=self._run_http, daemon=True, name="viewer3d_http"
            )
            self._http_thread.start()
        if self._ws_thread is None:
            self._ws_thread = threading.Thread(
                target=self._run_ws, daemon=True, name="viewer3d_ws"
            )
            self._ws_thread.start()

    def broadcast_frame(self, frame: np.ndarray):
        """
        Envía un frame RGB a todos los clientes WS conectados.

        frame: ndarray shape (num_bars, leds_per_bar, 3) dtype uint8.
        Se serializa como bytes intercalados (RGB RGB RGB...) y se envía
        binario por WebSocket — los browser lo reciben como ArrayBuffer.
        """
        if self._ws_loop is None:
            return
        try:
            if frame.dtype != np.uint8:
                frame = frame.astype(np.uint8)
            data = frame.tobytes()
            if len(data) != self.expected_bytes:
                # tamaño raro — ignoramos
                return
            self._last_frame_bytes = data
            if self._clients:
                # Schedule broadcast en el loop del WS
                asyncio.run_coroutine_threadsafe(
                    self._broadcast(data), self._ws_loop
                )
        except Exception as e:
            print(f"[viewer3d] broadcast error: {e}")

    async def _broadcast(self, data):
        """Envía `data` (bytes o str) a todos los clientes."""
        if not self._clients:
            return
        await asyncio.gather(
            *[c.send(data) for c in list(self._clients)],
            return_exceptions=True
        )

    # ── v1.7 Fase 4 — DMX state broadcast (movers/strobes) ────────
    def broadcast_dmx_state(self, states: Dict[str, Dict[str, float]]):
        """Envía un mensaje JSON con el estado DMX de los fixtures no-LED.

        Formato:
            {"type": "dmx",
             "fixtures": {
               "mover_wash_L_back": {"pan": 0.5, "tilt": 0.3, "dim": 1.0,
                                     "r": 1.0, "g": 0.4, "b": 0.0},
               ...
             }}

        Los valores ya vienen normalizados 0..1 desde
        `ShowEngine.get_fixture_dmx_states()`. El JS los multiplica por
        `metadata.max_pan_deg/max_tilt_deg` (que recibe en `rig_layout.json`).
        """
        if self._ws_loop is None or not states:
            return
        try:
            payload = {"type": "dmx", "fixtures": states}
            text = json.dumps(payload, separators=(',', ':'))
            self._last_dmx_state_text = text
            if self._clients:
                asyncio.run_coroutine_threadsafe(
                    self._broadcast(text), self._ws_loop
                )
        except Exception as e:
            print(f"[viewer3d] broadcast_dmx_state error: {e}")

    def broadcast_reload_layout(self):
        """Ordena al browser que recargue rig_layout.json y reconstruya la escena."""
        if self._ws_loop is None:
            return
        try:
            text = '{"type":"reload_layout"}'
            if self._clients:
                asyncio.run_coroutine_threadsafe(
                    self._broadcast(text), self._ws_loop
                )
        except Exception as e:
            print(f"[viewer3d] broadcast_reload_layout error: {e}")


# ───────────────────────────────────────────────────────────────
# Modo standalone — sirve viewer3d + envía un sweep animado
# ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time
    print("[standalone] arrancando viewer3d sin dual_app...")
    srv = Viewer3DServer(num_bars=10, leds_per_bar=93)
    srv.start()
    print(f"[standalone] Abre http://localhost:{HTTP_PORT}/ en el navegador")

    # Animación de prueba: sweep colorido
    frame = np.zeros((10, 93, 3), dtype=np.uint8)
    t = 0
    try:
        while True:
            time.sleep(1.0 / 30)
            t += 1
            frame[:] = 0
            for b in range(10):
                phase = (t * 0.05 + b * 0.6) % (2 * np.pi)
                intensity = int((np.sin(phase) * 0.5 + 0.5) * 255)
                for led in range(93):
                    fade = int(intensity * (led / 93.0))
                    frame[b, led, 0] = fade
                    frame[b, led, 1] = fade // 3
                    frame[b, led, 2] = 255 - fade
            srv.broadcast_frame(frame)
    except KeyboardInterrupt:
        print("\n[standalone] cerrado")
