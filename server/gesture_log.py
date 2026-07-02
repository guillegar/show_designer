"""
gesture_log.py — Historial de gestos en sesión en vivo (M3).

Registra los handlers ejecutados (excluyendo list_/get_/preview_/auth_).
Permite listarlos y re-ejecutarlos (replay).
Buffer circular de MAX_ENTRIES entradas.
"""
from __future__ import annotations

import builtins
import time
from typing import Any

_SKIP_PREFIXES = ("list_", "get_", "preview_", "auth_", "clear_gesture", "list_gesture", "replay_gesture")


class GestureLog:
    MAX_ENTRIES = 500

    def __init__(self):
        self._log: list[dict[str, Any]] = []
        self._idx_counter: int = 0

    def should_record(self, handler: str) -> bool:
        """True si el handler debe grabarse."""
        for prefix in _SKIP_PREFIXES:
            if handler.startswith(prefix):
                return False
        return True

    def record(self, handler: str, params: dict, t_ms: int) -> None:
        """Registra un gesto. Descarta el más antiguo si se supera MAX_ENTRIES."""
        if not self.should_record(handler):
            return
        entry = {
            "idx": self._idx_counter,
            "handler": handler,
            "params": dict(params) if params else {},
            "t_ms": t_ms,
            "ts_wall": round(time.time(), 3),
        }
        self._log.append(entry)
        self._idx_counter += 1
        if len(self._log) > self.MAX_ENTRIES:
            self._log.pop(0)

    def list(self, last: int = 200) -> builtins.list[dict]:
        """Devuelve los últimos `last` gestos (más reciente al final)."""
        return list(self._log[-last:])

    def get(self, idx: int) -> dict | None:
        """Busca un gesto por su idx global (no por posición en el buffer)."""
        for entry in self._log:
            if entry["idx"] == idx:
                return entry
        return None

    def clear(self) -> None:
        self._log.clear()
