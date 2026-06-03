"""
tick.py — Loop de render asyncio (sustituye al QTimer de dual_app).

Cada ~33 ms (30 FPS reproduciendo, 10 FPS en idle):
  1. Lee el reloj maestro (audio del PC).
  2. Gestiona fin de pista (loop / stop).
  3. compute_frame(t) → RGB de las 10 barras.
  4. Si reproduce: envía Art-Net por el ShowEngine (igual que shared_tick).
  5. Broadcast a los clientes /ws/stream:
       - frame binario RGB (10×93×3 = 2790 bytes)
       - {type:"state", ...}  (tiempo, transporte, sección, compás, rev)
       - {type:"dmx", fixtures:{...}}  (movers/strobes normalizados 0..1)

Corre en el MISMO event loop que el servidor web y el dispatcher, así que las
mutaciones del modelo (control) y las lecturas (este tick) nunca se solapan
(asyncio es cooperativo monohilo) → sin locks.
"""
from __future__ import annotations

import asyncio
import time
from typing import Set

from src.core.effects_engine import NUM_BARS


class StreamHub:
    """Conjunto de clientes WebSocket /ws/stream + broadcast tolerante a fallos."""

    def __init__(self):
        self.clients: Set = set()

    def add(self, ws):
        self.clients.add(ws)

    def remove(self, ws):
        self.clients.discard(ws)

    async def broadcast_bytes(self, data: bytes):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def broadcast_json(self, obj: dict):
        import json
        text = json.dumps(obj)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


class TickLoop:
    def __init__(self, session, hub: StreamHub, fps: int = 30, idle_fps: int = 10):
        self.session = session
        self.hub = hub
        self.fps = fps
        self.idle_fps = idle_fps
        self._running = False
        self._fps_meter = 0.0
        self._n = 0

    async def run(self):
        self._running = True
        s = self.session
        while self._running:
            self._n += 1
            t0 = time.monotonic()
            try:
                t = s.time
                playing = s.playing

                # Fin de pista: loop o stop
                if playing and s.duration > 0 and t >= s.duration - 0.02:
                    if s.loop:
                        s.play(at=0.0)
                        t = 0.0
                    else:
                        s.pause()
                        playing = False

                frame = s.compute_frame(t)

                # Art-Net (siempre, no solo reproduciendo)
                if s.send_artnet and s.show_engine is not None:
                    try:
                        rgb_list = [bytearray(frame[b].flatten().astype('uint8')) for b in range(NUM_BARS)]
                        s.show_engine.send_frame(rgb_list)
                    except Exception as e:
                        print(f"[tick] Art-Net error: {e}")
                        pass

                # Broadcast frame binario
                if self.hub.clients:
                    await self.hub.broadcast_bytes(frame.astype('uint8').tobytes())

                    bar, beat = s.bar_beat(t)
                    await self.hub.broadcast_json({
                        "type": "state",
                        "t": round(t, 3),
                        "playing": playing,
                        "duration": round(s.duration, 3),
                        "loop": s.loop,
                        "rec": s.rec,
                        "section": s.section_name_at(t),
                        "bar": bar,
                        "beat": beat,
                        "fps": round(self._fps_meter, 1),
                        "rev": s._rev,
                        "clip_count": len(s.timeline.clips),
                    })

                    # Estado DMX de movers/strobes (no-LED). Es caro (itera
                    # fixtures × clips), así que se difunde a ~7.5 FPS (cada 4
                    # ticks), suficiente para movers; los LEDs van a 30 FPS.
                    if s.show_engine is not None and self._n % 4 == 0:
                        try:
                            dmx = s.show_engine.get_fixture_dmx_states(
                                t, s._cached_actx, None, s.timeline)
                            if dmx:
                                await self.hub.broadcast_json(
                                    {"type": "dmx", "fixtures": dmx})
                        except Exception:
                            pass
            except Exception as e:
                print(f"[tick] error: {e}")

            period = 1.0 / (self.fps if self.session.playing else self.idle_fps)
            elapsed = time.monotonic() - t0
            if elapsed > 0:
                self._fps_meter = min(self.fps, 1.0 / elapsed)
            await asyncio.sleep(max(0.0, period - elapsed))

    def stop(self):
        self._running = False
