"""
live_engine.py — Motor de performance en vivo (C1, ROADMAP v2).

Estado de EJECUCIÓN: _active y _armed viven solo en memoria (no se persisten).
Los slots SÍ se persisten en show.json bajo "live_slots" (son configuración).

Invariante I4: compute_live_frame es numpy puro, sin I/O ni awaits.
Reutiliza la expansión de patrones de A3 (Pattern.from_dict + resolve_params).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

import numpy as np

NUM_LIVE_SLOTS = 16


@dataclass
class LiveSlot:
    uid: str
    pattern_uid: Optional[str] = None
    key: str = ""
    quantize: str = "bar"    # "bar" | "beat" | "free"
    mode: str = "oneshot"    # "oneshot" | "loop" | "hold"

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "pattern_uid": self.pattern_uid,
            "key": self.key,
            "quantize": self.quantize,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LiveSlot":
        return cls(
            uid=d.get("uid") or uuid4().hex[:8],
            pattern_uid=d.get("pattern_uid") or None,
            key=str(d.get("key", "")),
            quantize=str(d.get("quantize", "bar")),
            mode=str(d.get("mode", "oneshot")),
        )


@dataclass
class ActiveSlot:
    slot_uid: str
    pattern_uid: str
    started_at_ms: float
    mode: str    # "oneshot" | "loop" | "hold"


class LiveEngine:
    """Motor de lanzamiento en vivo: 16 slots con cuantización a beats/downbeats."""

    def __init__(self) -> None:
        self.slots: List[LiveSlot] = [
            LiveSlot(uid=uuid4().hex[:8]) for _ in range(NUM_LIVE_SLOTS)
        ]
        self._active: Dict[str, ActiveSlot] = {}   # slot_uid → ActiveSlot
        self._armed: Dict[str, float] = {}          # slot_uid → t_armed_ms

    # ── Cuantización ─────────────────────────────────────────────────────────

    @staticmethod
    def _next_boundary(t_ms: float, quantize: str, analysis) -> float:
        """Primer límite de cuantización DESPUÉS de t_ms (en ms).

        Degrada a t_ms (free) si:
          - quantize == "free"
          - analysis es None
          - la lista de beats/downbeats está vacía
          - ya superamos el último límite
        """
        if quantize == "free" or analysis is None:
            return t_ms
        try:
            beats_s: List[float] = (
                analysis.list_downbeats() if quantize == "bar"
                else analysis.list_beats()
            )
        except Exception:
            return t_ms
        if not beats_s:
            return t_ms
        for b_s in beats_s:
            b_ms = b_s * 1000.0
            if b_ms > t_ms:
                return b_ms
        return t_ms   # pasamos el último límite → free

    @staticmethod
    def _has_beats(quantize: str, analysis) -> bool:
        """True si hay beats disponibles para la cuantización pedida."""
        if quantize == "free" or analysis is None:
            return True
        try:
            if quantize == "bar":
                return bool(analysis.list_downbeats())
            return bool(analysis.list_beats())
        except Exception:
            return False

    # ── API de slots ─────────────────────────────────────────────────────────

    def assign_slot(self, slot_idx: int,
                    pattern_uid: Optional[str] = None,
                    key: Optional[str] = None,
                    quantize: Optional[str] = None,
                    mode: Optional[str] = None) -> LiveSlot:
        """Actualiza la configuración de un slot.

        Si cambia el pattern_uid, detiene la reproducción del slot.
        """
        if slot_idx < 0 or slot_idx >= NUM_LIVE_SLOTS:
            raise IndexError(f"slot_idx must be 0..{NUM_LIVE_SLOTS - 1}")
        slot = self.slots[slot_idx]
        old_pattern = slot.pattern_uid
        if pattern_uid is not None:
            slot.pattern_uid = pattern_uid if pattern_uid else None
        if key is not None:
            slot.key = key
        if quantize is not None:
            slot.quantize = quantize
        if mode is not None:
            slot.mode = mode
        if old_pattern != slot.pattern_uid:
            self._active.pop(slot.uid, None)
            self._armed.pop(slot.uid, None)
        return slot

    def trigger(self, slot_idx: int, t_ms: float,
                analysis=None) -> Tuple[LiveSlot, float]:
        """Dispara un slot; queda armado hasta el próximo límite de cuantización.

        Si el slot ya estaba activo (loop u otro modo), se detiene y se re-arma.
        Returns (slot, t_armed_ms).
        """
        slot = self.slots[slot_idx]
        if slot.pattern_uid is None:
            return slot, t_ms
        t_armed = self._next_boundary(t_ms, slot.quantize, analysis)
        self._active.pop(slot.uid, None)
        self._armed[slot.uid] = t_armed
        return slot, t_armed

    def release(self, slot_idx: int) -> LiveSlot:
        """Detiene un slot (relevante para mode='hold'; para otros modos también para.)"""
        slot = self.slots[slot_idx]
        self._active.pop(slot.uid, None)
        self._armed.pop(slot.uid, None)
        return slot

    def stop_all(self) -> None:
        """Pánico: detiene todos los slots activos y armados."""
        self._active.clear()
        self._armed.clear()

    # ── Render (I4: numpy puro, sin I/O) ────────────────────────────────────

    def compute_live_frame(self, t_ms: float, patterns: list,
                            library, param_stages: list,
                            actx: dict) -> np.ndarray:
        """Renderiza la capa live sobre un frame negro (10×93×3 uint8).

        Args:
            t_ms: tiempo actual en milisegundos
            patterns: lista de dicts de patterns (timeline.patterns)
            library: EffectLibrary para resolver efectos
            param_stages: pipeline de parámetros (modulación/automatización)
            actx: audio_context del frame (para modulación A1)
        Returns:
            Array (NUM_BARS, LEDS_PER_BAR, 3) uint8 — mezclar con np.maximum
            sobre el frame del timeline.
        """
        from src.core.effects_engine import NUM_BARS, LEDS_PER_BAR

        frame = np.zeros((NUM_BARS, LEDS_PER_BAR, 3), dtype=np.uint8)

        if not self._active and not self._armed:
            return frame   # fast path: cero coste cuando no hay nada activo

        # Promover _armed → _active cuando llega su tiempo
        newly_active: List[Tuple[str, LiveSlot, float]] = []
        to_disarm: List[str] = []
        for slot_uid, t_armed in list(self._armed.items()):
            if t_ms >= t_armed:
                slot = next((s for s in self.slots if s.uid == slot_uid), None)
                if slot is not None and slot.pattern_uid is not None:
                    newly_active.append((slot_uid, slot, t_armed))
                to_disarm.append(slot_uid)
        for uid in to_disarm:
            del self._armed[uid]
        for slot_uid, slot, t_armed in newly_active:
            self._active[slot_uid] = ActiveSlot(
                slot_uid=slot_uid,
                pattern_uid=slot.pattern_uid,
                started_at_ms=t_armed,   # empieza EXACTAMENTE en el límite armado
                mode=slot.mode,
            )

        # Renderizar slots activos
        from src.core.timeline_model import Pattern
        from src.core.param_pipeline import resolve_params

        expired: List[str] = []
        for slot_uid, aslot in list(self._active.items()):
            pat_d = next(
                (p for p in patterns if p.get("uid") == aslot.pattern_uid), None
            )
            if pat_d is None:
                expired.append(slot_uid)
                continue

            pat = Pattern.from_dict(pat_d)
            if not pat.clips:
                continue

            pattern_duration = max(c.end_ms for c in pat.clips)
            if pattern_duration <= 0:
                continue

            t_rel = t_ms - aslot.started_at_ms

            if aslot.mode == "oneshot":
                if t_rel >= pattern_duration:
                    expired.append(slot_uid)
                    continue
            elif aslot.mode == "loop":
                t_rel = t_rel % pattern_duration
            # "hold": permanece activo hasta que release() lo limpie

            t_rel_int = int(t_rel)

            for clip in pat.clips:
                if clip.start_ms > t_rel_int or clip.end_ms <= t_rel_int:
                    continue
                if getattr(clip, "muted", False):
                    continue
                eff = library.get_effect(clip.effect_id)
                if not eff:
                    continue
                params = resolve_params(
                    clip, t_rel_int, actx, param_stages, base_params=clip.params
                )
                try:
                    r = eff.render(
                        elapsed_time=t_rel_int - clip.start_ms,
                        bars_state=frame,
                        audio_context=actx,
                        **params,
                    )
                    if r.ndim == 3 and r.shape[0] == 1 and 0 <= clip.track < NUM_BARS:
                        frame[clip.track] = np.maximum(frame[clip.track], r[0])
                    elif r.ndim == 3 and r.shape[0] == NUM_BARS:
                        scope = getattr(clip, "scope", "per_bar")
                        if scope == "global":
                            frame = np.maximum(frame, r)
                        elif 0 <= clip.track < NUM_BARS:
                            frame[clip.track] = np.maximum(
                                frame[clip.track], r[clip.track]
                            )
                except Exception:
                    pass

        for uid in expired:
            self._active.pop(uid, None)

        return frame

    # ── Persistencia de la configuración de slots ─────────────────────────────

    def slots_to_dicts(self) -> list:
        return [s.to_dict() for s in self.slots]

    def slots_from_dicts(self, dicts: list) -> None:
        """Restaura la configuración de slots desde dicts. Limpia el runtime."""
        for i, d in enumerate(dicts[:NUM_LIVE_SLOTS]):
            self.slots[i] = LiveSlot.from_dict(d)
        self._active.clear()
        self._armed.clear()

    # ── Estado serializable para la UI ────────────────────────────────────────

    def get_state(self, analysis=None) -> dict:
        """Estado completo de los 16 slots + activos + armados."""
        slots_list = []
        for i, slot in enumerate(self.slots):
            sd = slot.to_dict()
            sd["idx"] = i
            sd["active"] = slot.uid in self._active
            sd["armed"] = slot.uid in self._armed
            sd["degraded"] = (
                slot.pattern_uid is not None
                and slot.quantize != "free"
                and not self._has_beats(slot.quantize, analysis)
            )
            if slot.uid in self._armed:
                sd["armed_at_ms"] = self._armed[slot.uid]
            slots_list.append(sd)
        return {
            "slots": slots_list,
            "active": list(self._active.keys()),
            "armed": list(self._armed.keys()),
        }
