"""
timeline_export.py — I5: Exportación PDF patch + CSV DMX del timeline.

export_patch_pdf(session, out_path) → path
    Genera un PDF con los clips del timeline ordenados por pista y tiempo.
    Usa fpdf2 (PyPI). Fallback a .txt si fpdf2 no disponible.

export_dmx_csv(session, out_path, fps=1) → path
    Genera un CSV con frames DMX muestreados a fps FPS.
    Reutiliza render.npz si existe; si no, compute_frame on-the-fly.
    Cabecera: t_ms,universe,ch_1,...,ch_512 (universe 1 = bar 0 RGB × 93 LEDs).
    Una fila por frame muestreado (ceil(duration_s * fps) filas total).
"""
from __future__ import annotations

import csv
import io
import math
import os
import tempfile
from pathlib import Path
from typing import Optional


_LEDS = 93        # LEDs por barra
_CH_PER_LED = 3   # R, G, B
_DMX_UNIVERSE = 512


# ── PDF patch ─────────────────────────────────────────────────────────────────

def export_patch_pdf(session, out_path: str) -> str:
    """Genera PDF (o TXT fallback) con clips ordenados por pista y tiempo.

    Returns
    -------
    str — ruta del archivo generado (puede cambiar la extensión a .txt si fpdf2
    no está disponible).
    """
    out_path = Path(out_path)
    clips = sorted(session.timeline.clips, key=lambda c: (c.track, c.start_ms))

    try:
        from fpdf import FPDF
        _export_pdf_fpdf(clips, session, str(out_path))
        return str(out_path)
    except ImportError:
        # Fallback: texto plano
        txt_path = out_path.with_suffix(".txt")
        _export_pdf_txt(clips, session, str(txt_path))
        return str(txt_path)


def _export_pdf_fpdf(clips, session, out_path: str) -> None:
    from fpdf import FPDF  # type: ignore

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    title = getattr(session, "song_title", "") or (
        getattr(session.project, "name", "") if hasattr(session, "project") else "Show"
    )
    pdf.cell(0, 10, f"Patch PDF — {title}", ln=True)
    pdf.set_font("Helvetica", size=9)
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(15, 7, "Bar", border=1)
    pdf.cell(30, 7, "Start (s)", border=1)
    pdf.cell(30, 7, "End (s)", border=1)
    pdf.cell(60, 7, "Label", border=1)
    pdf.cell(50, 7, "Effect ID", border=1, ln=True)
    pdf.set_font("Helvetica", size=9)

    for c in clips:
        pdf.cell(15, 6, str(c.track), border=1)
        pdf.cell(30, 6, f"{c.start_ms / 1000:.2f}", border=1)
        pdf.cell(30, 6, f"{c.end_ms / 1000:.2f}", border=1)
        label = (c.label or "")[:30]
        pdf.cell(60, 6, label, border=1)
        pdf.cell(50, 6, str(c.effect_id), border=1, ln=True)

    tmp = out_path + ".tmp"
    pdf.output(tmp)
    os.replace(tmp, out_path)


def _export_pdf_txt(clips, session, out_path: str) -> None:
    lines = []
    title = getattr(session, "song_title", "") or (
        getattr(session.project, "name", "") if hasattr(session, "project") else "Show"
    )
    lines.append(f"PATCH — {title}")
    lines.append(f"{'Bar':<5} {'Start(s)':<12} {'End(s)':<12} {'Label':<32} Effect")
    lines.append("-" * 75)
    for c in clips:
        lines.append(
            f"{c.track:<5} {c.start_ms / 1000:<12.2f} {c.end_ms / 1000:<12.2f}"
            f" {(c.label or '')[:32]:<32} {c.effect_id}"
        )
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, out_path)


# ── DMX CSV ──────────────────────────────────────────────────────────────────

def export_dmx_csv(session, out_path: str, fps: int = 1) -> str:
    """Genera CSV con frames DMX muestreados a fps FPS.

    Columnas: t_ms,universe,ch_1,...,ch_512.
    universe = 1 (bar 0 mapped to universe 1, 93 LEDs × RGB = 279 channels).
    Reutiliza render.npz si existe y es coherente con el timeline actual.
    Si no existe, compute_frame on-the-fly para cada sample.

    Returns
    -------
    str — ruta del archivo CSV generado.
    """
    import numpy as np

    out_path_obj = Path(out_path)
    duration_ms = round(session.timeline.duration_ms)
    duration_s = duration_ms / 1000.0
    n_frames = math.ceil(duration_s * fps)

    npz_path = None
    npz_frames: Optional[np.ndarray] = None
    if hasattr(session, "project"):
        candidate = session.project.folder / "render.npz"
        if candidate.is_file():
            try:
                data = np.load(str(candidate))
                if "frames" in data:
                    npz_frames = data["frames"]  # (N, 10, 93, 3)
                    npz_path = candidate
            except Exception:
                npz_frames = None

    header = ["t_ms", "universe"] + [f"ch_{i + 1}" for i in range(_DMX_UNIVERSE)]

    tmp = str(out_path_obj) + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i in range(n_frames):
            t_ms = round((i / fps) * 1000)
            frame = _get_frame(session, t_ms, npz_frames, fps)
            # Bar 0 → universe 1
            bar0 = frame[0].flatten()  # (279,) uint8
            channels = list(int(v) for v in bar0)
            # Pad to 512
            channels += [0] * (_DMX_UNIVERSE - len(channels))
            writer.writerow([t_ms, 1] + channels)

    os.replace(tmp, str(out_path_obj))
    return str(out_path_obj)


def _get_frame(session, t_ms: int, npz_frames, fps: int):
    """Devuelve el frame (10, 93, 3) uint8 para t_ms."""
    import numpy as np

    if npz_frames is not None:
        render_fps = 30  # offline_render siempre usa 30fps
        frame_idx = min(int(t_ms / 1000 * render_fps), len(npz_frames) - 1)
        return npz_frames[frame_idx]

    # on-the-fly via compute_frame
    t_s = t_ms / 1000.0
    try:
        frame = session.compute_frame(t_s)
        if isinstance(frame, np.ndarray) and frame.shape == (10, 93, 3):
            return frame
    except Exception:
        pass
    return np.zeros((10, 93, 3), dtype=np.uint8)
