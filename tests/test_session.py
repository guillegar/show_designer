"""
test_session.py — Fase 1 de la migración web.

Verifica que el ShowSession headless (server/session.py) construye sin Qt y que
compute_frame() reproduce la ruta de render del timeline.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.session import ShowSession  # noqa: E402


@pytest.fixture(scope="module")
def session():
    return ShowSession()


def test_session_constructs(session):
    assert session.project is not None
    assert session.timeline is not None
    assert session.show_engine is not None
    assert session.library is not None
    assert session.analysis is not None
    assert session.audio is not None


def test_loads_el_taser_clips(session):
    # El proyecto migrado tiene clips reales
    assert len(session.timeline.clips) > 0
    assert session.bpm > 0
    assert session.duration > 100  # El Taser dura ~273s


def test_compute_frame_shape(session):
    f = session.compute_frame(72.0)
    assert f.shape == (10, 93, 3)
    assert f.dtype == np.uint8


def test_compute_frame_has_light(session):
    # A 72s (zona de drop) debe haber clips activos → algo de luz
    f = session.compute_frame(72.0)
    assert int(f.max()) > 0


def test_transport_clock(session):
    session.stop()
    assert session.playing is False
    assert session.time == 0.0
    assert session.bar_beat(0.0) == (1, 1)


def test_mute_track_silences(session):
    session.muted_tracks = set(range(10))
    f = session.compute_frame(72.0)
    session.muted_tracks = set()
    assert int(f.max()) == 0  # todo silenciado → frame negro
