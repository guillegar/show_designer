"""
pixel_map.py — Función pura para mapear una región de imagen/vídeo a LEDs.

K2: soporte para PNG/JPG (via Pillow) y MP4 (via imageio, import lazy).
Si el archivo no está disponible → array negro, sin excepción (I4).
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np


# Cache de imágenes cargadas: {path: np.ndarray uint8 (H, W, 3)}
_IMG_CACHE: dict = {}


def _load_image(path: str) -> np.ndarray | None:
    """Carga imagen PNG/JPG con Pillow. Retorna array uint8 (H, W, 3) o None."""
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        return np.array(img, dtype=np.uint8)
    except Exception:
        return None


def _load_video_frame(path: str, frame_idx: int) -> np.ndarray | None:
    """Extrae un frame de vídeo MP4 con imageio (import lazy).

    Si imageio no está disponible, intenta cargar el archivo como imagen estática
    (útil para archivos .gif o formatos mixtos). Retorna array uint8 (H, W, 3) o None.
    """
    try:
        import imageio  # type: ignore
        reader = imageio.get_reader(path)
        total = reader.count_frames()
        idx = frame_idx % max(1, total)
        frame = reader.get_data(idx)
        reader.close()
        if frame.ndim == 2:
            frame = np.stack([frame, frame, frame], axis=-1)
        return frame[:, :, :3].astype(np.uint8)
    except Exception:
        return _load_image(path)


def _fit_region(region: np.ndarray, out_h: int, out_w: int,
                fit_mode: str) -> np.ndarray:
    """Escala/recorta region (H, W, 3) a (out_h, out_w, 3) según fit_mode."""
    try:
        from PIL import Image
        h, w = region.shape[:2]
        img = Image.fromarray(region)
        if fit_mode == "crop":
            scale = max(out_w / w, out_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - out_w) // 2
            top = (new_h - out_h) // 2
            img = img.crop((left, top, left + out_w, top + out_h))
        elif fit_mode == "tile":
            base = np.array(img.resize((max(1, out_w), max(1, out_h)), Image.NEAREST), dtype=np.uint8)
            return base
        else:  # stretch (default)
            img = img.resize((max(1, out_w), max(1, out_h)), Image.LANCZOS)
        return np.array(img, dtype=np.uint8)
    except Exception:
        return np.zeros((out_h, out_w, 3), dtype=np.uint8)


def sample_image_region(
    image_path: str,
    x: int,
    y: int,
    width: int,
    height: int,
    output_shape: Tuple[int, int, int] = (1, 93, 3),
    fit_mode: str = "stretch",
    frame_idx: int = 0,
) -> np.ndarray:
    """Carga la imagen/vídeo, recorta la región y escala a output_shape.

    Args:
        image_path:   ruta al archivo PNG/JPG/MP4
        x, y:         origen de la región (píxeles)
        width, height: tamaño de la región
        output_shape: (n_bars, leds_per_bar, 3) — forma de salida
        fit_mode:     "stretch" | "crop" | "tile"
        frame_idx:    índice de frame para vídeo (ignorado para imágenes)

    Returns:
        np.ndarray uint8 de shape output_shape. Si el archivo no existe o hay
        error de carga, retorna array negro sin lanzar excepción (I4).
    """
    if not image_path:
        return np.zeros(output_shape, dtype=np.uint8)

    path = str(image_path)
    suffix = Path(path).suffix.lower()

    # Cargar fuente
    if suffix in (".mp4", ".avi", ".mov", ".mkv", ".webm"):
        arr = _load_video_frame(path, frame_idx)
    else:
        arr = _IMG_CACHE.get(path)
        if arr is None:
            arr = _load_image(path)
            if arr is not None:
                _IMG_CACHE[path] = arr

    if arr is None:
        return np.zeros(output_shape, dtype=np.uint8)

    # Recortar región (clamp a los límites de la imagen)
    h, w = arr.shape[:2]
    x1 = max(0, min(x, w - 1))
    y1 = max(0, min(y, h - 1))
    x2 = max(x1 + 1, min(x + max(1, width), w))
    y2 = max(y1 + 1, min(y + max(1, height), h))
    region = arr[y1:y2, x1:x2]

    # Escalar a output_shape
    out_bars, out_leds, _ = output_shape
    fitted = _fit_region(region, out_bars, out_leds, fit_mode)

    # Ajustar shape si difiere
    if fitted.shape[0] != out_bars or fitted.shape[1] != out_leds:
        try:
            from PIL import Image
            img = Image.fromarray(fitted).resize((out_leds, out_bars), Image.NEAREST)
            fitted = np.array(img, dtype=np.uint8)
        except Exception:
            return np.zeros(output_shape, dtype=np.uint8)

    return fitted.reshape(output_shape).astype(np.uint8)
