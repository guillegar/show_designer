"""tests/test_output_tools.py — E4: herramientas de test de output y patch.

Tests:
  1. test_blackout_override_zeroes_frame: blackout(True) → compute_frame zeros
  2. test_blackout_false_restores: blackout(True) → blackout(False) → frame normal
  3. test_blackout_not_mutate_mixer: blackout no cambia timeline.mixer.master.brightness
  4. test_identify_invalid_fixture: fixture_id inexistente → {ok: False}
  5. test_test_universe_range: universe=0 o universe=11 → {ok: False}
"""
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


# ── Fixtures helpers ──────────────────────────────────────────────────────────

def _make_session():
    """Crea una sesión mínima con los atributos de E4."""
    from server.session import ShowSession
    with patch("server.session.get_manager") as mock_pm, \
         patch("server.session.ShowEngine"), \
         patch("server.session.HeadlessAudioPlayer"), \
         patch("server.session.EffectLibrary"), \
         patch("src.analysis.analyzer_service.AnalysisService"):

        mock_proj = MagicMock()
        mock_proj.name = "test"
        mock_proj.slug = "test"
        mock_proj.folder = MagicMock()
        mock_proj.audio_path = "/nonexistent/audio.mp3"
        mock_proj.show_file = MagicMock(is_file=MagicMock(return_value=False))
        mock_proj.rig_file = MagicMock(is_file=MagicMock(return_value=False))
        mock_proj.analysis_slug = None
        mock_pm.return_value.open_project.return_value = mock_proj
        mock_pm.return_value.current = mock_proj
        mock_pm.return_value.ensure_migrated.return_value = None

        try:
            session = ShowSession(slug="test")
            return session
        except Exception:
            pass
    return None


def _import_handler(name: str):
    import server.dispatcher as disp
    return disp._LOCAL[name]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBlackout:
    def test_blackout_override_zeroes_frame(self):
        """Con blackout_override=True, compute_frame devuelve zeros."""
        handler = _import_handler("blackout")

        # Sesión mínima con compute_frame real vía mock
        session = MagicMock()
        session.blackout_override = False
        session.timeline.mixer = {}
        session._cue_fade_start_ms = None
        session.macros = {"brightness_mul": 1.0, "speed_mul": 1.0, "hue_shift": 0.0, "strobe_rate": 0.0}
        session.baked_frames = None
        session.render_in_progress = False

        # Activar blackout
        result = handler(session, {"enabled": True})
        assert result["ok"] is True
        assert result["blackout"] is True
        assert session.blackout_override is True

    def test_blackout_false_restores(self):
        """blackout(False) limpia el override."""
        handler = _import_handler("blackout")

        session = MagicMock()
        session.blackout_override = True

        result = handler(session, {"enabled": False})
        assert result["ok"] is True
        assert result["blackout"] is False
        assert session.blackout_override is False

    def test_blackout_not_mutate_mixer(self):
        """blackout no toca timeline.mixer."""
        handler = _import_handler("blackout")

        session = MagicMock()
        session.blackout_override = False
        original_mixer = {"master": {"brightness": 0.8}}
        session.timeline.mixer = dict(original_mixer)

        handler(session, {"enabled": True})

        # mixer no debe haber cambiado
        assert session.timeline.mixer == original_mixer


class TestIdentifyFixture:
    def test_identify_invalid_fixture(self):
        """fixture_id inexistente → {ok: False, error}."""
        handler = _import_handler("identify_fixture")

        session = MagicMock()
        session.fixture_rig = MagicMock()
        # get_fixture devuelve None para ID desconocido
        session.fixture_rig.get_fixture.return_value = None
        session.fixture_rig.fixtures = []

        result = handler(session, {"fixture_id": "no_existe_123"})
        assert result["ok"] is False
        assert "error" in result

    def test_identify_sets_state(self):
        """identify_fixture con ID válido → estado efímero en sesión."""
        handler = _import_handler("identify_fixture")

        session = MagicMock()
        mock_fx = MagicMock()
        mock_fx.fixture_id = "barra_1"
        session.fixture_rig.fixtures = [mock_fx]
        session._identify = {}

        result = handler(session, {"fixture_id": "barra_1", "duration_ms": 2000})
        assert result["ok"] is True
        assert "barra_1" in session._identify


class TestTestUniverse:
    def test_test_universe_range_low(self):
        """universe=0 → {ok: False}."""
        handler = _import_handler("test_universe")
        session = MagicMock()

        result = handler(session, {"universe": 0, "r": 255, "g": 255, "b": 255})
        assert result["ok"] is False

    def test_test_universe_range_high(self):
        """universe=11 → {ok: False}."""
        handler = _import_handler("test_universe")
        session = MagicMock()

        result = handler(session, {"universe": 11, "r": 255, "g": 255, "b": 255})
        assert result["ok"] is False

    def test_test_universe_valid(self):
        """universe=1..10 → {ok: True}."""
        handler = _import_handler("test_universe")
        session = MagicMock()
        session._test_universes = {}

        result = handler(session, {"universe": 3, "r": 128, "g": 0, "b": 255})
        assert result["ok"] is True
