"""
undo_manager.py — re-export de la fuente única `src/core/undo` (ANALYSIS hallazgo 9).

La implementación canónica (callbacks, sin Qt) vive ahora en `src/core/undo.py`
y la comparten el server headless y el editor Qt. Este módulo se mantiene para no
romper los imports existentes (`from server.undo_manager import UndoManager`).
"""
from src.core.undo import UndoManager

__all__ = ["UndoManager"]
