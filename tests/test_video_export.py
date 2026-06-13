"""tests/test_video_export.py — E3: export de video preview.

Tests:
  1. test_gif_export_creates_file: render sintético → GIF existe
  2. test_gif_dimensions: GIF tiene dimensiones (10*scale) × (93*scale)
  3. test_mp4_skips_without_ffmpeg: sin ffmpeg → ValueError
  4. test_atomic_write: tmp file no queda si se simula fallo
  5. test_no_npz_returns_error: handler sin render.npz → {ok:False}
"""
import os
import struct
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_npz(path: str, n_frames: int = 5) -> None:
    """Crea un render.npz sintético (n_frames, 10, 93, 3) uint8."""
    frames = np.random.randint(0, 255, (n_frames, 10, 93, 3), dtype=np.uint8)
    np.savez(path, frames=frames)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_gif_export_creates_file(tmp_path):
    npz = str(tmp_path / "render.npz")
    out = str(tmp_path / "preview.gif")
    _make_npz(npz, n_frames=5)

    from server.video_export import export_preview
    export_preview(npz, out, format="gif", scale=4)

    assert Path(out).exists()
    assert Path(out).stat().st_size > 0


def test_gif_dimensions(tmp_path):
    npz = str(tmp_path / "render.npz")
    out = str(tmp_path / "preview.gif")
    scale = 2
    _make_npz(npz, n_frames=3)

    from server.video_export import export_preview
    export_preview(npz, out, format="gif", scale=scale)

    from PIL import Image
    with Image.open(out) as img:
        w, h = img.size
    # width = 93*scale, height = 10*scale
    assert w == 93 * scale
    assert h == 10 * scale


def test_mp4_skips_without_ffmpeg(tmp_path):
    npz = str(tmp_path / "render.npz")
    out = str(tmp_path / "preview.mp4")
    _make_npz(npz, n_frames=3)

    from server.video_export import export_preview
    with patch("shutil.which", return_value=None):
        with pytest.raises(ValueError, match="ffmpeg"):
            export_preview(npz, out, format="mp4", scale=4)


def test_atomic_write(tmp_path):
    """El archivo .tmp no debe quedar si export_preview falla a mitad."""
    npz = str(tmp_path / "render.npz")
    out = str(tmp_path / "preview.gif")
    _make_npz(npz, n_frames=3)

    from server.video_export import export_preview

    # Simulamos fallo dentro de _export_gif (antes del os.replace)
    with patch("server.video_export._export_gif", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            export_preview(npz, out, format="gif", scale=4)

    # El archivo destino no debe existir
    assert not Path(out).exists()
    # Tampoco debe quedar el .tmp
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_no_npz_returns_error():
    """Handler export_video sin render.npz → {ok: False}."""
    from unittest.mock import MagicMock
    from pathlib import Path
    import server.dispatcher as disp

    handler = disp._LOCAL.get("export_video")
    assert handler is not None, "Handler export_video no registrado en _LOCAL"

    # Construir session con carpeta que no tiene npz
    session = MagicMock()
    session.export_in_progress = False  # evitar el "ya hay un export" path
    npz_mock = MagicMock()
    npz_mock.is_file.return_value = False
    session.project.folder.__truediv__ = MagicMock(return_value=npz_mock)

    result = handler(session, {"format": "gif"})
    assert result["ok"] is False
    assert "render" in result["error"].lower() or "sin render" in result["error"].lower()
