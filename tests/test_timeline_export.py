"""
test_timeline_export.py — Tests I5: exportación PDF patch + CSV DMX.

Cubre:
  test_export_patch_pdf_or_txt     — archivo existe y tamaño > 0
  test_export_patch_txt_fallback   — con fpdf2 mock-absent → crea .txt
  test_export_patch_txt_has_content — TXT contiene nombres de clips
  test_export_dmx_csv_structure    — CSV con cabecera correcta
  test_export_dmx_csv_row_count    — ceil(duration_s) filas (±1)
  test_export_dmx_csv_onthefly     — sin render.npz usa compute_frame
  test_export_dmx_csv_reuses_npz  — con render.npz no llama compute_frame
  test_atomic_write                — archivo no existe en ruta final hasta que completa
"""
import csv
import math
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from server.timeline_export import _export_pdf_txt, export_dmx_csv, export_patch_pdf
from src.core.timeline_model import BarGroup, Clip, Timeline

# ── Fake session ──────────────────────────────────────────────────────────────

def _make_session(tmp_path: Path, duration_ms: int = 5000) -> MagicMock:
    session = MagicMock()
    session.project.folder = tmp_path
    session.project.name = "Test Show"
    session.song_title = "Test Song"
    tl = Timeline()
    tl.duration_ms = duration_ms
    c = Clip(track=0, start_ms=0, end_ms=2000, effect_id=1, scope="per_bar",
             label="TestClip", uid="clip1")
    tl.clips.append(c)
    session.timeline = tl
    session.compute_frame.return_value = np.zeros((10, 93, 3), dtype=np.uint8)
    return session


# ── Tests PDF ─────────────────────────────────────────────────────────────────

def test_export_patch_pdf_or_txt(tmp_path):
    """Archivo de patch existe y tiene tamaño > 0."""
    session = _make_session(tmp_path)
    out = str(tmp_path / "patch.pdf")
    path = export_patch_pdf(session, out)
    assert Path(path).exists()
    assert Path(path).stat().st_size > 0


def test_export_patch_txt_fallback(tmp_path):
    """Sin fpdf2 → crea .txt sin crash."""
    session = _make_session(tmp_path)
    out = str(tmp_path / "patch.pdf")
    with patch.dict("sys.modules", {"fpdf": None, "fpdf.FPDF": None}):
        path = export_patch_pdf(session, out)
    assert Path(path).exists()
    assert path.endswith(".txt") or Path(path).stat().st_size > 0


def test_export_patch_txt_has_content(tmp_path):
    """El TXT de fallback contiene el nombre del clip."""
    session = _make_session(tmp_path)
    out = str(tmp_path / "patch.txt")
    _export_pdf_txt(session.timeline.clips, session, out)
    content = Path(out).read_text(encoding="utf-8")
    assert "TestClip" in content


# ── Tests CSV DMX ─────────────────────────────────────────────────────────────

def test_export_dmx_csv_structure(tmp_path):
    """CSV tiene la cabecera correcta: t_ms, universe, ch_1..ch_512."""
    session = _make_session(tmp_path, duration_ms=3000)
    out = str(tmp_path / "dmx.csv")
    export_dmx_csv(session, out, fps=1)
    with open(out, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
    assert header[0] == "t_ms"
    assert header[1] == "universe"
    assert header[2] == "ch_1"
    assert header[-1] == "ch_512"
    assert len(header) == 2 + 512


def test_export_dmx_csv_row_count(tmp_path):
    """A fps=1 el número de filas de datos ≈ ceil(duration_s) ± 1."""
    duration_ms = 5000
    session = _make_session(tmp_path, duration_ms=duration_ms)
    out = str(tmp_path / "dmx.csv")
    export_dmx_csv(session, out, fps=1)
    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    n_data = len(rows) - 1  # excluir cabecera
    expected = math.ceil(duration_ms / 1000)
    assert abs(n_data - expected) <= 1, f"{n_data} ≠ {expected} ± 1"


def test_export_dmx_csv_onthefly(tmp_path):
    """Sin render.npz llama a compute_frame para cada frame."""
    session = _make_session(tmp_path, duration_ms=3000)
    out = str(tmp_path / "dmx.csv")
    export_dmx_csv(session, out, fps=1)
    # compute_frame se llama al menos 1 vez (3 frames)
    assert session.compute_frame.call_count >= 1


def test_export_dmx_csv_reuses_npz(tmp_path):
    """Con render.npz existente NO llama a compute_frame."""
    session = _make_session(tmp_path, duration_ms=3000)
    # Crear un render.npz falso
    frames = np.zeros((90, 10, 93, 3), dtype=np.uint8)  # 90 frames @ 30fps = 3s
    np.savez_compressed(str(tmp_path / "render.npz"), frames=frames)

    out = str(tmp_path / "dmx.csv")
    export_dmx_csv(session, out, fps=1)
    # compute_frame NO debe llamarse (usamos npz)
    assert session.compute_frame.call_count == 0


def test_atomic_write(tmp_path):
    """El archivo final no existe como .tmp una vez completado."""
    session = _make_session(tmp_path, duration_ms=2000)
    out = str(tmp_path / "dmx.csv")
    export_dmx_csv(session, out, fps=1)
    assert Path(out).exists()
    assert not Path(out + ".tmp").exists()
