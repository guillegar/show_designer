"""
undo_manager.py — Undo/redo del timeline, extraído de ShowSession (SRP, B2).

Modelo: pila de snapshots de los clips (listas de dicts). `snapshot()` se llama
ANTES de cada mutación y guarda el estado previo; `undo()`/`redo()` intercambian
entre las pilas. Misma semántica que la versión embebida en ShowSession, pero
aislada y testeable sin Qt ni WebSocket.

El coste de snapshot es O(nº clips) por edición (no por frame: el tick a 30 FPS
no hace snapshot), así que es asumible. La profundidad se limita a `max_depth`.
"""
from __future__ import annotations

from typing import Callable, List


class UndoManager:
    def __init__(
        self,
        get_clips: Callable[[], list],
        restore_clips: Callable[[list], None],
        max_depth: int = 60,
    ):
        """
        Args:
            get_clips: devuelve la lista de Clip actual del timeline.
            restore_clips: aplica una lista de dicts (restaura el timeline).
            max_depth: tope de niveles de undo en memoria.
        """
        self._get_clips = get_clips
        self._restore_clips = restore_clips
        self._max = max_depth
        self._undo: List[list] = []
        self._redo: List[list] = []

    def _snapshot_current(self) -> list:
        return [c.to_dict() for c in self._get_clips()]

    def snapshot(self) -> None:
        """Guarda el estado actual (llamar ANTES de mutar)."""
        self._undo.append(self._snapshot_current())
        if len(self._undo) > self._max:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot_current())
        self._restore_clips(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot_current())
        self._restore_clips(self._redo.pop())
        return True

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    @property
    def depth(self) -> int:
        return len(self._undo)
