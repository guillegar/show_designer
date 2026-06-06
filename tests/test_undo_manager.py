"""
test_undo_manager.py — UndoManager aislado (B2).

Sin Qt ni WebSocket ni ShowSession: clips falsos con to_dict().
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.undo_manager import UndoManager  # noqa: E402


class FakeClip:
    def __init__(self, v):
        self.v = v

    def to_dict(self):
        return {"v": self.v}


def _make(initial=1):
    state = {"clips": [FakeClip(initial)]}
    um = UndoManager(
        get_clips=lambda: state["clips"],
        restore_clips=lambda dicts: state.__setitem__(
            "clips", [FakeClip(d["v"]) for d in dicts]),
        max_depth=3,
    )
    return state, um


def test_undo_redo_roundtrip():
    state, um = _make(1)
    um.snapshot()                    # guarda [v=1]
    state["clips"] = [FakeClip(2)]   # muta a v=2
    assert um.undo() is True
    assert state["clips"][0].v == 1  # vuelve a 1
    assert um.redo() is True
    assert state["clips"][0].v == 2  # rehace a 2


def test_undo_redo_empty():
    _, um = _make()
    assert um.undo() is False
    assert um.redo() is False


def test_snapshot_clears_redo():
    state, um = _make(1)
    um.snapshot()
    state["clips"] = [FakeClip(2)]
    um.undo()                        # redo disponible
    um.snapshot()                    # una nueva edición limpia el redo
    assert um.redo() is False


def test_max_depth():
    _, um = _make()
    um.snapshot()
    um.snapshot()
    um.snapshot()
    um.snapshot()
    assert um.depth == 3             # tope respetado
