"""
video_export.py — E3: Export de video preview desde render.npz.

Genera un GIF animado (siempre) o MP4 (si ffmpeg está en PATH) a partir
del npz producido por B3 (offline_render.py).

Cada frame del npz es (10, 93, 3) uint8: 10 barras × 93 LEDs × RGB.
La imagen resultante apila las barras verticalmente: height = 10*scale,
width = 93*scale (por defecto 40 × 372 px con scale=4).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np


def _frame_to_image(frame: np.ndarray, scale: int):
    """Convierte un frame (10, 93, 3) uint8 a PIL Image escalada."""
    from PIL import Image
    # np.kron escala sin loop: (10,93,3) → (10*scale, 93*scale, 3)
    scaled = np.kron(frame, np.ones((scale, scale, 1), dtype=np.uint8))
    return Image.fromarray(scaled.astype(np.uint8))


def export_preview(
    npz_path: str,
    out_path: str,
    format: str = "gif",
    scale: int = 4,
    fps: int = 30,
    progress_cb: Callable[[float], None] | None = None,
) -> None:
    """Exporta render.npz a GIF o MP4 de preview.

    Parámetros
    ----------
    npz_path   : ruta al render.npz generado por offline_render.py
    out_path   : ruta de salida (preview.gif o preview.mp4)
    format     : "gif" | "mp4"
    scale      : píxeles por LED (default 4 → 40×372 px)
    fps        : frames por segundo del video de salida
    progress_cb: callback(pct: float) llamado periódicamente (0..100)
    """
    if format not in ("gif", "mp4"):
        raise ValueError(f"format debe ser 'gif' o 'mp4', recibido: {format!r}")

    if format == "mp4" and shutil.which("ffmpeg") is None:
        raise ValueError("ffmpeg no encontrado en PATH")

    # Cargar frames
    data = np.load(str(npz_path))
    baked: np.ndarray = data["frames"]  # (n_frames, 10, 93, 3) uint8
    n_frames = len(baked)
    if n_frames == 0:
        raise ValueError("render.npz no contiene frames")

    out_path_obj = Path(out_path)
    tmp_path = out_path_obj.with_suffix(out_path_obj.suffix + ".tmp")

    if format == "gif":
        _export_gif(baked, str(tmp_path), scale, fps, n_frames, progress_cb)
    else:
        _export_mp4(baked, str(tmp_path), scale, fps, n_frames, progress_cb)

    # Escritura atómica
    os.replace(str(tmp_path), str(out_path_obj))

    if progress_cb:
        progress_cb(100.0)


def _export_gif(
    baked: np.ndarray,
    tmp_path: str,
    scale: int,
    fps: int,
    n_frames: int,
    progress_cb: Callable[[float], None] | None,
) -> None:

    duration_ms = max(1, round(1000 / fps))
    frames_pil = []
    report_every = max(1, n_frames // 20)

    for i, f in enumerate(baked):
        frames_pil.append(_frame_to_image(f, scale))
        if progress_cb and (i % report_every == 0):
            progress_cb(min(95.0, (i / n_frames) * 95.0))

    frames_pil[0].save(
        tmp_path,
        format="GIF",
        save_all=True,
        append_images=frames_pil[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )


def _export_mp4(
    baked: np.ndarray,
    tmp_path: str,
    scale: int,
    fps: int,
    n_frames: int,
    progress_cb: Callable[[float], None] | None,
) -> None:

    report_every = max(1, n_frames // 20)
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, f in enumerate(baked):
            img = _frame_to_image(f, scale)
            img.save(os.path.join(tmpdir, f"frame_{i:06d}.png"))
            if progress_cb and (i % report_every == 0):
                progress_cb(min(80.0, (i / n_frames) * 80.0))

        h = baked.shape[1] * scale
        w = baked.shape[2] * scale
        # Asegurar dimensiones pares (requerido por yuv420p)
        vf_scale = f"scale={w + w%2}:{h + h%2}"

        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(tmpdir, "frame_%06d.png"),
            "-vf", vf_scale,
            "-pix_fmt", "yuv420p",
            tmp_path,
        ]
        if progress_cb:
            progress_cb(85.0)
        subprocess.run(cmd, check=True, capture_output=True)
        if progress_cb:
            progress_cb(95.0)
