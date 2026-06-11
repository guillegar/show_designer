"""
outputs/router.py — Routing de universos DMX a destinos físicos / simulados.

Cada universo del rig se enruta a un OutputTarget:
  • WledTarget(ip)         → envía Art-Net OpDmx a ip:6454 (modelo WLED actual).
  • ArtnetNodeTarget(ip)   → idem pero conceptualmente para un nodo Art-Net→DMX
                             físico que recibe N universos en una IP. STUB de
                             momento, mismo paquete que WLED.
  • SimOnlyTarget()        → NO envía nada por red. Guarda el último bytes(512)
                             en memoria para inspección y para el broadcast al
                             viewer 3D.

El mapeo universo → target se lee desde `output_targets.json` (config persistida).
Si un universo no aparece en el JSON → fallback a sim_only.

Uso:
    router = OutputRouter.load(Path('output_targets.json'))
    router.send(universe=1, dmx_bytes=b'\\x00' * 512)
    last = router.last_sent_for(universe=11)  # útil para viewer 3D + tests
"""
from __future__ import annotations

import json
import logging
import socket
import struct
from pathlib import Path
from typing import Dict, Optional

from src.log import get_logger, log_throttled

_log = get_logger(__name__)


# ───────────────────────────────────────────────────────────────
# Art-Net packet builder (compartido entre WLED y artnet_node)
# ───────────────────────────────────────────────────────────────

def build_artnet_packet(universe: int, dmx_payload: bytes) -> bytes:
    """Paquete Art-Net OpDmx (0x5000) estándar de 512 bytes."""
    dmx = bytearray(512)
    dmx[:len(dmx_payload)] = dmx_payload
    return (
        b'Art-Net\x00'
        + struct.pack('<H', 0x5000)
        + struct.pack('>H', 14)        # protocol version
        + b'\x00\x00'                  # sequence + physical
        + struct.pack('<H', universe)  # universe (little-endian)
        + struct.pack('>H', 512)       # data length (big-endian)
        + bytes(dmx)
    )


# ───────────────────────────────────────────────────────────────
# OutputTarget base + implementaciones
# ───────────────────────────────────────────────────────────────

class OutputTarget:
    """Interfaz base."""
    type_name: str = "base"

    def send(self, universe: int, dmx_bytes: bytes) -> None:
        raise NotImplementedError

    def describe(self) -> Dict:
        return {"type": self.type_name}


class WledTarget(OutputTarget):
    """Art-Net directo a la IP de un WLED (1 universo por IP)."""
    type_name = "wled"

    def __init__(self, ip: str, sock: Optional[socket.socket] = None):
        self.ip = str(ip)
        self._sock = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, universe: int, dmx_bytes: bytes) -> None:
        try:
            pkt = build_artnet_packet(universe, dmx_bytes)
            self._sock.sendto(pkt, (self.ip, 6454))
        except Exception as e:
            # No matar el render loop, pero NO silenciar (ANALYSIS hallazgo 17):
            # log throttled 1/s por IP. Antes era `pass` mudo → "no funciona y no
            # dice nada" cuando la IP estaba mal configurada.
            log_throttled(_log, logging.ERROR, f"wled:{self.ip}",
                          f"Art-Net a WLED {self.ip} falló: {e}")

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass

    def describe(self) -> Dict:
        return {"type": "wled", "ip": self.ip}


class ArtnetNodeTarget(OutputTarget):
    """Nodo Art-Net→DMX físico que recibe N universos en una IP.

    Stub por ahora — implementación idéntica a WledTarget. Cuando llegue
    el nodo físico (ENTTEC ODE, Open-Lighting node, etc.) puede que haya
    que añadir alguna negociación o ajustar el universo (1-based vs 0-based,
    subnet etc.) pero el formato del paquete es el mismo.
    """
    type_name = "artnet_node"

    def __init__(self, ip: str, sock: Optional[socket.socket] = None):
        self.ip = str(ip)
        self._sock = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, universe: int, dmx_bytes: bytes) -> None:
        try:
            pkt = build_artnet_packet(universe, dmx_bytes)
            self._sock.sendto(pkt, (self.ip, 6454))
        except Exception as e:
            log_throttled(_log, logging.ERROR, f"artnet_node:{self.ip}",
                          f"Art-Net a nodo {self.ip} falló: {e}")

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass

    def describe(self) -> Dict:
        return {"type": "artnet_node", "ip": self.ip}


class SimOnlyTarget(OutputTarget):
    """No envía nada por red. Mantiene el último bytes(512) para inspección
    (viewer 3D, tests, debug MCP)."""
    type_name = "sim_only"

    def __init__(self):
        self._last: Dict[int, bytes] = {}

    def send(self, universe: int, dmx_bytes: bytes) -> None:
        self._last[int(universe)] = bytes(dmx_bytes)

    def last_for(self, universe: int) -> Optional[bytes]:
        return self._last.get(int(universe))


# ───────────────────────────────────────────────────────────────
# OutputRouter — gestiona la tabla universe → target
# ───────────────────────────────────────────────────────────────

class OutputRouter:
    """Tabla universe → OutputTarget. Universos no presentes caen a
    SimOnlyTarget compartido."""

    def __init__(self, targets: Optional[Dict[int, OutputTarget]] = None):
        self.targets: Dict[int, OutputTarget] = dict(targets or {})
        # SimOnly fallback compartido — mantiene historial para todos los
        # universos no enrutados explícitamente.
        self._sim_fallback = SimOnlyTarget()

    @classmethod
    def load(cls, path: Path) -> 'OutputRouter':
        """Carga el mapping desde output_targets.json.

        Formato:
        {
          "1": {"type": "wled", "ip": "192.168.1.201"},
          "11": {"type": "sim_only"},
          ...
        }
        """
        path = Path(path)
        if not path.is_file():
            _log.warning("%s no existe, fallback total a sim_only", path)
            return cls()
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            _log.error("error leyendo %s: %s", path, e)
            return cls()

        # Compartir socket entre WLED/ArtnetNode targets para evitar saturar
        # el sistema con N sockets UDP.
        shared_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        targets: Dict[int, OutputTarget] = {}
        for uni_str, cfg in data.items():
            try:
                uni = int(uni_str)
            except ValueError:
                continue
            ttype = cfg.get("type", "sim_only")
            if ttype == "wled":
                targets[uni] = WledTarget(cfg["ip"], sock=shared_sock)
            elif ttype == "artnet_node":
                targets[uni] = ArtnetNodeTarget(cfg["ip"], sock=shared_sock)
            elif ttype == "sim_only":
                targets[uni] = SimOnlyTarget()
            else:
                _log.warning("tipo desconocido %r en univ %s, fallback sim_only",
                             ttype, uni)
                targets[uni] = SimOnlyTarget()
        return cls(targets)

    def send(self, universe: int, dmx_bytes: bytes) -> None:
        """Enruta los 512 bytes del universo al target configurado."""
        target = self.targets.get(int(universe))
        if target is None:
            self._sim_fallback.send(universe, dmx_bytes)
        else:
            target.send(universe, dmx_bytes)

    def close(self) -> None:
        """Cierra los sockets de los targets (ANALYSIS hallazgo 18). Idempotente
        (cerrar un socket ya cerrado es no-op; targets que comparten socket no
        rompen)."""
        for target in self.targets.values():
            closer = getattr(target, "close", None)
            if callable(closer):
                closer()

    def last_sent_for(self, universe: int) -> Optional[bytes]:
        """Para tests/viewer3d: devuelve el último bytes(512) enviado a este
        universo, **si el target lo guarda** (SimOnly sí, otros no).
        """
        target = self.targets.get(int(universe))
        if target is None:
            return self._sim_fallback.last_for(universe)
        if isinstance(target, SimOnlyTarget):
            return target.last_for(universe)
        return None

    def describe(self) -> Dict:
        """Snapshot del routing — útil para debug MCP."""
        return {
            "targets": {
                str(u): t.describe() for u, t in self.targets.items()
            },
            "fallback": "sim_only",
        }
