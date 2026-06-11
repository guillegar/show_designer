"""
test_clip_uid.py — ANALYSIS hallazgo 2: IDs de clips estables y persistidos.

Verifica que `Clip.uid` reemplaza al frágil `id(self)`: es un string estable,
se serializa, sobrevive a save/load, migra shows viejos, y los lookups
(`ShowSession.find_clip_by_id`) lo aceptan + el int legacy por compat.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.timeline_model import Clip, Timeline  # noqa: E402


# ── El campo uid ─────────────────────────────────────────────────────────────

def test_clip_has_unique_string_uid():
    a = Clip(track=0, start_ms=0, end_ms=1000, effect_id=1)
    b = Clip(track=0, start_ms=0, end_ms=1000, effect_id=1)
    assert isinstance(a.uid, str) and len(a.uid) == 12
    assert a.uid != b.uid  # cada clip tiene un uid propio


def test_to_dict_id_is_the_uid():
    c = Clip(track=2, start_ms=0, end_ms=500, effect_id=3)
    d = c.to_dict()
    # `id` (clave que leen Claude/web) y `uid` apuntan ambos al uid string
    assert d["id"] == c.uid
    assert d["uid"] == c.uid
    assert isinstance(d["id"], str)


# ── Round-trip y migración ───────────────────────────────────────────────────

def test_from_dict_roundtrip_preserves_uid():
    c = Clip(track=1, start_ms=100, end_ms=900, effect_id=5)
    c2 = Clip.from_dict(c.to_dict())
    assert c2.uid == c.uid


def test_from_dict_migrates_legacy_int_id():
    # Show viejo: "id" era el entero de id(self) y no había "uid".
    legacy = {"id": 140523456789012, "track": 0, "start_ms": 0,
              "end_ms": 1000, "effect_id": 0}
    c = Clip.from_dict(legacy)
    assert isinstance(c.uid, str) and len(c.uid) == 12  # uid nuevo generado
    assert c.uid != "140523456789012"


def test_from_dict_without_any_id_generates_uid():
    c = Clip.from_dict({"track": 0, "start_ms": 0, "end_ms": 1000, "effect_id": 0})
    assert isinstance(c.uid, str) and len(c.uid) == 12


def test_timeline_save_load_preserves_uid(tmp_path):
    c = Clip(track=0, start_ms=0, end_ms=1000, effect_id=1)
    Timeline(clips=[c]).save(tmp_path / "show.json")
    loaded = Timeline.load(tmp_path / "show.json")
    assert len(loaded.clips) == 1
    assert loaded.clips[0].uid == c.uid  # uid sobrevive al JSON


# ── Lookup en la sesión headless (uid + compat int legacy) ───────────────────

@pytest.fixture(scope="module")
def session():
    from server.session import ShowSession
    return ShowSession()


def test_session_find_clip_by_uid(session):
    if not session.timeline.clips:
        pytest.skip("proyecto sin clips")
    target = session.timeline.clips[0]
    assert session.find_clip_by_id(target.uid) is target


def test_session_find_clip_legacy_int_fallback(session):
    if not session.timeline.clips:
        pytest.skip("proyecto sin clips")
    target = session.timeline.clips[0]
    # Cliente que guardó el id(objeto) entero antiguo: aún debe resolver.
    assert session.find_clip_by_id(id(target)) is target


def test_session_find_clip_missing_returns_none(session):
    assert session.find_clip_by_id("nonexistent_uid") is None
    assert session.find_clip_by_id(999999999) is None
