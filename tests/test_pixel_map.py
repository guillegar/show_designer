"""
test_pixel_map.py — Tests K2: pixel mapping imagen/vídeo → LEDs.

Cubre:
  test_sample_image_region_shape       — PNG 100x100, region (0,0,10,10) → shape (1,93,3)
  test_sample_image_region_dtype       — resultado uint8, valores en [0, 255]
  test_sample_image_tile_mode          — fit_mode="tile" → sin crash, shape correcta
  test_sample_image_missing_path       — source_path vacío/inexistente → array negro, sin excepción (I4)
  test_set_clip_pixel_map_updates_clip — handler actualiza params del clip y devuelve clip (I3)
"""
import io
import numpy as np
import pytest

# ── Helpers para crear PNG en memoria ────────────────────────────────────────

def _make_png_100x100(tmp_path) -> str:
    """Crea un PNG 100x100 de colores aleatorios y devuelve su ruta."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow no disponible")
    arr = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    path = tmp_path / "test_img.png"
    img.save(str(path))
    return str(path)


# ── Tests pixel_map core ──────────────────────────────────────────────────────

def test_sample_image_region_shape(tmp_path):
    """sample_image_region devuelve array de shape (1, 93, 3)."""
    from src.core.pixel_map import sample_image_region
    path = _make_png_100x100(tmp_path)
    result = sample_image_region(path, x=0, y=0, width=10, height=10,
                                 output_shape=(1, 93, 3))
    assert result.shape == (1, 93, 3)


def test_sample_image_region_dtype(tmp_path):
    """Resultado es uint8 con valores en [0, 255]."""
    from src.core.pixel_map import sample_image_region
    path = _make_png_100x100(tmp_path)
    result = sample_image_region(path, x=0, y=0, width=50, height=50,
                                 output_shape=(1, 93, 3))
    assert result.dtype == np.uint8
    assert int(result.min()) >= 0
    assert int(result.max()) <= 255


def test_sample_image_tile_mode(tmp_path):
    """fit_mode="tile" no lanza excepción y devuelve shape correcta."""
    from src.core.pixel_map import sample_image_region
    path = _make_png_100x100(tmp_path)
    result = sample_image_region(path, x=0, y=0, width=20, height=20,
                                 output_shape=(1, 93, 3), fit_mode="tile")
    assert result.shape == (1, 93, 3)
    assert result.dtype == np.uint8


def test_sample_image_missing_path():
    """source_path vacío o inexistente → array negro (1,93,3), sin excepción (I4)."""
    from src.core.pixel_map import sample_image_region

    # Vacío
    result = sample_image_region("", x=0, y=0, width=10, height=10)
    assert result.shape == (1, 93, 3)
    assert result.max() == 0

    # Inexistente
    result = sample_image_region("/tmp/no_existe_k2_test.png", x=0, y=0, width=10, height=10)
    assert result.shape == (1, 93, 3)
    assert result.max() == 0


# ── Test handler set_clip_pixel_map ──────────────────────────────────────────

def test_set_clip_pixel_map_updates_clip():
    """set_clip_pixel_map actualiza params del clip y devuelve clip actualizado (I3)."""
    from unittest.mock import MagicMock
    from server.dispatcher import _h_set_clip_pixel_map

    clip = MagicMock()
    clip.id = "clip_1"
    clip.params = {}
    clip.effect_id = None
    clip.to_dict.return_value = {"id": "clip_1", "effect_id": 1010}

    session = MagicMock()
    session.find_clip_by_id.return_value = clip

    res = _h_set_clip_pixel_map(session, {
        "clip_id": "clip_1",
        "source_path": "/shows/logo.png",
        "x": 10, "y": 20,
        "width": 50, "height": 50,
        "fit_mode": "stretch",
    })

    assert res["ok"] is True
    assert res["clip"]["effect_id"] == 1010
    assert clip.params["source_path"] == "/shows/logo.png"
    assert clip.params["x"] == 10
    assert clip.params["fit_mode"] == "stretch"
    assert clip.effect_id == 1010
    session.invalidate_caches.assert_called_once()
