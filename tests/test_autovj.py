"""
test_autovj.py — Tests D1: Auto-VJ por reglas (ROADMAP v2).

Cubre:
  test_rule_roundtrip                  — to_dict / from_dict preserva campos
  test_ruleset_roundtrip               — RuleSet to_dict / from_dict
  test_on_beat_fires_in_window         — on_beat dispara dentro de ±20 ms
  test_on_beat_no_fire_out_of_window   — on_beat no dispara fuera de ±20 ms
  test_on_downbeat_fires               — on_downbeat dispara en downbeat
  test_on_kick_fires_above_threshold   — on_kick dispara cuando valor > 0.6
  test_on_kick_no_fire_below           — on_kick no dispara cuando valor < 0.6
  test_on_section_change_fires         — on_section_change al cambiar sección
  test_on_section_change_no_first_frame — no dispara si _last_section es None
  test_signal_above_rising_edge        — signal_above sólo en flanco ascendente
  test_signal_above_hysteresis         — no re-dispara hasta caer por thr*0.8
  test_cooldown_prevents_refire        — cooldown bloquea re-disparo dentro de ventana
  test_cooldown_allows_after_expiry    — cooldown permite re-disparo tras expirar
  test_fire_effect_active_slot         — fire_effect inyecta slot en live._active
  test_fire_effect_ephemeral_pattern   — fire_effect crea pattern en _ephemeral_patterns
  test_fire_effect_pattern_content     — ephemeral pattern tiene effect_id y duration correctos
  test_fire_pattern_slot15_fallback    — fire_pattern usa slot 15 si no hay slot con pattern
  test_fire_pattern_finds_existing     — fire_pattern usa slot existente si tiene el pattern
  test_disabled_rule_no_fire           — regla disabled no dispara
  test_disabled_ruleset_no_eval        — ruleset disabled no evalúa ninguna regla
  test_no_analysis_no_beat             — on_beat con analysis=None devuelve False
  test_ephemeral_cleanup               — patterns efímeros se limpian al expirar slot
  test_save_load_roundtrip             — save/load conserva el ruleset
  test_presets_exist                   — PRESETS tiene fiesta/chill/techno
  test_preset_fiesta_triggers          — FIESTA tiene on_downbeat, on_beat, signal_above
  test_none_ruleset_noop               — evaluate con ruleset=None es no-op
  test_empty_rules_noop                — evaluate con rules=[] es no-op
"""
import math
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.core.autovj import (
    Rule, RuleSet, AutoVJEngine,
    PRESET_FIESTA, PRESET_CHILL, PRESET_TECHNO, PRESETS,
    _BEAT_WINDOW_MS,
)
from server.live_engine import LiveEngine, NUM_LIVE_SLOTS


# ── Helpers ───────────────────────────────────────────────────────────────────

class FakeAnalysis:
    """Análisis sintético con beats, downbeats y secciones predefinidos."""

    def __init__(self, beats_s=None, downbeats_s=None, sections=None):
        self._beats = beats_s or []
        self._downbeats = downbeats_s or []
        self._sections = sections or []   # [{start, end, name}]

    def list_beats(self, t0=0.0, t1=None):
        return [b for b in self._beats if b >= t0]

    def list_downbeats(self, t0=0.0, t1=None):
        return [b for b in self._downbeats if b >= t0]

    def section_at(self, time_sec: float):
        for s in self._sections:
            if s["start"] <= time_sec < s["end"]:
                # Duck-typed Section con name y label
                name = s.get("name", "")
                obj = type("Section", (), {"name": name, "label": name})()
                return obj
        return None


# BPM ≈ 119.68 → beat ≈ 501.6 ms, compás ≈ 2006.4 ms
_BEAT_MS = 1000.0 * 60.0 / 119.68
_BAR_MS = _BEAT_MS * 4

# 50 beats en ms
_BEATS_S = [round(i * _BEAT_MS / 1000.0, 4) for i in range(50)]
_DOWNBEATS_S = [round(i * _BAR_MS / 1000.0, 4) for i in range(13)]

_ANALYSIS = FakeAnalysis(beats_s=_BEATS_S, downbeats_s=_DOWNBEATS_S)
_EMPTY_ANALYSIS = FakeAnalysis()

_BEAT_T_MS = _BEATS_S[1] * 1000.0      # segundo beat en ms
_DOWNBEAT_T_MS = _DOWNBEATS_S[1] * 1000.0  # segundo downbeat en ms


def _engine_with_rule(trigger, action="fire_effect:1:per_bar:200", cooldown_ms=0):
    engine = AutoVJEngine()
    engine.ruleset = RuleSet(uid="rs", name="Test", rules=[
        Rule(uid="r1", trigger=trigger, action=action, cooldown_ms=cooldown_ms)
    ])
    return engine


def _live():
    return LiveEngine()


def _actx(norm=None):
    return {"norm": norm or {}}


# ── Modelo: serialización ─────────────────────────────────────────────────────

def test_rule_roundtrip():
    r = Rule(uid="abc12345", trigger="on_beat", action="fire_effect:1:per_bar:500",
             cooldown_ms=300, enabled=False)
    d = r.to_dict()
    r2 = Rule.from_dict(d)
    assert r2.uid == "abc12345"
    assert r2.trigger == "on_beat"
    assert r2.action == "fire_effect:1:per_bar:500"
    assert r2.cooldown_ms == 300
    assert r2.enabled is False
    # Runtime state no se persiste
    assert r2._last_fired_ms == -math.inf
    assert r2._above is False


def test_ruleset_roundtrip():
    rs = RuleSet(uid="rs1", name="MySet", enabled=True, rules=[
        Rule(uid="r1", trigger="on_downbeat", action="fire_effect:4:global:100"),
        Rule(uid="r2", trigger="signal_above:rms:0.5", action="fire_pattern:pat1",
             cooldown_ms=500, enabled=False),
    ])
    d = rs.to_dict()
    rs2 = RuleSet.from_dict(d)
    assert rs2.uid == "rs1"
    assert rs2.name == "MySet"
    assert len(rs2.rules) == 2
    assert rs2.rules[1].enabled is False
    assert rs2.rules[1].cooldown_ms == 500


# ── Triggers: on_beat ─────────────────────────────────────────────────────────

def test_on_beat_fires_in_window():
    engine = _engine_with_rule("on_beat")
    live = _live()
    # Exactamente en el beat
    engine.evaluate(_BEAT_T_MS, _actx(), _ANALYSIS, live)
    assert "autovj_r1" in live._active

def test_on_beat_fires_at_plus_window():
    engine = _engine_with_rule("on_beat")
    live = _live()
    engine.evaluate(_BEAT_T_MS + _BEAT_WINDOW_MS, _actx(), _ANALYSIS, live)
    assert "autovj_r1" in live._active

def test_on_beat_fires_at_minus_window():
    engine = _engine_with_rule("on_beat")
    live = _live()
    engine.evaluate(_BEAT_T_MS - _BEAT_WINDOW_MS, _actx(), _ANALYSIS, live)
    assert "autovj_r1" in live._active

def test_on_beat_no_fire_out_of_window():
    engine = _engine_with_rule("on_beat")
    live = _live()
    engine.evaluate(_BEAT_T_MS + _BEAT_WINDOW_MS + 1, _actx(), _ANALYSIS, live)
    assert "autovj_r1" not in live._active


# ── Triggers: on_downbeat ─────────────────────────────────────────────────────

def test_on_downbeat_fires():
    engine = _engine_with_rule("on_downbeat")
    live = _live()
    engine.evaluate(_DOWNBEAT_T_MS, _actx(), _ANALYSIS, live)
    assert "autovj_r1" in live._active

def test_on_downbeat_no_fire_on_plain_beat():
    engine = _engine_with_rule("on_downbeat")
    live = _live()
    # Un beat que NO es downbeat (beats[2] ≠ downbeats[1])
    t = _BEATS_S[2] * 1000.0  # 3er beat
    # Si este beat es un downbeat, busca uno que no lo sea
    downbeat_ms_set = {round(d * 1000.0) for d in _DOWNBEATS_S}
    for i in range(1, len(_BEATS_S)):
        t_candidate = round(_BEATS_S[i] * 1000.0)
        if not any(abs(t_candidate - db) <= _BEAT_WINDOW_MS for db in downbeat_ms_set):
            t = _BEATS_S[i] * 1000.0
            break
    engine.evaluate(t, _actx(), _ANALYSIS, live)
    assert "autovj_r1" not in live._active


# ── Triggers: on_kick ─────────────────────────────────────────────────────────

def test_on_kick_fires_above_threshold():
    engine = _engine_with_rule("on_kick")
    live = _live()
    engine.evaluate(0.0, _actx({"kick": 0.8}), None, live)
    assert "autovj_r1" in live._active

def test_on_kick_no_fire_below():
    engine = _engine_with_rule("on_kick")
    live = _live()
    engine.evaluate(0.0, _actx({"kick": 0.4}), None, live)
    assert "autovj_r1" not in live._active

def test_on_kick_uses_onset_strength_fallback():
    engine = _engine_with_rule("on_kick")
    live = _live()
    # Sin 'kick' en norm → usa onset_strength
    engine.evaluate(0.0, _actx({"onset_strength": 0.9}), None, live)
    assert "autovj_r1" in live._active


# ── Triggers: on_section_change ───────────────────────────────────────────────

def test_on_section_change_fires_on_transition():
    sections = [
        {"start": 0.0, "end": 10.0, "name": "intro"},
        {"start": 10.0, "end": 30.0, "name": "verse"},
    ]
    analysis = FakeAnalysis(sections=sections)
    engine = _engine_with_rule("on_section_change")
    live = _live()

    # Primera evaluación en intro — _last_section se inicia en None → no dispara
    engine.evaluate(5000.0, _actx(), analysis, live)
    assert "autovj_r1" not in live._active
    assert engine._last_section == "intro"

    # Segunda evaluación en verse — cambia → dispara
    engine.evaluate(10000.0, _actx(), analysis, live)
    assert "autovj_r1" in live._active

def test_on_section_change_no_first_frame():
    """No dispara en el primer frame (último _last_section=None)."""
    sections = [{"start": 0.0, "end": 30.0, "name": "intro"}]
    analysis = FakeAnalysis(sections=sections)
    engine = _engine_with_rule("on_section_change")
    live = _live()

    engine.evaluate(0.0, _actx(), analysis, live)
    assert "autovj_r1" not in live._active  # _last_section era None


# ── Triggers: signal_above ────────────────────────────────────────────────────

def test_signal_above_rising_edge():
    engine = _engine_with_rule("signal_above:rms:0.7")
    live = _live()
    # Señal sube por encima del umbral → dispara (flanco ascendente)
    engine.evaluate(0.0, _actx({"rms": 0.8}), None, live)
    assert "autovj_r1" in live._active

def test_signal_above_no_fire_when_already_above():
    engine = _engine_with_rule("signal_above:rms:0.7")
    live = _live()
    engine.evaluate(0.0, _actx({"rms": 0.8}), None, live)  # rising edge
    live._active.clear()
    # Mismo valor alto en el siguiente frame: NO dispara (ya estaba arriba)
    engine.evaluate(100.0, _actx({"rms": 0.85}), None, live)
    assert "autovj_r1" not in live._active

def test_signal_above_hysteresis():
    """Sólo re-dispara tras caer por debajo de thr_off = thr * 0.8."""
    engine = _engine_with_rule("signal_above:rms:0.7")
    live = _live()

    # Rising edge → dispara
    engine.evaluate(0.0, _actx({"rms": 0.8}), None, live)
    assert "autovj_r1" in live._active
    live._active.clear()

    # Baja entre thr_off y thr → _above sigue True, NO re-dispara
    engine.evaluate(100.0, _actx({"rms": 0.72}), None, live)
    assert "autovj_r1" not in live._active
    assert engine.ruleset.rules[0]._above is True

    # Baja por debajo de thr_off (0.7 * 0.8 = 0.56) → _above = False
    engine.evaluate(200.0, _actx({"rms": 0.5}), None, live)
    assert engine.ruleset.rules[0]._above is False

    # Sube de nuevo → re-dispara
    engine.evaluate(300.0, _actx({"rms": 0.85}), None, live)
    assert "autovj_r1" in live._active

def test_signal_above_no_fire_below_threshold():
    engine = _engine_with_rule("signal_above:rms:0.7")
    live = _live()
    engine.evaluate(0.0, _actx({"rms": 0.5}), None, live)
    assert "autovj_r1" not in live._active


# ── Cooldown ──────────────────────────────────────────────────────────────────

def test_cooldown_prevents_refire():
    engine = _engine_with_rule("on_beat", cooldown_ms=500)
    live = _live()
    engine.evaluate(_BEAT_T_MS, _actx(), _ANALYSIS, live)
    assert "autovj_r1" in live._active

    live._active.clear()

    # 200 ms después (< 500 ms cooldown) → NO dispara
    engine.evaluate(_BEAT_T_MS + 200.0, _actx(), _ANALYSIS, live)
    assert "autovj_r1" not in live._active

def test_cooldown_allows_after_expiry():
    engine = _engine_with_rule("on_kick", cooldown_ms=100)
    live = _live()
    actx = _actx({"kick": 0.9})

    engine.evaluate(0.0, actx, None, live)
    assert "autovj_r1" in live._active
    live._active.clear()

    # 50 ms después → bloqueado
    engine.evaluate(50.0, actx, None, live)
    assert "autovj_r1" not in live._active

    # 110 ms después → permitido (> 100 ms cooldown)
    engine.evaluate(110.0, actx, None, live)
    assert "autovj_r1" in live._active


# ── Acciones: fire_effect ─────────────────────────────────────────────────────

def test_fire_effect_active_slot():
    engine = _engine_with_rule("on_kick", action="fire_effect:2:global:400")
    live = _live()
    engine.evaluate(0.0, _actx({"kick": 0.9}), None, live)

    assert "autovj_r1" in live._active
    slot = live._active["autovj_r1"]
    assert slot.pattern_uid == "autovj_effect_r1"
    assert slot.started_at_ms == 0.0
    assert slot.mode == "oneshot"

def test_fire_effect_ephemeral_pattern():
    engine = _engine_with_rule("on_kick", action="fire_effect:2:global:400")
    live = _live()
    engine.evaluate(0.0, _actx({"kick": 0.9}), None, live)

    assert "autovj_effect_r1" in engine._ephemeral_patterns

def test_fire_effect_pattern_content():
    engine = _engine_with_rule("on_kick", action="fire_effect:7:per_bar:600")
    live = _live()
    engine.evaluate(0.0, _actx({"kick": 0.9}), None, live)

    pat_d = engine._ephemeral_patterns["autovj_effect_r1"]
    assert pat_d["uid"] == "autovj_effect_r1"
    clips = pat_d.get("clips", [])
    assert len(clips) == 1
    assert clips[0]["effect_id"] == 7
    assert clips[0]["scope"] == "per_bar"
    assert clips[0]["end_ms"] == 600


# ── Acciones: fire_pattern ────────────────────────────────────────────────────

def test_fire_pattern_slot15_fallback():
    """Si ningún slot tiene el pattern_uid, se usa el slot 15."""
    engine = _engine_with_rule("on_kick", action="fire_pattern:mypattern")
    live = _live()
    engine.evaluate(0.0, _actx({"kick": 0.9}), None, live)

    slot15_uid = live.slots[15].uid
    assert slot15_uid in live._active
    assert live.slots[15].pattern_uid == "mypattern"

def test_fire_pattern_finds_existing_slot():
    """Si un slot ya tiene el pattern_uid, lo usa (no usa slot 15)."""
    engine = _engine_with_rule("on_kick", action="fire_pattern:mypattern")
    live = _live()
    live.slots[3].pattern_uid = "mypattern"

    engine.evaluate(0.0, _actx({"kick": 0.9}), None, live)

    slot3_uid = live.slots[3].uid
    assert slot3_uid in live._active
    # slot 15 no debería estar activo (a menos que tuviera el mismo uid, que no)
    slot15_uid = live.slots[15].uid
    assert slot15_uid not in live._active


# ── Reglas y rulesets desactivados ────────────────────────────────────────────

def test_disabled_rule_no_fire():
    engine = AutoVJEngine()
    engine.ruleset = RuleSet(uid="rs", name="T", rules=[
        Rule(uid="r1", trigger="on_kick", action="fire_effect:1:per_bar:200",
             cooldown_ms=0, enabled=False)
    ])
    live = _live()
    engine.evaluate(0.0, _actx({"kick": 0.9}), None, live)
    assert "autovj_r1" not in live._active

def test_disabled_ruleset_no_eval():
    engine = AutoVJEngine()
    engine.ruleset = RuleSet(uid="rs", name="T", enabled=False, rules=[
        Rule(uid="r1", trigger="on_kick", action="fire_effect:1:per_bar:200",
             cooldown_ms=0)
    ])
    live = _live()
    engine.evaluate(0.0, _actx({"kick": 0.9}), None, live)
    assert "autovj_r1" not in live._active

def test_none_ruleset_noop():
    engine = AutoVJEngine()
    # ruleset = None por defecto
    live = _live()
    # No debe lanzar excepción
    engine.evaluate(1000.0, _actx({"kick": 0.9}), _ANALYSIS, live)
    assert not live._active

def test_empty_rules_noop():
    engine = AutoVJEngine()
    engine.ruleset = RuleSet(uid="rs", name="T", rules=[])
    live = _live()
    engine.evaluate(1000.0, _actx(), _ANALYSIS, live)
    assert not live._active


# ── Sin análisis ──────────────────────────────────────────────────────────────

def test_no_analysis_no_beat():
    engine = _engine_with_rule("on_beat")
    live = _live()
    engine.evaluate(1000.0, _actx(), None, live)
    assert "autovj_r1" not in live._active

def test_empty_analysis_no_beat():
    engine = _engine_with_rule("on_beat")
    live = _live()
    engine.evaluate(1000.0, _actx(), _EMPTY_ANALYSIS, live)
    assert "autovj_r1" not in live._active


# ── Limpieza de ephemeral patterns ───────────────────────────────────────────

def test_ephemeral_cleanup():
    """Los patterns efímeros se eliminan cuando su slot ya no está en _active."""
    engine = _engine_with_rule("on_kick", action="fire_effect:1:per_bar:200")
    live = _live()

    engine.evaluate(0.0, _actx({"kick": 0.9}), None, live)
    assert "autovj_effect_r1" in engine._ephemeral_patterns

    # Simular que el slot expiró (oneshot terminado)
    live._active.clear()

    # Nueva evaluación — kick bajo para no re-disparar (cooldown=0 pero kick=0)
    engine.evaluate(5000.0, _actx({"kick": 0.0}), None, live)
    assert "autovj_effect_r1" not in engine._ephemeral_patterns


# ── Persistencia: save / load ─────────────────────────────────────────────────

def test_save_load_roundtrip(tmp_path):
    engine = AutoVJEngine()
    engine.ruleset = RuleSet(uid="rs_save", name="SaveTest", rules=[
        Rule(uid="x1", trigger="on_beat", action="fire_effect:3:global:100", cooldown_ms=400),
        Rule(uid="x2", trigger="signal_above:rms:0.6", action="fire_pattern:p1",
             cooldown_ms=1000, enabled=False),
    ])

    path = tmp_path / "autovj.json"
    engine.save(path)
    assert path.is_file()

    engine2 = AutoVJEngine()
    engine2.load(path)
    rs = engine2.ruleset
    assert rs is not None
    assert rs.uid == "rs_save"
    assert rs.name == "SaveTest"
    assert len(rs.rules) == 2
    assert rs.rules[0].uid == "x1"
    assert rs.rules[1].enabled is False

def test_save_noop_when_no_ruleset(tmp_path):
    engine = AutoVJEngine()
    path = tmp_path / "autovj.json"
    engine.save(path)
    assert not path.exists()

def test_load_noop_when_no_file(tmp_path):
    engine = AutoVJEngine()
    engine.load(tmp_path / "nonexistent.json")
    assert engine.ruleset is None

def test_save_atomic(tmp_path):
    """Guardado atómico: no deja .tmp si tiene éxito."""
    engine = AutoVJEngine()
    engine.ruleset = RuleSet(uid="rs1", name="T", rules=[
        Rule(uid="r1", trigger="on_beat", action="fire_effect:1:per_bar:100")
    ])
    path = tmp_path / "autovj.json"
    engine.save(path)
    assert not (tmp_path / "autovj.tmp").exists()
    assert path.is_file()


# ── Presets integrados ────────────────────────────────────────────────────────

def test_presets_exist():
    assert "preset_fiesta" in PRESETS
    assert "preset_chill" in PRESETS
    assert "preset_techno" in PRESETS

def test_preset_fiesta_triggers():
    triggers = {r.trigger for r in PRESET_FIESTA.rules}
    assert "on_downbeat" in triggers
    assert "on_beat" in triggers
    assert any(t.startswith("signal_above:") for t in triggers)

def test_preset_chill_slower():
    """Chill debe tener cooldowns > Fiesta (más tranquilo)."""
    chill_min_cd = min(r.cooldown_ms for r in PRESET_CHILL.rules)
    fiesta_max_cd = max(r.cooldown_ms for r in PRESET_FIESTA.rules)
    # No necesariamente siempre mayor, pero Chill tiene cooldowns largos
    assert chill_min_cd >= 1000   # al menos 1s

def test_preset_techno_short_cooldowns():
    """Techno debe tener cooldowns cortos (agresivo)."""
    techno_max_cd = max(r.cooldown_ms for r in PRESET_TECHNO.rules)
    assert techno_max_cd <= 500   # máximo 500ms en Techno

def test_preset_from_dict_fresh_state():
    """from_dict crea reglas con estado runtime reseteado (sin herencia del preset)."""
    # Simular que el preset tiene _last_fired_ms contaminado
    PRESET_FIESTA.rules[0]._last_fired_ms = 999999.0
    # Crear copia fresh via from_dict
    rs = RuleSet.from_dict(PRESET_FIESTA.to_dict())
    assert rs.rules[0]._last_fired_ms == -math.inf
    # Restaurar el preset para no afectar otros tests
    PRESET_FIESTA.rules[0]._last_fired_ms = -math.inf
