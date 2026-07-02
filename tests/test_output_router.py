"""
Tests del OutputRouter (outputs/router.py).

Cubre:
  - Carga del routing desde output_targets.json
  - Universos sin entrada caen a sim_only fallback
  - WledTarget construye el paquete Art-Net correcto (sin hacer envío real)
  - SimOnlyTarget guarda el último DMX por universo
  - describe() devuelve snapshot inspeccionable

Lanzar:
    pytest tests/test_output_router.py -v
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.io.outputs.router import (  # noqa: E402
    ArtnetNodeTarget,
    OutputRouter,
    SimOnlyTarget,
    WledTarget,
    build_artnet_packet,
)

# ────────────────────────────────────────────────────────────────
# build_artnet_packet
# ────────────────────────────────────────────────────────────────

def test_artnet_packet_header():
    pkt = build_artnet_packet(universe=1, dmx_payload=b'\x10\x20\x30')
    assert pkt[:8] == b'Art-Net\x00'
    # Total: 8 header + 2 opcode + 2 protover + 2 seq/phys + 2 universe + 2 length + 512 data = 530
    assert len(pkt) == 530


def test_artnet_packet_padding_to_512():
    pkt = build_artnet_packet(universe=5, dmx_payload=b'\xff' * 3)
    # Los primeros 3 bytes de DMX son 0xff, el resto 0x00
    dmx = pkt[18:]
    assert dmx[:3] == b'\xff\xff\xff'
    assert dmx[3:] == b'\x00' * 509


def test_artnet_packet_universe_encoded():
    pkt = build_artnet_packet(universe=11, dmx_payload=b'')
    # Universe va a partir del byte 14 (8 header + 2 opcode + 2 ver + 2 seq/phys)
    # little-endian 16 bits
    assert pkt[14:16] == bytes([11, 0])


# ────────────────────────────────────────────────────────────────
# SimOnlyTarget
# ────────────────────────────────────────────────────────────────

def test_sim_only_stores_last():
    t = SimOnlyTarget()
    assert t.last_for(1) is None
    t.send(1, b'\x01\x02\x03')
    assert t.last_for(1) == b'\x01\x02\x03'
    t.send(1, b'\xff' * 5)
    assert t.last_for(1) == b'\xff' * 5


def test_sim_only_multi_universe():
    t = SimOnlyTarget()
    t.send(1, b'a')
    t.send(2, b'b')
    t.send(11, b'c')
    assert t.last_for(1) == b'a'
    assert t.last_for(2) == b'b'
    assert t.last_for(11) == b'c'


def test_sim_only_describe():
    t = SimOnlyTarget()
    assert t.describe() == {"type": "sim_only"}


# ────────────────────────────────────────────────────────────────
# WledTarget — verificamos construcción y describe sin hacer envío real
# ────────────────────────────────────────────────────────────────

def test_wled_describe():
    t = WledTarget("192.168.1.201")
    assert t.describe() == {"type": "wled", "ip": "192.168.1.201"}


def test_wled_send_does_not_raise(monkeypatch):
    """Envío a IP que no escucha no debe lanzar (sólo silenciar)."""
    t = WledTarget("127.0.0.1")
    # No vamos a tener nadie escuchando en 6454 — el target debe tragarse el error
    try:
        t.send(1, b'\x00' * 100)
    except Exception:
        pytest.fail("WledTarget.send no debe propagar excepciones")


def test_artnet_node_describe():
    t = ArtnetNodeTarget("192.168.1.50")
    assert t.describe() == {"type": "artnet_node", "ip": "192.168.1.50"}


# ────────────────────────────────────────────────────────────────
# OutputRouter
# ────────────────────────────────────────────────────────────────

@pytest.fixture
def router_config(tmp_path):
    cfg = {
        "1": {"type": "wled", "ip": "192.168.1.201"},
        "2": {"type": "wled", "ip": "192.168.1.202"},
        "11": {"type": "sim_only"},
        "12": {"type": "artnet_node", "ip": "192.168.1.50"},
    }
    p = tmp_path / "output_targets.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def test_router_load(router_config):
    r = OutputRouter.load(router_config)
    assert isinstance(r.targets[1], WledTarget)
    assert isinstance(r.targets[2], WledTarget)
    assert isinstance(r.targets[11], SimOnlyTarget)
    assert isinstance(r.targets[12], ArtnetNodeTarget)


def test_router_load_missing_file_falls_back(tmp_path):
    """Si no existe el JSON, el router se inicializa vacío (todo a sim_only)."""
    r = OutputRouter.load(tmp_path / "noexiste.json")
    assert r.targets == {}
    # Pero send() sigue funcionando vía fallback
    r.send(1, b'\xaa')
    assert r.last_sent_for(1) == b'\xaa'


def test_router_send_to_sim_only(router_config):
    r = OutputRouter.load(router_config)
    r.send(11, b'\x10\x20\x30')
    assert r.last_sent_for(11) == b'\x10\x20\x30'


def test_router_send_unmapped_universe_falls_back_sim(router_config):
    r = OutputRouter.load(router_config)
    r.send(99, b'\xff' * 50)
    # Univ 99 no está en config → fallback a sim_only
    assert r.last_sent_for(99) == b'\xff' * 50


def test_router_wled_returns_none_for_last(router_config):
    """WledTarget no guarda historial (envía y olvida)."""
    r = OutputRouter.load(router_config)
    r.send(1, b'\xaa' * 10)
    assert r.last_sent_for(1) is None


def test_router_describe_snapshot(router_config):
    r = OutputRouter.load(router_config)
    d = r.describe()
    assert "targets" in d
    assert d["fallback"] == "sim_only"
    assert d["targets"]["1"] == {"type": "wled", "ip": "192.168.1.201"}
    assert d["targets"]["11"] == {"type": "sim_only"}


def test_router_load_unknown_type_falls_to_sim(tmp_path):
    """Tipo desconocido en config → cae a sim_only sin crashear."""
    cfg = {"5": {"type": "espectro_imaginario", "ip": "1.2.3.4"}}
    p = tmp_path / "output_targets.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    r = OutputRouter.load(p)
    assert isinstance(r.targets[5], SimOnlyTarget)
