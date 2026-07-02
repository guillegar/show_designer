"""
osc_bridge.py — OSC bridge (E2, ROADMAP v3): UDP servidor IN + emitter OUT.

OSC IN  (puerto 8001 por defecto) → llama handlers de la sesión:
    /show/go_cue <numero|uid>   → go_cue() o go_next_cue()
    /show/goto_t <ms>           → seek al instante t_ms
    /macro/brightness <0..1>    → brightness_mul = v*2
    /macro/strobe <hz>          → strobe_rate = hz
    /live/trigger <slot_idx>    → live_engine.trigger(idx)
    /live/stop_all              → live_engine.stop_all()

OSC OUT (puerto 8002 por defecto) → emite a clients_out, throttled ≤ 10 Hz:
    /show/t_ms   <int>
    /show/section <str>
    /show/beat   <int>
    /show/rms    <float 0..1>

Config persistida en output_targets.json bajo clave "osc".
Se degrada limpiamente si python-osc no está instalado.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from pythonosc.dispatcher import Dispatcher as OscDispatcher
    from pythonosc.osc_server import AsyncIOOSCUDPServer
    from pythonosc.udp_client import SimpleUDPClient
    _HAVE_OSC = True
except ImportError:
    _HAVE_OSC = False
    log.warning("python-osc no instalado — OSC desactivado. pip install python-osc")


class OscBridge:
    """Servidor UDP OSC + emitter OUT. Instanciado en web.py, accesible desde session."""

    def __init__(self, session, port_in: int = 8001, port_out: int = 8002):
        self._session = session
        self.port_in = port_in
        self.port_out = port_out
        self.enabled = True
        self.clients_out: list[tuple[str, int]] = []
        self._osc_clients: list = []
        self._transport = None
        self._last_out_t: float = -999.0  # asegura que la primera emisión pasa el throttle
        self._recv_log: list[dict] = []

    # ── Ciclo de vida ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        if not _HAVE_OSC or not self.enabled:
            return
        try:
            disp = OscDispatcher()
            disp.map("/show/go_cue", self._on_go_cue)
            disp.map("/show/goto_t", self._on_goto_t)
            disp.map("/macro/brightness", self._on_macro_brightness)
            disp.map("/macro/strobe", self._on_macro_strobe)
            disp.map("/live/trigger", self._on_live_trigger)
            disp.map("/live/stop_all", self._on_live_stop_all)
            disp.set_default_handler(self._on_unknown)
            srv = AsyncIOOSCUDPServer(
                ("0.0.0.0", self.port_in), disp, asyncio.get_event_loop()
            )
            self._transport, _ = await srv.create_serve_endpoint()
            log.info("OSC bridge listo — IN :%-5d  OUT :%d", self.port_in, self.port_out)
        except Exception as exc:
            log.error("OSC start error: %s", exc)

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    # ── Handlers OSC IN ───────────────────────────────────────────────────────

    def _log_recv(self, addr: str, args) -> None:
        self._recv_log.append({"addr": addr, "args": list(args), "ts": round(time.time(), 3)})
        if len(self._recv_log) > 20:
            self._recv_log.pop(0)

    def _on_go_cue(self, addr: str, *args):
        self._log_recv(addr, args)
        s = self._session
        try:
            if not args:
                s.go_next_cue()
                return
            val = args[0]
            entries = s.timeline.cue_list.entries
            if isinstance(val, (int, float)):
                match = next((e for e in entries if abs(e.number - float(val)) < 0.001), None)
                if match:
                    s.go_cue(match.uid)
                else:
                    log.warning("OSC go_cue: cue número %s no encontrada", val)
            else:
                s.go_cue(str(val))
        except Exception as exc:
            log.warning("OSC _on_go_cue: %s", exc)

    def _on_goto_t(self, addr: str, *args):
        self._log_recv(addr, args)
        if args:
            try:
                self._session.audio.seek(float(args[0]) / 1000.0)
            except Exception as exc:
                log.warning("OSC _on_goto_t: %s", exc)

    def _on_macro_brightness(self, addr: str, *args):
        self._log_recv(addr, args)
        if args:
            try:
                v = max(0.0, min(2.0, float(args[0]) * 2.0))
                self._session.macros["brightness_mul"] = v
            except Exception as exc:
                log.warning("OSC _on_macro_brightness: %s", exc)

    def _on_macro_strobe(self, addr: str, *args):
        self._log_recv(addr, args)
        if args:
            try:
                hz = max(0.0, min(30.0, float(args[0])))
                self._session.macros["strobe_rate"] = hz
            except Exception as exc:
                log.warning("OSC _on_macro_strobe: %s", exc)

    def _on_live_trigger(self, addr: str, *args):
        self._log_recv(addr, args)
        if args:
            try:
                idx = int(args[0])
                s = self._session
                s.live_engine.trigger(idx, s.time * 1000.0, s.analysis)
            except Exception as exc:
                log.warning("OSC _on_live_trigger: %s", exc)

    def _on_live_stop_all(self, addr: str, *args):
        self._log_recv(addr, args)
        try:
            self._session.live_engine.stop_all()
        except Exception as exc:
            log.warning("OSC _on_live_stop_all: %s", exc)

    def _on_unknown(self, addr: str, *args):
        self._log_recv(addr, args)
        log.debug("OSC desconocido: %s %s", addr, args)

    # ── Emisión OSC OUT ───────────────────────────────────────────────────────

    def set_clients_out(self, clients: list[tuple[str, int]]) -> None:
        """Actualiza clientes OUT y reconstruye los sockets UDP."""
        self.clients_out = list(clients)
        self._rebuild_osc_clients()

    def _rebuild_osc_clients(self) -> None:
        self._osc_clients = []
        if not _HAVE_OSC:
            return
        for ip, port in self.clients_out:
            try:
                self._osc_clients.append(SimpleUDPClient(ip, port))
            except Exception as exc:
                log.warning("OSC client %s:%d — %s", ip, port, exc)

    def emit_out(self, t_ms: int, section: str, beat: int, rms: float) -> None:
        """Envía telemetría a clients_out. Throttled a ≤ 10 Hz. No-op si sin clientes."""
        if not self._osc_clients:
            return
        now = time.monotonic()
        if now - self._last_out_t < 0.1:
            return
        self._last_out_t = now
        for client in self._osc_clients:
            try:
                client.send_message("/show/t_ms", t_ms)
                client.send_message("/show/section", section or "")
                client.send_message("/show/beat", beat)
                client.send_message("/show/rms", float(rms))
            except Exception as exc:
                log.warning("OSC OUT: %s", exc)

    # ── Config + estado ───────────────────────────────────────────────────────

    def get_state(self) -> dict:
        return {
            "enabled": self.enabled,
            "port_in": self.port_in,
            "port_out": self.port_out,
            "clients_out": [{"ip": ip, "port": p} for ip, p in self.clients_out],
            "recv_log": list(self._recv_log),
            "available": _HAVE_OSC,
            "active": self._transport is not None,
        }

    @classmethod
    def load_config(cls, output_targets_path: Path) -> dict:
        """Lee la sección 'osc' de output_targets.json. Devuelve {} si no existe."""
        try:
            data = json.loads(output_targets_path.read_text(encoding="utf-8"))
            return data.get("osc", {})
        except Exception:
            return {}

    def save_config(self, output_targets_path: Path) -> None:
        """Escribe la sección 'osc' en output_targets.json preservando el resto."""
        try:
            data: dict = {}
            if output_targets_path.is_file():
                try:
                    data = json.loads(output_targets_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, ValueError):
                    data = {}
            data["osc"] = {
                "port_in": self.port_in,
                "port_out": self.port_out,
                "enabled": self.enabled,
                "clients_out": [{"ip": ip, "port": p} for ip, p in self.clients_out],
            }
            tmp = output_targets_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(output_targets_path)
        except Exception as exc:
            log.error("OSC save_config: %s", exc)
