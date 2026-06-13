"""
test_waveform.py — B1: endpoint get_waveform.

Verifica que el handler genera y cachea la forma de onda del audio.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.session import ShowSession  # noqa: E402
from server.dispatcher import Dispatcher  # noqa: E402


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
