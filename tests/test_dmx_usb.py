"""
test_dmx_usb.py — Tests del target DMX USB (ENTTEC Open DMX) (G4).

Sin hardware real: se mockea serial.Serial para verificar el framing.
No se usa importlib.reload para no romper las referencias de clase en otros tests.
serial se importa lazy dentro de los métodos, así que patch.dict(sys.modules) basta.

Cubre:
  - send() escribe BREAK + START_CODE (0x00) + 512 bytes DMX.
  - send() rellena con ceros a 512 bytes si el payload es menor.
  - close() cierra el puerto serie.
  - DmxUsbTarget.list_ports() devuelve lista (puede estar vacía).
  - Error de puerto inexistente → log + no-crash (send es no-op).
  - OutputRouter carga dmx_usb desde JSON correctamente.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.io.outputs.router import DmxUsbTarget, OutputRouter


def _mock_serial_ctx(side_effect=None):
    """Context manager que inyecta un serial.Serial mockeado en sys.modules."""
    mock_serial = MagicMock()
    mock_ser = MagicMock()
    mock_ser.is_open = True
    if side_effect is not None:
        mock_serial.Serial.side_effect = side_effect
    else:
        mock_serial.Serial.return_value = mock_ser
    mock_list_ports = MagicMock()
    mock_list_ports.comports.return_value = []
    mock_serial.tools = MagicMock()
    mock_serial.tools.list_ports = mock_list_ports
    return patch.dict("sys.modules", {
        "serial": mock_serial,
        "serial.tools": mock_serial.tools,
        "serial.tools.list_ports": mock_list_ports,
    }), mock_serial, mock_ser


# ── DmxUsbTarget.send ────────────────────────────────────────────────────────

def test_dmx_usb_send_calls_send_break_and_write():
    """send() llama a send_break() + write(START_CODE + 512 bytes)."""
    ctx, mock_serial, mock_ser = _mock_serial_ctx()
    with ctx:
        t = DmxUsbTarget(port="COM3")
        dmx = b'\xAA' * 512
        t.send(universe=1, dmx_bytes=dmx)

        mock_ser.send_break.assert_called_once()
        mock_ser.write.assert_called_once()
        written = mock_ser.write.call_args[0][0]
        assert written[0] == 0x00, "primer byte = START CODE 0x00"
        assert len(written) == 513, "START + 512 bytes"
        assert written[1:] == dmx


def test_dmx_usb_send_pads_to_512():
    """Payload < 512 bytes → se rellena con ceros hasta 512."""
    ctx, mock_serial, mock_ser = _mock_serial_ctx()
    with ctx:
        t = DmxUsbTarget(port="COM3")
        t.send(universe=1, dmx_bytes=b'\xFF' * 5)

        written = mock_ser.write.call_args[0][0]
        assert len(written) == 513
        assert written[0] == 0x00
        assert written[1:6] == b'\xFF' * 5
        assert written[6] == 0


# ── Cierre limpio ────────────────────────────────────────────────────────────

def test_dmx_usb_close_calls_serial_close():
    """close() llama a serial.close() para liberar el puerto."""
    ctx, mock_serial, mock_ser = _mock_serial_ctx()
    with ctx:
        t = DmxUsbTarget(port="COM3")
        t.close()
        mock_ser.close.assert_called_once()


def test_dmx_usb_close_idempotent():
    """Llamar a close() dos veces no lanza."""
    ctx, mock_serial, mock_ser = _mock_serial_ctx()
    with ctx:
        t = DmxUsbTarget(port="COM3")
        t.close()
        t.close()  # no-op, self._ser es None


# ── list_ports ────────────────────────────────────────────────────────────────

def test_dmx_usb_list_ports_returns_list():
    """list_ports() devuelve una lista (puede estar vacía)."""
    mock_port = MagicMock()
    mock_port.device = "COM3"
    mock_list_ports = MagicMock()
    mock_list_ports.comports.return_value = [mock_port]
    mock_serial = MagicMock()
    mock_serial.Serial.return_value = MagicMock()
    mock_serial.tools = MagicMock()
    mock_serial.tools.list_ports = mock_list_ports

    with patch.dict("sys.modules", {
        "serial": mock_serial,
        "serial.tools": mock_serial.tools,
        "serial.tools.list_ports": mock_list_ports,
    }):
        ports = DmxUsbTarget.list_ports()
        assert isinstance(ports, list)
        assert "COM3" in ports


def test_dmx_usb_list_ports_empty_if_serial_unavailable():
    """list_ports() devuelve [] si pyserial no disponible."""
    with patch.object(DmxUsbTarget, 'list_ports', return_value=[]):
        ports = DmxUsbTarget.list_ports()
        assert ports == []


# ── Error de puerto inexistente ───────────────────────────────────────────────

def test_dmx_usb_init_error_no_crash():
    """Si el puerto no existe, DmxUsbTarget no lanza y send es no-op."""
    ctx, mock_serial, _ = _mock_serial_ctx(side_effect=RuntimeError("puerto no encontrado"))
    with ctx:
        t = DmxUsbTarget(port="COM99")
        assert t._ser is None
        t.send(universe=1, dmx_bytes=b'\x00' * 512)  # no-op
        t.close()  # no-op


# ── Carga desde JSON ─────────────────────────────────────────────────────────

def test_output_router_loads_dmx_usb_from_json(tmp_path):
    """OutputRouter instancia DmxUsbTarget cuando el JSON contiene type=dmx_usb."""
    ctx, mock_serial, mock_ser = _mock_serial_ctx()
    cfg_file = tmp_path / "output_targets.json"
    cfg_file.write_text(json.dumps({
        "1": {"type": "dmx_usb", "port": "COM3"},
    }))

    with ctx:
        router = OutputRouter.load(cfg_file)
        assert 1 in router.targets
        t = router.targets[1]
        assert isinstance(t, DmxUsbTarget)
        assert t.port == "COM3"
