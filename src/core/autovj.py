"""
autovj.py — Motor de Auto-VJ por reglas (D1, ROADMAP v2).

Módulo PURO: sin imports de server/, web/, fastapi ni rutas de proyecto.
Recibe actx + analysis + live_engine y dispara efectos/patterns en respuesta
a señales musicales (beats, secciones, umbrales de señal).

Reutiliza la capa live de C1 (LiveEngine._active) como destino de los disparos.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

import numpy as np


# ── Constantes ───────────────────────────────────────────────────────────────

_BEAT_WINDOW_MS = 20.0       # ±20 ms para considerar "en el beat"
_AUTOVJ_SLOT_IDX = 15        # Slot reservado para AutoVJ en fire_pattern


# ── _EphemeralSlot ───────────────────────────────────────────────────────────

class _EphemeralSlot:
    """Duck-typed sustituto de server.live_engine.ActiveSlot.

    Definido aquí para evitar importar de server/ dentro de src/core/ (regla
    de layering del ROADMAP). live_engine.compute_live_frame sólo accede a los
    atributos slot_uid, pattern_uid, started_at_ms y mode — todos presentes.
    """
    __slots__ = ("slot_uid", "pattern_uid", "started_at_ms", "mode")

    def __init__(self, slot_uid: str, pattern_uid: str,
                 started_at_ms: float, mode: str) -> None:
        self.slot_uid = slot_uid
        self.pattern_uid = pattern_uid
        self.started_at_ms = started_at_ms
        self.mode = mode


# ── Modelo de datos ──────────────────────────────────────────────────────────

@dataclass
class Rule:
    """Una regla trigger→action con cooldown.

    Triggers:
      "on_beat"                         — cerca de cualquier beat (±20 ms)
      "on_downbeat"                     — cerca de un downbeat (±20 ms)
      "on_kick"                         — proxy en actx['norm'] (ver nota)
      "on_section_change"               — cambio de sección detectado
      "signal_above:<src>:<thr>"        — señal en actx['norm'] > thr (flanco)

    Nota on_kick: no hay una curva 'kick' en el timeseries; se usa
    norm.get('kick', norm.get('onset_strength', 0)) > 0.6 como proxy.
    D2 (análisis en vivo) implementará detección real de onsets.

    Actions:
      "fire_effect:<effect_id>:<scope>:<duration_ms>"
      "fire_pattern:<pattern_uid>"
    """
    uid: str
    trigger: str
    action: str
    cooldown_ms: int = 2000
    enabled: bool = True
    # Runtime state — no se persiste
    _last_fired_ms: float = field(default=-math.inf, init=False, repr=False)
    _above: bool = field(default=False, init=False, repr=False)

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "trigger": self.trigger,
            "action": self.action,
            "cooldown_ms": self.cooldown_ms,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(
            uid=str(d.get("uid") or uuid4().hex[:8]),
            trigger=str(d.get("trigger", "on_beat")),
            action=str(d.get("action", "")),
            cooldown_ms=max(0, int(d.get("cooldown_ms", 2000))),
            enabled=bool(d.get("enabled", True)),
        )


@dataclass
class RuleSet:
    uid: str
    name: str
    rules: List[Rule]
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "name": self.name,
            "rules": [r.to_dict() for r in self.rules],
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RuleSet":
        return cls(
            uid=str(d.get("uid") or uuid4().hex[:8]),
            name=str(d.get("name", "Custom")),
            rules=[Rule.from_dict(rd) for rd in d.get("rules", [])],
            enabled=bool(d.get("enabled", True)),
        )


# ── Presets integrados ───────────────────────────────────────────────────────
# No se persisten en disco — viven en código. El usuario puede guardar su
# propia versión con save().

PRESET_FIESTA = RuleSet(uid="preset_fiesta", name="Fiesta", rules=[
    Rule(uid="f1", trigger="on_downbeat",
         action="fire_effect:1:per_bar:500", cooldown_ms=1000),
    Rule(uid="f2", trigger="on_beat",
         action="fire_effect:4:per_bar:200", cooldown_ms=500),
    Rule(uid="f3", trigger="signal_above:rms:0.7",
         action="fire_effect:0:global:300", cooldown_ms=2000),
])

PRESET_CHILL = RuleSet(uid="preset_chill", name="Chill", rules=[
    Rule(uid="c1", trigger="on_downbeat",
         action="fire_effect:1:per_bar:2000", cooldown_ms=4000),
    Rule(uid="c2", trigger="signal_above:rms:0.5",
         action="fire_effect:4:per_bar:800", cooldown_ms=3000),
    Rule(uid="c3", trigger="on_section_change",
         action="fire_effect:1004:global:1000", cooldown_ms=8000),
])

PRESET_TECHNO = RuleSet(uid="preset_techno", name="Techno", rules=[
    Rule(uid="t1", trigger="on_downbeat",
         action="fire_effect:0:global:100", cooldown_ms=200),
    Rule(uid="t2", trigger="on_beat",
         action="fire_effect:1004:per_bar:100", cooldown_ms=200),
    Rule(uid="t3", trigger="signal_above:rms:0.8",
         action="fire_effect:4:global:50", cooldown_ms=100),
    Rule(uid="t4", trigger="on_kick",
         action="fire_effect:1005:global:80", cooldown_ms=150),
])

PRESETS: Dict[str, RuleSet] = {
    p.uid: p for p in [PRESET_FIESTA, PRESET_CHILL, PRESET_TECHNO]
}


# ── Motor ────────────────────────────────────────────────────────────────────

class AutoVJEngine:
    """Motor de Auto-VJ: evalúa reglas y dispara efectos/patterns via LiveEngine.

    Se instancia en ShowSession (server/session.py) y se llama desde
    compute_frame ANTES de live_engine.compute_live_frame, para que los
    disparos lleguen al mismo frame que los desencadenó.

    Los patterns efímeros generados por fire_effect se guardan en
    _ephemeral_patterns (uid → dict). Session los pasa a compute_live_frame
    junto con los patterns del timeline.
    """

    def __init__(self) -> None:
        self.ruleset: Optional[RuleSet] = None
        self._last_section: Optional[str] = None
        # Patterns efímeros creados por fire_effect (uid → pattern dict).
        # Session los pasa a live_engine.compute_live_frame junto con timeline.patterns.
        self._ephemeral_patterns: Dict[str, dict] = {}

    # ── Evaluación principal ─────────────────────────────────────────────────

    def evaluate(self, t_ms: float, actx: dict, analysis, live_engine) -> None:
        """Evalúa todas las reglas del ruleset activo.

        Se llama en compute_frame, dentro del tick de 30 FPS. Debe ser rápido:
        cada regla es ~1 µs (searchsorted + lookup en dict).
        """
        if self.ruleset is None or not self.ruleset.enabled:
            return

        # Limpieza de patterns efímeros cuyo slot ya expiró (oneshot terminado)
        active_pat_uids = {aslot.pattern_uid
                           for aslot in live_engine._active.values()}
        stale = [uid for uid in self._ephemeral_patterns
                 if uid not in active_pat_uids]
        for uid in stale:
            del self._ephemeral_patterns[uid]

        norm: dict = actx.get("norm", {}) if actx else {}
        current_section = self._get_section_name(t_ms, analysis)

        for rule in self.ruleset.rules:
            if not rule.enabled:
                continue
            if self._check_trigger(rule, t_ms, norm, analysis, current_section):
                self._fire(rule, t_ms, live_engine)

        # Actualizar sección DESPUÉS de evaluar (para que section_change
        # compare la anterior con la actual, no la actual con sí misma)
        self._last_section = current_section

    # ── Helpers privados ─────────────────────────────────────────────────────

    def _get_section_name(self, t_ms: float, analysis) -> Optional[str]:
        if analysis is None:
            return None
        try:
            sec = analysis.section_at(t_ms / 1000.0)
            if sec is not None:
                return getattr(sec, 'name', None) or getattr(sec, 'label', None)
        except Exception:
            pass
        return None

    def _check_trigger(self, rule: Rule, t_ms: float, norm: dict,
                       analysis, current_section: Optional[str]) -> bool:
        t = rule.trigger

        if t == "on_beat":
            return self._near_beat(t_ms, analysis, "beat")

        if t == "on_downbeat":
            return self._near_beat(t_ms, analysis, "downbeat")

        if t == "on_kick":
            # Proxy: no hay curva 'kick' en el timeseries. Se usa norm.kick si
            # el análisis lo provee, o onset_strength como fallback.
            # D2 implementará detección real de onsets en tiempo real.
            val = float(norm.get("kick", norm.get("onset_strength", 0.0)))
            return val > 0.6

        if t == "on_section_change":
            # Sólo dispara al transitar entre dos secciones conocidas,
            # no en el primer frame (donde _last_section es None).
            return (self._last_section is not None
                    and current_section is not None
                    and current_section != self._last_section)

        if t.startswith("signal_above:"):
            return self._check_signal_above(rule, norm)

        return False

    def _near_beat(self, t_ms: float, analysis, kind: str) -> bool:
        """True si t_ms está dentro de ±BEAT_WINDOW_MS de algún beat/downbeat."""
        if analysis is None:
            return False
        try:
            beats_s = (analysis.list_downbeats() if kind == "downbeat"
                       else analysis.list_beats())
        except Exception:
            return False
        if not beats_s:
            return False
        beats_ms = np.asarray(beats_s, dtype=np.float64) * 1000.0
        idx = int(np.searchsorted(beats_ms, t_ms))
        for i in (idx - 1, idx):
            if 0 <= i < len(beats_ms) and abs(beats_ms[i] - t_ms) <= _BEAT_WINDOW_MS:
                return True
        return False

    def _check_signal_above(self, rule: Rule, norm: dict) -> bool:
        """signal_above:<src>:<thr> con histéresis (thr_off = thr * 0.8).

        Sólo dispara en el flanco ascendente (rising edge), para evitar
        disparos repetidos cuando la señal ronda el umbral.
        """
        parts = rule.trigger.split(":", 2)
        if len(parts) != 3:
            return False
        src, thr_str = parts[1], parts[2]
        try:
            thr = float(thr_str)
        except ValueError:
            return False

        val = float(norm.get(src, 0.0))

        if not rule._above and val > thr:
            rule._above = True
            return True                   # rising edge → dispara

        if rule._above and val < thr * 0.8:
            rule._above = False           # cae por debajo de thr_off → reset

        return False                      # sólo el flanco, no el nivel

    def _fire(self, rule: Rule, t_ms: float, live_engine) -> None:
        """Aplica el cooldown y ejecuta la acción si corresponde."""
        if t_ms - rule._last_fired_ms < rule.cooldown_ms:
            return
        rule._last_fired_ms = t_ms

        if rule.action.startswith("fire_effect:"):
            self._fire_effect(rule, t_ms, live_engine)
        elif rule.action.startswith("fire_pattern:"):
            self._fire_pattern(rule, t_ms, live_engine)

    def _fire_effect(self, rule: Rule, t_ms: float, live_engine) -> None:
        """fire_effect:<effect_id>:<scope>:<duration_ms>

        Crea un pattern efímero de 1 clip en memoria (no persiste) e inyecta
        un _EphemeralSlot en live_engine._active para que compute_live_frame
        lo renderice en el frame actual.
        """
        parts = rule.action.split(":", 3)
        if len(parts) != 4:
            return
        try:
            effect_id = int(parts[1])
            scope = parts[2]
            duration_ms = int(parts[3])
        except (ValueError, IndexError):
            return

        from src.core.timeline_model import Clip, Pattern

        pat_uid = f"autovj_effect_{rule.uid}"
        clip = Clip(
            track=0, start_ms=0, end_ms=duration_ms,
            effect_id=effect_id, scope=scope, params={},
        )
        pat = Pattern(uid=pat_uid, name=f"autovj:{rule.uid}",
                      color="#ff6600", clips=[clip])
        self._ephemeral_patterns[pat_uid] = pat.to_dict()

        slot_uid = f"autovj_{rule.uid}"
        live_engine._armed.pop(slot_uid, None)
        live_engine._active[slot_uid] = _EphemeralSlot(
            slot_uid=slot_uid,
            pattern_uid=pat_uid,
            started_at_ms=t_ms,
            mode="oneshot",
        )

    def _fire_pattern(self, rule: Rule, t_ms: float, live_engine) -> None:
        """fire_pattern:<pattern_uid>

        Busca el primer slot que ya tenga ese pattern_uid. Si no lo encuentra,
        usa el slot 15 (reservado para AutoVJ). Inyecta directamente en
        _active (quantize='free' = reactividad inmediata, sin esperar beats).
        """
        parts = rule.action.split(":", 1)
        if len(parts) != 2:
            return
        pattern_uid = parts[1]

        slot_idx = _AUTOVJ_SLOT_IDX
        for i, slot in enumerate(live_engine.slots):
            if slot.pattern_uid == pattern_uid:
                slot_idx = i
                break

        slot = live_engine.slots[slot_idx]
        if slot.pattern_uid != pattern_uid:
            slot.pattern_uid = pattern_uid

        slot_uid = slot.uid
        live_engine._armed.pop(slot_uid, None)
        live_engine._active[slot_uid] = _EphemeralSlot(
            slot_uid=slot_uid,
            pattern_uid=pattern_uid,
            started_at_ms=t_ms,
            mode="oneshot",
        )

    # ── Persistencia ─────────────────────────────────────────────────────────

    def save(self, path) -> None:
        """Guarda el ruleset activo en path (guardado atómico, no parte de show.json)."""
        if self.ruleset is None:
            return
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.ruleset.to_dict(), f, indent=2, ensure_ascii=False)
        tmp.replace(p)

    def load(self, path) -> None:
        """Carga un ruleset desde path. No-op si el archivo no existe."""
        p = Path(path)
        if not p.is_file():
            return
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        self.ruleset = RuleSet.from_dict(data)
