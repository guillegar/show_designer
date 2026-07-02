"""
test_autosave.py — Fase B4: autosave + versiones de show.

Tests:
    test_autosave_creates_file    Trigger manual → archivo show_<ts>.json existe
    test_autosave_rotation        22 archivos → solo quedan 20
    test_restore_autosave         Guardar autosave → modificar → restore → estado original
    test_no_restore_if_show_newer show.json más nuevo que autosave → check_autosave_at_startup = None
    test_path_traversal_blocked   restore_autosave("../../etc/passwd") → {ok: False}
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.timeline_model import Clip, Timeline, make_default_groups  # noqa: E402

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_timeline(n_clips: int = 3, duration_ms: int = 5000) -> Timeline:
    tl = Timeline(duration_ms=duration_ms)
    tl.groups = make_default_groups()
    for i in range(n_clips):
        tl.clips.append(Clip(
            track=i % 10,
            start_ms=i * 1000,
            end_ms=i * 1000 + 500,
            effect_id=1004,
            scope="per_bar",
            params={"r": 200, "g": 100, "b": 50},
        ))
    return tl


def _make_mock_session(tmp_path: Path) -> MagicMock:
    """Crea un ShowSession mockeado con la estructura mínima para los tests de autosave."""
    session = MagicMock()
    session._rev = 5
    session._last_saved_rev = 0
    session._autosave_banner_shown = False
    session.timeline = _make_timeline()

    # Proyecto simulado
    project = MagicMock()
    project.slug = "test_show"
    project.folder = tmp_path
    project.show_file = tmp_path / "show.json"
    session.project = project

    # Inyectar los métodos reales de ShowSession en el mock
    from server.session import ShowSession
    session._autosave_dir = lambda: ShowSession._autosave_dir(session)
    session.autosave_now = lambda: ShowSession.autosave_now(session)
    session._rotate_autosaves = lambda: ShowSession._rotate_autosaves(session)
    session.check_autosave_at_startup = lambda: ShowSession.check_autosave_at_startup(session)

    return session


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAutosaveCreatesFile:
    """autosave_now() crea el archivo show_<ts>.json en el directorio autosave."""

    def test_file_exists(self, tmp_path):
        session = _make_mock_session(tmp_path)

        path = session.autosave_now()

        assert path.is_file(), "El autosave no creó el archivo"
        assert path.parent == tmp_path / "autosave"
        assert path.name.startswith("show_")
        assert path.suffix == ".json"

    def test_file_is_valid_json(self, tmp_path):
        session = _make_mock_session(tmp_path)

        path = session.autosave_now()

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "clips" in data
        assert "version" in data

    def test_last_saved_rev_updated(self, tmp_path):
        session = _make_mock_session(tmp_path)
        session._rev = 7
        session._last_saved_rev = 0

        session.autosave_now()

        assert session._last_saved_rev == 7


class TestAutosaveRotation:
    """Crear más de 20 autosaves → solo quedan los 20 más recientes."""

    def test_rotation_keeps_20(self, tmp_path):
        session = _make_mock_session(tmp_path)

        # Crear 22 autosaves con tiempos distintos
        d = tmp_path / "autosave"
        d.mkdir(parents=True, exist_ok=True)
        for i in range(22):
            fname = d / f"show_20260101T{i:06d}.json"
            session.timeline.save(fname)

        # La rotación debe dejar solo 20
        session._rotate_autosaves()

        files = list(d.glob("show_*.json"))
        assert len(files) == 20, f"Se esperaban 20 archivos, hay {len(files)}"

    def test_rotation_keeps_newest(self, tmp_path):
        """Los 20 archivos que quedan son los más recientes (orden lexicográfico de nombre)."""
        session = _make_mock_session(tmp_path)

        d = tmp_path / "autosave"
        d.mkdir(parents=True, exist_ok=True)
        for i in range(22):
            fname = d / f"show_20260101T{i:06d}.json"
            session.timeline.save(fname)

        session._rotate_autosaves()

        files = sorted(d.glob("show_*.json"), key=lambda p: p.name)
        # Los 2 más viejos (T000000, T000001) deben haberse borrado
        assert not any("T000000" in f.name for f in files)
        assert not any("T000001" in f.name for f in files)
        # El más reciente (T000021) debe estar
        assert any("T000021" in f.name for f in files)


class TestRestoreAutosave:
    """restore_autosave() carga el autosave como timeline activo."""

    def test_restore_reverts_changes(self, tmp_path):
        """Guardar autosave → modificar timeline → restore → mismo estado original."""
        from server.dispatcher import _h_restore_autosave

        # Crear show.json inicial
        tl_original = _make_timeline(n_clips=3)
        show_path = tmp_path / "show.json"
        tl_original.save(show_path)

        # Crear autosave del estado original
        d = tmp_path / "autosave"
        d.mkdir()
        autosave_name = "show_20260101T120000.json"
        tl_original.save(d / autosave_name)

        # Simular modificación del timeline (añadir un clip extra)
        session = _make_mock_session(tmp_path)
        session.timeline = _make_timeline(n_clips=5)
        session.snapshot = MagicMock()
        session.invalidate_caches = MagicMock()

        result = _h_restore_autosave(session, {"filename": autosave_name})

        assert result["ok"] is True
        assert len(session.timeline.clips) == 3, (
            f"Esperaba 3 clips tras restore, hay {len(session.timeline.clips)}")

    def test_restore_preserves_duration(self, tmp_path):
        """El restore preserva duration_ms del show activo (viene del audio)."""
        from server.dispatcher import _h_restore_autosave

        d = tmp_path / "autosave"
        d.mkdir()
        autosave_name = "show_20260101T130000.json"
        tl = _make_timeline()
        tl.duration_ms = 30000
        tl.save(d / autosave_name)

        session = _make_mock_session(tmp_path)
        session.timeline.duration_ms = 99999  # duración del audio
        session.snapshot = MagicMock()
        session.invalidate_caches = MagicMock()

        _h_restore_autosave(session, {"filename": autosave_name})

        assert session.timeline.duration_ms == 99999, (
            "restore_autosave no preservó duration_ms del show activo")


class TestNoRestoreIfShowNewer:
    """Si show.json es más reciente que el autosave → no emitir evento."""

    def test_no_event_when_show_is_newer(self, tmp_path):
        session = _make_mock_session(tmp_path)

        # Crear autosave con mtime viejo
        d = tmp_path / "autosave"
        d.mkdir()
        autosave = d / "show_20260101T000000.json"
        _make_timeline().save(autosave)

        # Dar un poco de margen y luego crear show.json (más nuevo)
        time.sleep(0.01)
        show_path = tmp_path / "show.json"
        _make_timeline().save(show_path)

        # Ajustar mtime del autosave para que sea más viejo que show.json
        mtime_show = show_path.stat().st_mtime
        os.utime(autosave, (mtime_show - 10, mtime_show - 10))

        event = session.check_autosave_at_startup()
        assert event is None, "No debería emitir evento si show.json es más nuevo"

    def test_event_when_autosave_is_newer(self, tmp_path):
        session = _make_mock_session(tmp_path)

        # Crear show.json primero (más viejo)
        show_path = tmp_path / "show.json"
        _make_timeline().save(show_path)

        # Ajustar mtime de show.json para que sea más viejo
        mtime_show = show_path.stat().st_mtime
        os.utime(show_path, (mtime_show - 10, mtime_show - 10))

        # Crear autosave con mtime reciente
        d = tmp_path / "autosave"
        d.mkdir()
        autosave = d / "show_20260601T100000.json"
        _make_timeline().save(autosave)

        event = session.check_autosave_at_startup()
        assert event is not None, "Debe emitir evento si autosave es más nuevo"
        assert event["type"] == "autosave_available"
        assert event["filename"] == "show_20260601T100000.json"

    def test_banner_shown_only_once(self, tmp_path):
        """El flag _autosave_banner_shown evita repetición."""
        session = _make_mock_session(tmp_path)

        show_path = tmp_path / "show.json"
        _make_timeline().save(show_path)
        mtime_show = show_path.stat().st_mtime
        os.utime(show_path, (mtime_show - 10, mtime_show - 10))

        d = tmp_path / "autosave"
        d.mkdir()
        autosave = d / "show_20260601T110000.json"
        _make_timeline().save(autosave)

        event1 = session.check_autosave_at_startup()
        event2 = session.check_autosave_at_startup()
        assert event1 is not None
        assert event2 is None, "El banner no debe mostrarse dos veces"


class TestPathTraversalBlocked:
    """restore_autosave con paths maliciosos debe devolver {ok: False}."""

    @pytest.mark.parametrize("filename", [
        "../../etc/passwd",
        "../show.json",
        "/etc/passwd",
        "autosave/../../show.json",
        "show_../../../bad.json",
    ])
    def test_traversal_blocked(self, tmp_path, filename):
        from server.dispatcher import _h_restore_autosave

        session = _make_mock_session(tmp_path)

        result = _h_restore_autosave(session, {"filename": filename})

        assert result["ok"] is False, (
            f"Path traversal no fue bloqueado para: {filename!r}")
        assert "error" in result
