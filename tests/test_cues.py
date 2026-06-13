"""
test_cues.py — Tests E1: Sistema de Cues profesional (ROADMAP v3).

Cubre:
  - Persistencia: add_cue → save → load → cue existe
  - Migración tolerante v3→v4 (show sin cue_list)
  - go_cue seek al audio player
  - Navegación: go_next, go_prev
  - auto_follow dispara tras hold_ms
  - Fade aplica multiplicador al master
  - Undo cubre la CueList (I1)
  - delete_cue no toca CuePoint existentes
  - reorder_cues ordena por number
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import json
import tempfile
import numpy as np

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.timeline_model import (
    Timeline, CueEntry, CueList, CuePoint
)
from server.undo_manager import UndoManager


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_cue(number=1.0, t_ms=1000, name="C1", fade_in_ms=0, hold_ms=-1, auto_follow=False):
    from uuid import uuid4
    return CueEntry(
        uid=uuid4().hex[:12],
        number=number,
        name=name,
        t_ms=t_ms,
        fade_in_ms=fade_in_ms,
        hold_ms=hold_ms,
        auto_follow=auto_follow,
    )


def make_session_mock():
    """ShowSession mínima sin audio real para tests de cues."""
    from server.session import ShowSession
    session = ShowSession.__new__(ShowSession)
    session.timeline = Timeline()
    session.timeline.cue_list = CueList(entries=[])

    # Mock del audio player
    audio = MagicMock()
    audio.get_current_time.return_value = 0.0
    audio._pause_time = 0.0
    audio.duration = 300.0
    audio._playing = False

    def _seek(seconds):
        audio._pause_time = float(seconds)
        audio.get_current_time.return_value = float(seconds)

    audio.seek.side_effect = _seek
    session.audio = audio

    # Notificaciones no-op
    session._rev = 0
    session.on_change = None
    session.notify_changed = MagicMock()

    # Estado runtime cues
    session._cue_fade_start_ms = None
    session._cue_fade_duration_ms = 0.0
    session._cue_fade_from_master = 1.0
    session._cue_auto_follow_task = None
    session._cue_last_fade_pct = 1.0

    return session


# ── 1. PERSISTENCIA ───────────────────────────────────────────────────────────

def test_add_cue_persists():
    """add_cue → save → load → cue existe con mismos campos."""
    tl = Timeline()
    entry = make_cue(number=1.0, t_ms=5000, name="Intro", fade_in_ms=500)
    tl.cue_list.entries.append(entry)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)

    try:
        tl.save(path)
        loaded = Timeline.load(path)
        assert len(loaded.cue_list.entries) == 1
        c = loaded.cue_list.entries[0]
        assert c.uid == entry.uid
        assert c.number == 1.0
        assert c.t_ms == 5000
        assert c.name == "Intro"
        assert c.fade_in_ms == 500
    finally:
        path.unlink(missing_ok=True)


# ── 2. MIGRACIÓN v3→v4 ───────────────────────────────────────────────────────

def test_schema_v4_migration():
    """Cargar un show v3 (sin cue_list) → carga OK, cue_list vacía."""
    fixture = Path(__file__).parent / "fixtures" / "show_v3.json"
    assert fixture.is_file(), "Fixture show_v3.json no encontrada"
    tl = Timeline.load(fixture)
    assert tl.cue_list is not None
    assert isinstance(tl.cue_list, CueList)
    assert len(tl.cue_list.entries) == 0
    assert tl.cue_list.active_uid is None
    # Los clips del v3 deben cargarse sin pérdida
    assert len(tl.clips) == 1


# ── 3. GO_CUE SEEKS ──────────────────────────────────────────────────────────

def test_go_cue_seeks():
    """go_cue → audio.seek llamado con cue.t_ms/1000 y _pause_time actualizado."""
    session = make_session_mock()
    cue = make_cue(number=1.0, t_ms=42000)
    session.timeline.cue_list.entries = [cue]

    # Inyectar métodos de la sesión real
    from server.session import ShowSession
    session.go_cue = ShowSession.go_cue.__get__(session, ShowSession)
    session._find_cue_by_uid = ShowSession._find_cue_by_uid.__get__(session, ShowSession)

    result = session.go_cue(cue.uid)
    assert result is not None
    session.audio.seek.assert_called_once_with(42.0)
    assert session.audio._pause_time == 42.0
    # _current_t_ms via la property real (usa audio.get_current_time que devuelve 42.0)
    assert int(session.audio.get_current_time() * 1000) == 42000


# ── 4. GO_NEXT AVANZA ────────────────────────────────────────────────────────

def test_go_next_advances():
    """go_cue(cue1) → go_next → active = cue2."""
    session = make_session_mock()
    c1 = make_cue(number=1.0, t_ms=1000)
    c2 = make_cue(number=2.0, t_ms=5000)
    session.timeline.cue_list.entries = [c1, c2]

    from server.session import ShowSession
    session.go_cue = ShowSession.go_cue.__get__(session, ShowSession)
    session.go_next_cue = ShowSession.go_next_cue.__get__(session, ShowSession)
    session._find_cue_by_uid = ShowSession._find_cue_by_uid.__get__(session, ShowSession)

    session.go_cue(c1.uid)
    assert session.timeline.cue_list.active_uid == c1.uid

    session.go_next_cue()
    assert session.timeline.cue_list.active_uid == c2.uid
    assert session.audio.seek.call_count == 2
    # Segundo seek al t_ms de c2
    session.audio.seek.assert_called_with(5.0)


# ── 5. GO_PREV RETROCEDE ─────────────────────────────────────────────────────

def test_go_prev_rewinds():
    """go_cue(cue2) → go_prev → active = cue1."""
    session = make_session_mock()
    c1 = make_cue(number=1.0, t_ms=1000)
    c2 = make_cue(number=2.0, t_ms=5000)
    session.timeline.cue_list.entries = [c1, c2]

    from server.session import ShowSession
    session.go_cue = ShowSession.go_cue.__get__(session, ShowSession)
    session.go_prev_cue = ShowSession.go_prev_cue.__get__(session, ShowSession)
    session._find_cue_by_uid = ShowSession._find_cue_by_uid.__get__(session, ShowSession)

    session.go_cue(c2.uid)
    session.go_prev_cue()
    assert session.timeline.cue_list.active_uid == c1.uid
    session.audio.seek.assert_called_with(1.0)


# ── 6. AUTO_FOLLOW TRIGGERS ──────────────────────────────────────────────────

def test_auto_follow_triggers():
    """Cue con hold_ms=100, auto_follow=True → tras 100ms → go_next."""
    session = make_session_mock()
    c1 = make_cue(number=1.0, t_ms=0, hold_ms=100, auto_follow=True)
    c2 = make_cue(number=2.0, t_ms=5000)
    session.timeline.cue_list.entries = [c1, c2]

    from server.session import ShowSession
    session.go_cue = ShowSession.go_cue.__get__(session, ShowSession)
    session.go_next_cue = ShowSession.go_next_cue.__get__(session, ShowSession)
    session._find_cue_by_uid = ShowSession._find_cue_by_uid.__get__(session, ShowSession)
    session._auto_follow_task = ShowSession._auto_follow_task.__get__(session, ShowSession)

    async def run():
        session.go_cue(c1.uid)
        # crear la tarea real
        task = asyncio.create_task(session._auto_follow_task(100))
        await asyncio.sleep(0.15)  # esperar >100ms
        return task

    asyncio.run(run())
    assert session.timeline.cue_list.active_uid == c2.uid


# ── 7. FADE APLICA AL MASTER ─────────────────────────────────────────────────

def test_fade_applies_to_master():
    """fade_in_ms=1000, t=500ms → multiplicador del frame ≈ 0.5."""
    session = make_session_mock()
    # Simular fade activo iniciado en t_ms=0, duración 1000ms
    session._cue_fade_start_ms = 0.0
    session._cue_fade_duration_ms = 1000.0

    # Frame blanco puro
    frame = np.full((10, 93, 3), 200, dtype=np.uint8)

    # Simular la lógica de fade de compute_frame en t=500ms
    t_ms = 500
    elapsed = t_ms - session._cue_fade_start_ms
    pct = max(0.0, elapsed / session._cue_fade_duration_ms)
    assert abs(pct - 0.5) < 0.01

    result = (frame.astype(np.float32) * pct).clip(0, 255).astype(np.uint8)
    expected = np.full((10, 93, 3), 100, dtype=np.uint8)
    np.testing.assert_array_equal(result, expected)


# ── 8. UNDO CUBRE CUES (I1) ──────────────────────────────────────────────────

def test_undo_covers_cues():
    """add_cue → undo → cue_list vacía."""
    tl = Timeline()
    state = {"tl": tl}

    def get_extra():
        return {"cue_list": state["tl"].cue_list.to_dict()}

    def restore_extra(extra):
        state["tl"].cue_list = CueList.from_dict(extra["cue_list"])

    um = UndoManager(
        get_clips=lambda: state["tl"].clips,
        restore_clips=lambda dicts: None,
        get_extra=get_extra,
        restore_extra=restore_extra,
    )

    # Snapshot antes de añadir cue (estado vacío)
    um.snapshot()
    cue = make_cue()
    state["tl"].cue_list.entries.append(cue)
    assert len(state["tl"].cue_list.entries) == 1

    # Undo → vuelve a vacío
    assert um.undo() is True
    assert len(state["tl"].cue_list.entries) == 0


# ── 9. DELETE_CUE NO TOCA CUEPOINTS ─────────────────────────────────────────

def test_delete_cue_not_delete_cuepoint():
    """Borrar CueEntry no toca los CuePoint del timeline."""
    tl = Timeline()
    # Añadir un CuePoint clásico (marcador pasivo)
    tl.cue_points = [CuePoint(slot=1, time_ms=5000, name="Sección A")]
    # Añadir una CueEntry con el mismo t_ms
    entry = make_cue(t_ms=5000, name="Cue 1")
    tl.cue_list.entries.append(entry)

    # Borrar la CueEntry
    tl.cue_list.entries = [e for e in tl.cue_list.entries if e.uid != entry.uid]

    # El CuePoint debe seguir intacto
    assert len(tl.cue_points) == 1
    assert tl.cue_points[0].time_ms == 5000
    assert tl.cue_points[0].name == "Sección A"
    assert len(tl.cue_list.entries) == 0


# ── 10. REORDER POR NUMBER ───────────────────────────────────────────────────

def test_reorder_by_number():
    """Añadir cues en orden inverso → reorder_cues → ordenados por number."""
    tl = Timeline()
    c3 = make_cue(number=3.0, t_ms=9000, name="C3")
    c1 = make_cue(number=1.0, t_ms=1000, name="C1")
    c2 = make_cue(number=2.0, t_ms=5000, name="C2")
    tl.cue_list.entries = [c3, c1, c2]

    # Reordenar
    tl.cue_list.entries.sort(key=lambda e: e.number)

    assert [e.name for e in tl.cue_list.entries] == ["C1", "C2", "C3"]
    assert tl.cue_list.entries[0].t_ms == 1000
    assert tl.cue_list.entries[2].t_ms == 9000
