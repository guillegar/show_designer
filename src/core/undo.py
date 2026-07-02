"""
undo.py — Undo/redo del timeline, FUENTE ÚNICA (ANALYSIS hallazgo 9).

Antes existían dos implementaciones separadas (server/undo_manager.py y
src/ui/timeline_editor.py) que podían divergir en semántica. Ambas usan el MISMO
modelo: una pila de snapshots de clips (listas de dicts vía `Clip.to_dict()`).
Aquí viven las dos, consumidas por el server y por el editor Qt respectivamente:

  - `UndoManager`            → CANÓNICA, basada en callbacks (sin Qt ni WebSocket,
                               testeable). La usa el backend headless (server).
  - `ClipSnapshotUndoManager`→ API "push" (snapshot(clips) → undo()→clips) que usa
                               el editor Qt legacy. Misma semántica de snapshots.

`ClipSnapshotUndoManager` es candidata a fusionarse con `UndoManager` cuando se
retire la UI Qt (Fase 7). Mantenerlas aquí garantiza que no se desincronicen.
"""
from __future__ import annotations

from collections.abc import Callable

from src.core.timeline_model import Clip

# ── Canónica (callbacks, sin Qt) — la consume el server headless ─────────────

class UndoManager:
    """Undo/redo por snapshots del timeline, desacoplado vía callbacks.

    `snapshot()` se llama ANTES de cada mutación y guarda el estado previo;
    `undo()`/`redo()` intercambian entre las pilas. Coste O(nº clips) por edición
    (no por frame). Profundidad limitada a `max_depth`.

    A3 (ROADMAP v2): se añaden `get_extra`/`restore_extra` opcionales para
    incluir patterns y pattern_instances en el snapshot (invariante I1).
    La extensión es backward-compatible: las instancias sin extras siguen
    funcionando igual y los stacks legacy (listas de dicts) se restauran
    correctamente.
    """

    def __init__(
        self,
        get_clips: Callable[[], list],
        restore_clips: Callable[[list], None],
        get_extra: Callable[[], dict] | None = None,
        restore_extra: Callable[[dict], None] | None = None,
        max_depth: int = 60,
    ):
        """
        Args:
            get_clips: devuelve la lista de Clip actual del timeline.
            restore_clips: aplica una lista de dicts (restaura los clips).
            get_extra: (A3) devuelve dict con entidades extra a snapshotear
                       (p.ej. {"patterns": [...], "pattern_instances": [...]}).
            restore_extra: (A3) restaura las entidades extra del snapshot.
            max_depth: tope de niveles de undo en memoria.
        """
        self._get_clips = get_clips
        self._restore_clips = restore_clips
        self._get_extra = get_extra
        self._restore_extra = restore_extra
        self._max = max_depth
        self._undo: list = []
        self._redo: list = []

    def _snapshot_current(self):
        snap: dict = {"clips": [c.to_dict() for c in self._get_clips()]}
        if self._get_extra is not None:
            snap["extra"] = self._get_extra()
        return snap

    def _do_restore(self, snap) -> None:
        """Restaura un snapshot, compatible con el formato antiguo (lista directa)."""
        if isinstance(snap, list):
            # Formato legacy: sólo lista de clip dicts
            self._restore_clips(snap)
        else:
            self._restore_clips(snap["clips"])
            if self._restore_extra is not None and "extra" in snap:
                self._restore_extra(snap["extra"])

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
        self._do_restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot_current())
        self._do_restore(self._redo.pop())
        return True

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    @property
    def depth(self) -> int:
        return len(self._undo)


# ── API "push" — la consume el editor Qt legacy (timeline_editor.py) ─────────

class ClipSnapshotUndoManager:
    """Snapshot-based undo/redo sobre la lista de clips (API push para Qt).

    El caller pasa los clips a `snapshot()` y recibe la lista restaurada de
    `undo()`/`redo()`. Misma semántica de snapshots que `UndoManager`.
    """
    def __init__(self, max_size: int = 60):
        self._stack: list[list] = []   # lista de snapshots (listas de dicts)
        self._pos   = -1
        self._max   = max_size

    def snapshot(self, clips: list[Clip]):
        """Guardar estado ANTES de una modificación."""
        self._stack = self._stack[:self._pos + 1]
        self._stack.append([c.to_dict() for c in clips])
        if len(self._stack) > self._max:
            self._stack.pop(0)
        else:
            self._pos += 1

    def undo(self) -> list[Clip] | None:
        if self._pos <= 0:
            return None
        self._pos -= 1
        return [Clip.from_dict(d) for d in self._stack[self._pos]]

    def redo(self) -> list[Clip] | None:
        if self._pos >= len(self._stack) - 1:
            return None
        self._pos += 1
        return [Clip.from_dict(d) for d in self._stack[self._pos]]

    @property
    def can_undo(self): return self._pos > 0
    @property
    def can_redo(self): return self._pos < len(self._stack) - 1
