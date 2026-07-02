"""
test_waveform.py — B1: endpoint get_waveform.

Verifica que el handler genera y cachea la forma de onda del audio.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.dispatcher import Dispatcher  # noqa: E402
from server.session import ShowSession  # noqa: E402


@pytest.fixture(scope="module")
def disp():
    return Dispatcher(ShowSession())


def test_get_waveform_basic(disp):
    r = disp.call("get_waveform", {})
    assert r["ok"] is True
    assert r["n_buckets"] == 8000
    assert len(r["peaks_max"]) == 8000
    assert len(r["peaks_min"]) == 8000
    assert len(r["rms"]) == 8000
    assert r["duration_sec"] > 10


def test_waveform_min_le_max(disp):
    r = disp.call("get_waveform", {})
    for mn, mx in zip(r["peaks_min"], r["peaks_max"]):
        assert mn <= mx


def test_waveform_cache_reuse(disp):
    r1 = disp.call("get_waveform", {})
    r2 = disp.call("get_waveform", {})
    assert r1["peaks_max"][:10] == r2["peaks_max"][:10]
    assert r1["duration_sec"] == r2["duration_sec"]


def test_waveform_range_valid(disp):
    r = disp.call("get_waveform", {})
    for v in r["peaks_max"]:
        assert -1.1 <= v <= 1.1
    for v in r["peaks_min"]:
        assert -1.1 <= v <= 1.1
    for v in r["rms"]:
        assert 0.0 <= v <= 1.1


def test_ensure_waveform_cached_writes_cache(disp):
    """El helper bloqueante (el que corre en el executor) devuelve los datos y
    deja escrito waveform.json en el analysis_dir."""
    from server.dispatcher import _ensure_waveform_cached
    data = _ensure_waveform_cached(disp.session)
    assert data is not None
    assert data["n_buckets"] == 8000
    cache = disp.session.analysis.analysis_dir / "waveform.json"
    assert cache.is_file()


def test_get_waveform_async_does_not_block(tmp_path, monkeypatch):
    """Con un event loop corriendo (como en el server web), get_waveform NO
    calcula inline: devuelve {status:'computing'} al instante y emite
    'waveform_ready' por el hub cuando el job del executor termina. Se conduce
    el loop a mano para no depender de pytest-asyncio (no está en el venv)."""
    from server.handlers import waveform as W

    sess = ShowSession()
    # analysis_dir limpio → sin cache → fuerza la rama asíncrona "computing".
    # analysis_dir es una property sin setter → se parchea a nivel de clase.
    monkeypatch.setattr(type(sess.analysis), "analysis_dir",
                        property(lambda self: tmp_path))

    fake = {"peaks_max": [0.1], "peaks_min": [-0.1], "rms": [0.05],
            "n_buckets": 1, "duration_sec": 1.0, "bpm": 120.0}

    def _fake_ensure(session):
        (tmp_path / "waveform.json").write_text("{}", encoding="utf-8")
        return fake
    monkeypatch.setattr(W, "_ensure_waveform_cached", _fake_ensure)

    events = []

    class _Hub:
        async def broadcast_json(self, obj):
            events.append(obj)

    sess.hub = _Hub()
    disp = Dispatcher(sess)

    loop = asyncio.new_event_loop()
    try:
        async def _run():
            r = disp.call("get_waveform", {})
            assert r["ok"] is True
            assert r.get("status") == "computing"
            # esperar a que el job del executor termine y emita el evento
            for _ in range(100):
                if events:
                    break
                await asyncio.sleep(0.02)
        loop.run_until_complete(_run())
    finally:
        loop.close()

    assert any(e.get("type") == "waveform_ready" for e in events)
    assert (tmp_path / "waveform.json").is_file()
