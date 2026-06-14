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
        # Envío en paralelo (asyncio.gather): un cliente lento NO frena al resto
        # ni al tick loop. Coste = máx(latencias) en vez de Σ(latencias).
        if not self.clients:
            return
        clients = list(self.clients)
        results = await asyncio.gather(
            *(ws.send_bytes(data) for ws in clients), return_exceptions=True)
        for ws, res in zip(clients, results):
            if isinstance(res, Exception):
                self.clients.discard(ws)

    async def broadcast_json(self, obj: dict):
        if not self.clients:
            return
        import json
        text = json.dumps(obj)
        clients = list(self.clients)
        results = await asyncio.gather(
            *(ws.send_text(text) for ws in clients), return_exceptions=True)
        for ws, res in zip(clients, results):
            if isinstance(res, Exception):
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
        self._last_state_sig = None  # throttle del estado JSON (A3)
        self._record_emit_t: float = 0.0  # I1: último envío de record_state

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

                frame = s.compute_frame(t)  # (NUM_BARS, LEDS, 3) uint8

                # Art-Net (siempre, no solo reproduciendo). frame[b] ya es uint8
                # contiguo → .tobytes() da el RGB row-major sin copias extra.
                if s.send_artnet and s.show_engine is not None:
                    try:
                        s.show_engine.send_frame([frame[b].tobytes() for b in range(NUM_BARS)])
                    except Exception as e:
                        print(f"[tick] Art-Net error: {e}")

                # Broadcast frame binario (frame ya es uint8 → sin astype redundante)
                if self.hub.clients:
                    await self.hub.broadcast_bytes(frame.tobytes())

                    # Estado JSON: la UI no necesita 30 FPS. Se difunde cada 3 ticks
                    # (~10 FPS) o cuando cambia algo relevante (play/section/bar/rev).
                    bar, beat = s.bar_beat(t)
                    section = s.section_name_at(t)
                    sig = (playing, section, bar, beat, s.loop, s.rec, s._rev)
                    if self._n % 3 == 0 or sig != self._last_state_sig:
                        self._last_state_sig = sig
                        ts = getattr(s, "tempo_sync", None)
                        await self.hub.broadcast_json({
                            "type": "state",
                            "t": round(t, 3),
                            "playing": playing,
                            "duration": round(s.duration, 3),
                            "loop": s.loop,
                            "rec": s.rec,
                            "section": section,
                            "bar": bar,
                            "beat": beat,
                            "fps": round(self._fps_meter, 1),
                            "rev": s._rev,
                            "clip_count": len(s.timeline.clips),
                            "tempo_sync": ts.get_state() if ts else {"mode": "off", "bpm": 0.0, "synced": False},
                        })

                    # E1: cue_changed — emitir solo si hay fade activo y pct cambió >1%
                    cue_fade_start = getattr(s, '_cue_fade_start_ms', None)
                    if cue_fade_start is not None:
                        cue_dur = max(1.0, getattr(s, '_cue_fade_duration_ms', 1.0))
                        t_ms_now = int(t * 1000)
                        elapsed_c = t_ms_now - cue_fade_start
                        fade_pct = round(min(1.0, max(0.0, elapsed_c / cue_dur)), 3)
                        last_pct = getattr(s, '_cue_last_fade_pct', -1.0)
                        if abs(fade_pct - last_pct) > 0.01:
                            s._cue_last_fade_pct = fade_pct
                            cue_st = s.get_cue_state()
                            await self.hub.broadcast_json({
                                "type": "cue_changed",
                                "active_uid": cue_st["active_uid"],
                                "fade_pct": fade_pct,
                                "next_uid": cue_st["next_uid"],
                            })

                    # E2: OSC OUT — throttled internamente a ≤10 Hz por OscBridge.emit_out
                    osc = getattr(s, "osc_bridge", None)
                    if osc is not None:
                        actx_norm = s._cached_actx.get("norm", {}) if hasattr(s, "_cached_actx") else {}
                        rms_val = float(actx_norm.get("rms", 0.0))
                        osc.emit_out(int(t * 1000), section, beat, rms_val)

                    # I1: record_state — emitir cada ~500ms durante grabación
                    if getattr(s, '_recording', False):
                        if t0 - self._record_emit_t >= 0.5:
                            self._record_emit_t = t0
                            points = sum(
                                len(v) for v in getattr(s, '_recorded_lanes', {}).values()
                            )
                            elapsed = (float(s._current_t_ms) - s._record_start_ms)
                            await self.hub.broadcast_json({
                                "type": "record_state",
                                "recording": True,
                                "elapsed_ms": elapsed,
                                "points": points,
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
