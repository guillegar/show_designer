"""
test_osc_bridge.py — Tests E2: OSC bridge (ROADMAP v3).

Cubre:
  - /live/trigger <idx> → live_engine.trigger llamado con idx correcto
  - Mensaje malformado → log + no-crash
  - Throttle OUT: 100 llamadas rápidas → ≤ 40 send_message (≤ 10 disparos × 4 mensajes)
  - start/stop no bloquean el event loop (I4)
  - get_state devuelve estructura correcta
  - osc_get_state handler con bridge None
  - osc_set_config actualiza clients_out y guarda config
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.osc_bridge import OscBridge


def make_mock_session():
    session = MagicMock()
    session.time = 0.0
    session.analysis = MagicMock()
    session.timeline.cue_list.entries = []
    session.macros = {"brightness_mul": 1.0, "strobe_rate": 0.0}
    session.live_engine = MagicMock()
    session.audio = MagicMock()
    session.osc_bridge = None
    return session


# ── 1. /live/trigger → live_engine.trigger ────────────────────────────────────

def test_live_trigger_calls_engine():
    """/live/trigger 3 → live_engine.trigger(3, ...) llamado."""
    session = make_mock_session()
    bridge = OscBridge(session)
    bridge._on_live_trigger("/live/trigger", 3)
    session.live_engine.trigger.assert_called_once()
    call_args = session.live_engine.trigger.call_args
    assert call_args[0][0] == 3  # primer argumento posicional = slot_idx


# ── 2. Mensajes malformados → no-crash ───────────────────────────────────────

def test_malformed_no_crash():
    """Args inválidos en cualquier handler → log pero no lanza excepción."""
    session = make_mock_session()
    bridge = OscBridge(session)

    # go_cue con tipo no convertible
    bridge._on_go_cue("/show/go_cue", object())  # no es int/float/str útil
    # goto_t con string no numérico
    bridge._on_goto_t("/show/goto_t", "no-un-número")
    # live_trigger con float que no convierte bien
    bridge._on_live_trigger("/live/trigger", "abc")
    # macro_brightness con None
    bridge._on_macro_brightness("/macro/brightness", None)
    # macro_strobe sin args
    bridge._on_macro_strobe("/macro/strobe")
    # Todo lo anterior: no exception → pass


# ── 3. Throttle OUT ≤ 10 Hz ──────────────────────────────────────────────────

def test_throttle_out():
    """100 emit_out a t=0 → send_message llamado ≤ 40 veces (≤ 10 disparos × 4 msjs)."""
    session = make_mock_session()
    bridge = OscBridge(session)

    mock_client = MagicMock()
    bridge._osc_clients = [mock_client]
    bridge._last_out_t = -999.0  # garantiza que la primera pasa

    with patch("server.osc_bridge.time.monotonic", return_value=0.0):
        for _ in range(100):
            bridge.emit_out(1000, "intro", 1, 0.5)

    # Solo el primer emit_out pasa el throttle (todos a t=0.0, diff < 0.1 → bloqueados)
    assert mock_client.send_message.call_count <= 40


# ── 4. start/stop no bloquean el event loop (I4) ─────────────────────────────

def test_start_stop_nonblocking():
    """start() y stop() son corutinas que completan en < 500ms (no bloquean)."""
    session = make_mock_session()
    bridge = OscBridge(session)

    async def run():
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        await bridge.start()   # puede ser no-op si _HAVE_OSC=False o port en uso
        await bridge.stop()
        return loop.time() - t0

    elapsed = asyncio.run(run())
    assert elapsed < 0.5


# ── 5. get_state ──────────────────────────────────────────────────────────────

def test_get_state_structure():
    """get_state() devuelve dict con las claves esperadas."""
    session = make_mock_session()
    bridge = OscBridge(session, port_in=9001, port_out=9002)
    state = bridge.get_state()
    assert state["port_in"] == 9001
    assert state["port_out"] == 9002
    assert isinstance(state["clients_out"], list)
    assert isinstance(state["recv_log"], list)
    assert "enabled" in state
    assert "available" in state
    assert "active" in state


# ── 6. osc_get_state handler sin bridge ──────────────────────────────────────

def test_osc_get_state_handler_no_bridge():
    """osc_get_state con osc_bridge=None → ok=True + enabled=False."""
    from server.dispatcher import _LOCAL
    session = make_mock_session()
    session.osc_bridge = None
    result = _LOCAL["osc_get_state"](session, {})
    assert result["ok"] is True
    assert result["enabled"] is False


# ── 7. osc_set_config actualiza clients_out ──────────────────────────────────

def test_osc_set_config_updates_clients():
    """osc_set_config con clients_out → bridge.clients_out actualizado y guardado."""
    from server.dispatcher import _LOCAL
    session = make_mock_session()
    bridge = OscBridge(session)
    session.osc_bridge = bridge

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({"1": {"type": "sim_only"}}, f)
        tmp = Path(f.name)

    try:
        with patch("server.dispatcher.Path") as mock_path_cls:
            mock_path_cls.return_value.__truediv__ = lambda s, o: tmp
            # patch Path(__file__).resolve().parent.parent / "output_targets.json"
            with patch("server.osc_bridge.Path", Path):
                # Llamar directamente con el path real
                params = {"clients_out": [{"ip": "192.168.1.50", "port": 8002}]}
                # Parcheamos save_config para no tocar el archivo real
                bridge.save_config = MagicMock()
                result = _LOCAL["osc_set_config"](session, params)
                assert result["ok"] is True
                assert len(bridge.clients_out) == 1
                assert bridge.clients_out[0] == ("192.168.1.50", 8002)
    finally:
        tmp.unlink(missing_ok=True)


# ── 8. save_config / load_config roundtrip ───────────────────────────────────

def test_config_roundtrip():
    """save_config → load_config devuelve mismos valores."""
    session = make_mock_session()
    bridge = OscBridge(session, port_in=7001, port_out=7002)
    bridge.enabled = False
    bridge.set_clients_out([("10.0.0.1", 9000)])

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = Path(f.name)

    try:
        bridge.save_config(tmp)
        cfg = OscBridge.load_config(tmp)
        assert cfg["port_in"] == 7001
        assert cfg["port_out"] == 7002
        assert cfg["enabled"] is False
        assert cfg["clients_out"] == [{"ip": "10.0.0.1", "port": 9000}]
    finally:
        tmp.unlink(missing_ok=True)
