"""
test_sacn.py — Tests del target sACN (E1.31) en OutputRouter (G1).

Sin red real: se mockea la librería `sacn` completa para que los tests no
requieran hardware ni binding UDP.

Cubre:
  - SacnNodeTarget.send() llama al sender con el universo y 512 bytes correctos.
  - Cierre limpio: close() llama a sender.stop().
  - OutputRouter con entrada sacn en el JSON lo instancia correctamente.
  - Coexistencia Art-Net + sACN en el mismo router.
  - Error de init del sender → no lanza, log throttled.
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call as mcall

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── Helpers / fixtures ───────────────────────────────────────────────────────

def _make_mock_sacn():
    """Devuelve un módulo sacn mockeado con sACNsender funcional."""
    mock_sacn = MagicMock()
    mock_sender = MagicMock()
    mock_output = MagicMock()

    mock_sacn.sACNsender.return_value = mock_sender
    mock_sender.__getitem__ = MagicMock(return_value=mock_output)
    mock_sender.activate_output = MagicMock()
    mock_sender.start = MagicMock()
    mock_sender.stop = MagicMock()
    mock_output.dmx_data = None
    mock_output.destination = None
    mock_output.multicast = False

    return mock_sacn, mock_sender, mock_output


# ── SacnNodeTarget.send ──────────────────────────────────────────────────────

def test_sacn_send_calls_sender_with_correct_data():
    """send() activa el universo y asigna 512 bytes al output."""
    mock_sacn, mock_sender, mock_output = _make_mock_sacn()

    with patch.dict("sys.modules", {"sacn": mock_sacn}):
        from src.io.outputs.router import SacnNodeTarget
        import importlib
        import src.io.outputs.router as router_mod
        importlib.reload(router_mod)

        t = router_mod.SacnNodeTarget(ip="192.168.1.50")
        dmx = bytes(range(256)) + bytes(256)  # 512 bytes
        t.send(universe=1, dmx_bytes=dmx)

        mock_sender.activate_output.assert_called_once_with(1)
        # dmx_data debe ser una tupla de 512 bytes
        out = mock_sender[1]
        assert out.dmx_data is not None
        assert len(out.dmx_data) == 512
        assert out.dmx_data[0] == 0
        assert out.dmx_data[255] == 255


def test_sacn_send_pads_to_512_bytes():
    """Si el payload es < 512 bytes, se rellena con ceros hasta 512."""
    mock_sacn, mock_sender, mock_output = _make_mock_sacn()

    with patch.dict("sys.modules", {"sacn": mock_sacn}):
        import importlib
        import src.io.outputs.router as router_mod
        importlib.reload(router_mod)

        t = router_mod.SacnNodeTarget(ip="10.0.0.1")
        t.send(universe=2, dmx_bytes=b'\xff' * 10)

        out = mock_sender[2]
        assert len(out.dmx_data) == 512
        assert out.dmx_data[:10] == tuple([255] * 10)
        assert out.dmx_data[10] == 0


def test_sacn_sets_destination_unicast():
    """En modo unicast, destination se establece con la IP del target."""
    mock_sacn, mock_sender, mock_output = _make_mock_sacn()

    with patch.dict("sys.modules", {"sacn": mock_sacn}):
        import importlib
        import src.io.outputs.router as router_mod
        importlib.reload(router_mod)

        t = router_mod.SacnNodeTarget(ip="192.168.1.50", multicast=False)
        t.send(universe=3, dmx_bytes=b'\x00' * 512)

        out = mock_sender[3]
        assert out.destination == "192.168.1.50"
        assert out.multicast is False


def test_sacn_multicast_no_destination():
    """En modo multicast, destination no se establece."""
    mock_sacn, mock_sender, mock_output = _make_mock_sacn()

    with patch.dict("sys.modules", {"sacn": mock_sacn}):
        import importlib
        import src.io.outputs.router as router_mod
        importlib.reload(router_mod)

        t = router_mod.SacnNodeTarget(ip="", multicast=True)
        t.send(universe=4, dmx_bytes=b'\x00' * 512)

        out = mock_sender[4]
        # multicast=True se pasa al output, destination no se toca
        assert out.multicast is True


# ── Cierre limpio ────────────────────────────────────────────────────────────

def test_sacn_close_calls_stop():
    """close() llama a sender.stop() para detener el hilo interno."""
    mock_sacn, mock_sender, mock_output = _make_mock_sacn()

    with patch.dict("sys.modules", {"sacn": mock_sacn}):
        import importlib
        import src.io.outputs.router as router_mod
        importlib.reload(router_mod)

        t = router_mod.SacnNodeTarget(ip="192.168.1.50")
        t.close()

        mock_sender.stop.assert_called_once()


def test_sacn_close_idempotent():
    """Llamar a close() dos veces no lanza."""
    mock_sacn, mock_sender, mock_output = _make_mock_sacn()

    with patch.dict("sys.modules", {"sacn": mock_sacn}):
        import importlib
        import src.io.outputs.router as router_mod
        importlib.reload(router_mod)

        t = router_mod.SacnNodeTarget(ip="192.168.1.50")
        t.close()
        t.close()  # segunda llamada no debe lanzar


# ── Carga desde JSON ─────────────────────────────────────────────────────────

def test_output_router_loads_sacn_from_json(tmp_path):
    """OutputRouter instancia SacnNodeTarget cuando el JSON contiene type=sacn."""
    import json
    mock_sacn, mock_sender, mock_output = _make_mock_sacn()

    cfg_file = tmp_path / "output_targets.json"
    cfg_file.write_text(json.dumps({
        "1": {"type": "sacn", "ip": "192.168.1.50"},
    }))

    with patch.dict("sys.modules", {"sacn": mock_sacn}):
        import importlib
        import src.io.outputs.router as router_mod
        importlib.reload(router_mod)

        router = router_mod.OutputRouter.load(cfg_file)
        assert 1 in router.targets
        t = router.targets[1]
        assert isinstance(t, router_mod.SacnNodeTarget)
        assert t.ip == "192.168.1.50"


def test_output_router_coexistence_artnet_sacn(tmp_path):
    """Art-Net (universe 1) y sACN (universe 2) coexisten en el mismo router."""
    import json
    mock_sacn, mock_sender, mock_output = _make_mock_sacn()

    cfg_file = tmp_path / "output_targets.json"
    cfg_file.write_text(json.dumps({
        "1": {"type": "wled", "ip": "192.168.1.201"},
        "2": {"type": "sacn", "ip": "192.168.1.50"},
    }))

    with patch.dict("sys.modules", {"sacn": mock_sacn}):
        import importlib
        import src.io.outputs.router as router_mod
        importlib.reload(router_mod)

        router = router_mod.OutputRouter.load(cfg_file)
        assert isinstance(router.targets[1], router_mod.WledTarget)
        assert isinstance(router.targets[2], router_mod.SacnNodeTarget)


# ── Error de init ────────────────────────────────────────────────────────────

def test_sacn_init_error_no_crash():
    """Si sacn.sACNsender() lanza, SacnNodeTarget no propaga la excepción."""
    mock_sacn = MagicMock()
    mock_sacn.sACNsender.side_effect = RuntimeError("no sacn")

    with patch.dict("sys.modules", {"sacn": mock_sacn}):
        import importlib
        import src.io.outputs.router as router_mod
        importlib.reload(router_mod)

        t = router_mod.SacnNodeTarget(ip="192.168.1.50")
        # send con sender=None → no-op, no lanza
        t.send(universe=1, dmx_bytes=b'\x00' * 512)
        t.close()
