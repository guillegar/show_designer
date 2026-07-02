"""
test_live_engine.py — Tests C1: Performance grid (ROADMAP v2).

Cubre:
  test_quantize_bar           — disparar a mitad de compás → t_armed = próximo downbeat
  test_quantize_beat          — disparar a mitad de beat → t_armed = próximo beat
  test_quantize_free          — t_armed = t_actual (sin esperar)
  test_oneshot_stops          — oneshot expira al llegar a started_at + pattern_duration
  test_loop_restarts          — loop reinicia al llegar a started_at + pattern_duration
  test_hold_requires_release  — hold sigue activo hasta live_release
  test_stop_all               — limpia _active y _armed
  test_degraded_to_free       — sin beats → quantize="bar" degrada a free (t_armed = t_ms)
  test_live_frame_merges_max  — live_frame > 0 en zona del pattern activo
  test_undo_covers_slots      — asignar slot → undo → slot vacío
  test_armed_to_active_transition — t_ms >= t_armed → slot pasa de armed a active
"""
from unittest.mock import MagicMock

import numpy as np
import pytest

from server.live_engine import NUM_LIVE_SLOTS, LiveEngine, LiveSlot

# ── Helpers ───────────────────────────────────────────────────────────────────

class FakeAnalysis:
    """Análisis sintético con beats y downbeats predefinidos."""

    def __init__(self, beats_s=None, downbeats_s=None):
        self._beats = beats_s or []
        self._downbeats = downbeats_s or []

    def list_beats(self, t0=0.0, t1=None):
        return [b for b in self._beats if b >= t0]

    def list_downbeats(self, t0=0.0, t1=None):
        return [b for b in self._downbeats if b >= t0]


# BPM 119.68 → beat ≈ 0.5016 s, downbeat ≈ 2.007 s
_BEAT_S = 60.0 / 119.68            # ~0.5016 s
_BAR_S = _BEAT_S * 4               # ~2.007 s

_BEATS = [round(i * _BEAT_S, 4) for i in range(200)]
_DOWNBEATS = [round(i * _BAR_S, 4) for i in range(50)]

_FULL_ANALYSIS = FakeAnalysis(beats_s=_BEATS, downbeats_s=_DOWNBEATS)
_EMPTY_ANALYSIS = FakeAnalysis()


_FIXED_PAT_UID = "pat000001"


def _make_pattern_dict(effect_id=1, duration_ms=2000, track=0,
                        uid=_FIXED_PAT_UID) -> dict:
    """Devuelve un dict de pattern con uid fijo y un clip simple (tiempos relativos)."""
    from src.core.timeline_model import Clip, Pattern
    clip = Clip(track=track, start_ms=0, end_ms=duration_ms, effect_id=effect_id,
                scope="per_bar")
    pat = Pattern(uid=uid, name="Test", color="#ff0000", clips=[clip])
    return pat.to_dict()


def _make_library(effect_id=1, leds=93, bars=10):
    """Mock de EffectLibrary con un efecto que pinta una barra entera de blanco."""
    lib = MagicMock()
    eff = MagicMock()
    arr = np.full((1, leds, 3), 200, dtype=np.uint8)
    eff.render.return_value = arr
    lib.get_effect.return_value = eff
    return lib


# ── Tests de cuantización ─────────────────────────────────────────────────────

def test_quantize_bar():
    """Disparar a mitad de compás → t_armed = próximo downbeat."""
    engine = LiveEngine()
    # Primer downbeat en 0 ms, segundo en ~2007 ms
    first_db_ms = _DOWNBEATS[0] * 1000
    second_db_ms = _DOWNBEATS[1] * 1000

    # Disparo entre los dos primeros downbeats
    t_ms = (first_db_ms + second_db_ms) / 2
    engine.assign_slot(0, pattern_uid=_FIXED_PAT_UID, quantize="bar", mode="oneshot")

    _, t_armed = engine.trigger(0, t_ms, _FULL_ANALYSIS)

    assert t_armed > t_ms, "t_armed debe ser posterior al disparo"
    assert abs(t_armed - second_db_ms) < 1.0, (
        f"t_armed={t_armed:.1f} debe ser el siguiente downbeat ({second_db_ms:.1f})"
    )


def test_quantize_beat():
    """Disparar a mitad de beat → t_armed = próximo beat."""
    engine = LiveEngine()
    engine.assign_slot(0, pattern_uid=_FIXED_PAT_UID, quantize="beat", mode="oneshot")

    first_beat_ms = _BEATS[1] * 1000   # ≈ 502 ms
    second_beat_ms = _BEATS[2] * 1000  # ≈ 1003 ms
    t_ms = (first_beat_ms + second_beat_ms) / 2

    _, t_armed = engine.trigger(0, t_ms, _FULL_ANALYSIS)

    assert t_armed > t_ms
    assert abs(t_armed - second_beat_ms) < 1.0, (
        f"t_armed={t_armed:.1f} debe ser el siguiente beat ({second_beat_ms:.1f})"
    )


def test_quantize_free():
    """Quantize='free' → t_armed == t_ms (sin espera)."""
    engine = LiveEngine()
    engine.assign_slot(0, pattern_uid=_FIXED_PAT_UID, quantize="free", mode="oneshot")
    t_ms = 1234.5
    _, t_armed = engine.trigger(0, t_ms, _FULL_ANALYSIS)
    assert t_armed == t_ms


def test_degraded_to_free():
    """Sin beats disponibles, quantize='bar' degrada a free."""
    engine = LiveEngine()
    engine.assign_slot(0, pattern_uid=_FIXED_PAT_UID, quantize="bar", mode="oneshot")
    t_ms = 5000.0
    _, t_armed = engine.trigger(0, t_ms, _EMPTY_ANALYSIS)
    assert t_armed == t_ms, (
        "Sin downbeats, el trigger debe degradar a free (t_armed = t_ms)"
    )


# ── Tests de modos de reproducción ───────────────────────────────────────────

def _make_engine_with_active_slot(pattern_uid=_FIXED_PAT_UID, started_at_ms=0.0,
                                   mode="oneshot") -> LiveEngine:
    from server.live_engine import ActiveSlot
    engine = LiveEngine()
    engine.assign_slot(0, pattern_uid=pattern_uid, mode=mode)
    engine._active[engine.slots[0].uid] = ActiveSlot(
        slot_uid=engine.slots[0].uid,
        pattern_uid=pattern_uid,
        started_at_ms=started_at_ms,
        mode=mode,
    )
    return engine


def test_oneshot_stops():
    """Oneshot: el slot se elimina de _active al llegar a started_at + duration."""
    DURATION_MS = 2000
    STARTED = 0.0
    engine = _make_engine_with_active_slot(mode="oneshot", started_at_ms=STARTED)
    slot_uid = engine.slots[0].uid

    patterns = [_make_pattern_dict(duration_ms=DURATION_MS)]
    lib = _make_library()
    actx: dict = {}

    # Dentro de la duración → activo
    frame = engine.compute_live_frame(STARTED + 500, patterns, lib, [], actx)
    assert slot_uid in engine._active, "Slot debe seguir activo dentro de la duración"

    # Exactamente en el límite → expira
    engine._active[slot_uid].started_at_ms = STARTED  # restaurar por si se tocó
    frame = engine.compute_live_frame(STARTED + DURATION_MS + 10, patterns, lib, [], actx)
    assert slot_uid not in engine._active, "Slot oneshot debe expirar tras la duración"


def test_loop_restarts():
    """Loop: el pattern vuelve a empezar al llegar a started_at + duration."""
    DURATION_MS = 2000
    STARTED = 0.0
    engine = _make_engine_with_active_slot(mode="loop", started_at_ms=STARTED)
    slot_uid = engine.slots[0].uid

    patterns = [_make_pattern_dict(duration_ms=DURATION_MS)]
    lib = _make_library()
    actx: dict = {}

    # A 3000 ms: t_rel sería 3000, pero en loop = 3000 % 2000 = 1000 → activo
    frame = engine.compute_live_frame(STARTED + 3000, patterns, lib, [], actx)
    assert slot_uid in engine._active, "Loop debe seguir activo más allá de la duración"
    # Verificar que el effect fue invocado (clip activo en t_rel=1000)
    lib.get_effect.return_value.render.assert_called()


def test_hold_requires_release():
    """Hold: el slot sigue activo hasta que se llame a release()."""
    DURATION_MS = 500
    engine = _make_engine_with_active_slot(mode="hold", started_at_ms=0.0)
    slot_uid = engine.slots[0].uid

    patterns = [_make_pattern_dict(duration_ms=DURATION_MS)]
    lib = _make_library()
    actx: dict = {}

    # Mucho más allá de la duración → sigue activo (hold)
    engine.compute_live_frame(10_000, patterns, lib, [], actx)
    assert slot_uid in engine._active, "Hold debe seguir activo mientras no se libere"

    # Liberar → desaparece
    engine.release(0)
    assert slot_uid not in engine._active


def test_stop_all():
    """stop_all() limpia _active y _armed."""
    from server.live_engine import ActiveSlot
    engine = LiveEngine()
    # Armar dos slots
    engine._armed["uid_a"] = 1000.0
    engine._armed["uid_b"] = 2000.0
    engine._active["uid_c"] = ActiveSlot(
        slot_uid="uid_c", pattern_uid="p1", started_at_ms=0.0, mode="loop"
    )
    engine.stop_all()
    assert engine._active == {}
    assert engine._armed == {}


# ── Test de transición armed → active ─────────────────────────────────────────

def test_armed_to_active_transition():
    """t_ms >= t_armed → slot pasa de _armed a _active en compute_live_frame."""
    engine = LiveEngine()
    engine.assign_slot(0, pattern_uid=_FIXED_PAT_UID, mode="loop")
    slot_uid = engine.slots[0].uid
    t_armed = 2000.0
    engine._armed[slot_uid] = t_armed

    patterns = [_make_pattern_dict(duration_ms=4000)]
    lib = _make_library()
    actx: dict = {}

    # Antes del tiempo armado → sigue armado, no activo
    engine.compute_live_frame(t_armed - 100, patterns, lib, [], actx)
    assert slot_uid in engine._armed
    assert slot_uid not in engine._active

    # En el tiempo armado → debe activarse
    engine._armed[slot_uid] = t_armed  # restaurar
    engine.compute_live_frame(t_armed, patterns, lib, [], actx)
    assert slot_uid not in engine._armed
    assert slot_uid in engine._active
    assert engine._active[slot_uid].started_at_ms == t_armed


# ── Test de render ────────────────────────────────────────────────────────────

def test_live_frame_merges_max():
    """live_frame > 0 en la zona del pattern activo."""
    engine = _make_engine_with_active_slot(mode="loop", started_at_ms=0.0)
    patterns = [_make_pattern_dict(effect_id=1, duration_ms=4000, track=3)]
    lib = _make_library()
    actx: dict = {}

    frame = engine.compute_live_frame(500, patterns, lib, [], actx)
    assert frame.max() > 0, "La capa live debe tener valores > 0 con un slot activo"
    assert frame[3].max() > 0, "La pista 3 debe estar iluminada"


# ── Test de undo (I1) ─────────────────────────────────────────────────────────

def test_undo_covers_slots():
    """Asignar slot → undo → slot vacío (invariante I1)."""
    from src.core.timeline_model import Timeline
    from src.core.undo import UndoManager

    tl = Timeline()
    engine = LiveEngine()
    engine_ref = engine   # referencia local

    restored_extra = {}

    def restore_extra(extra):
        restored_extra.update(extra)
        if "live_slots" in extra:
            engine_ref.slots_from_dicts(extra["live_slots"])

    um = UndoManager(
        get_clips=lambda: tl.clips,
        restore_clips=lambda dicts: None,
        get_extra=lambda: {"live_slots": engine_ref.slots_to_dicts()},
        restore_extra=restore_extra,
    )

    # Estado inicial: slot 0 vacío
    um.snapshot()

    # Asignar pattern al slot 0
    engine.assign_slot(0, pattern_uid=_FIXED_PAT_UID, mode="loop")
    assert engine.slots[0].pattern_uid == _FIXED_PAT_UID

    # Undo → slot debe quedar vacío
    um.undo()
    assert engine.slots[0].pattern_uid is None, (
        "Después de undo, el slot debe estar vacío"
    )
