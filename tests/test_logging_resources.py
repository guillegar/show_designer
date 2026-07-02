"""
test_logging_resources.py — ANALYSIS Fase 6 (hallazgos 17 y 18).

Cubre: guardado atómico del timeline, cierre idempotente de recursos (router),
que un fallo de red NO lanza (se loguea), y el throttling del logger.
"""
import logging
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Hallazgo 18: guardado atómico ────────────────────────────────────────────

def test_timeline_save_is_atomic(tmp_path):
    from src.core.timeline_model import Clip, Timeline
    p = tmp_path / "show.json"
    Timeline(clips=[Clip(track=0, start_ms=0, end_ms=100, effect_id=0)]).save(p)
    assert p.is_file()
    # No debe quedar el .tmp tras un guardado correcto
    assert not (tmp_path / "show.json.tmp").exists()
    assert len(Timeline.load(p).clips) == 1


# ── Hallazgo 18: cierre de recursos ──────────────────────────────────────────

def test_output_router_close_idempotent():
    from src.io.outputs.router import OutputRouter, WledTarget
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    r = OutputRouter({1: WledTarget("127.0.0.1", sock=s)})
    r.close()
    assert s.fileno() == -1          # socket cerrado
    r.close()                        # idempotente: no lanza


# ── Hallazgo 17: fallo de red se loguea, no se lanza ─────────────────────────

def test_wled_send_failure_does_not_raise():
    from src.io.outputs.router import WledTarget
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        t = WledTarget("256.256.256.256", sock=s)   # IP inválida → sendto falla
        t.send(1, b"\x00" * 512)                      # NO debe propagar excepción
    finally:
        s.close()


# ── Hallazgo 17: throttling del logger ───────────────────────────────────────

def test_log_throttled_emits_once_per_period():
    from src.log import _last_emit, get_logger, log_throttled
    log = get_logger("test_throttle")
    seen = []
    h = logging.Handler()
    h.emit = lambda rec: seen.append(rec.getMessage())
    log.addHandler(h)
    key = "parity_throttle_key_unique"
    _last_emit.pop(key, None)
    try:
        log_throttled(log, logging.ERROR, key, "primera", period_s=100)
        log_throttled(log, logging.ERROR, key, "segunda", period_s=100)  # throttled
    finally:
        log.removeHandler(h)
    assert seen == ["primera"]
