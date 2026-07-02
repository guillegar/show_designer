"""
test_preview_effect.py — Tests del handler preview_effect_frame (F4).

Cubre:
  - solid_color con r=255,g=0,b=0 → PNG válido, pixel es rojo.
  - Efecto inexistente → error limpio (ok=False, no lanza).
  - Sin Pillow (LUCES_NO_PILLOW=1) → frame_raw en vez de frame_b64.
  - ALL_BARS scope → imagen de 10 filas.
  - t_ms se pasa correctamente al render.
"""
import base64
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LUCES_NO_MCP_COMPAT", "1")


@pytest.fixture(scope="module")
def session():
    from server.session import ShowSession
    return ShowSession()


@pytest.fixture(scope="module")
def dispatcher(session):
    from server.dispatcher import Dispatcher
    return Dispatcher(session)


def call(dispatcher, method, params):
    import asyncio

    from server.dispatcher import _LOCAL
    handler = _LOCAL.get(method)
    assert handler is not None, f"Handler '{method}' no registrado"
    return handler(dispatcher.session, params)


# ── PNG válido, color correcto ───────────────────────────────────────────────

def test_solid_color_red_frame_b64(dispatcher):
    """solid_color con r=255,g=0,b=0 → PNG rojo."""
    res = call(dispatcher, "preview_effect_frame", {
        "effect_id": 1004,
        "params": {"r": 255, "g": 0, "b": 0},
        "t_ms": 0,
    })
    assert res["ok"], f"Error inesperado: {res.get('error')}"
    assert "frame_b64" in res, "Debe devolver frame_b64"

    import io

    from PIL import Image
    img_bytes = base64.b64decode(res["frame_b64"])
    img = Image.open(io.BytesIO(img_bytes))
    pix = img.getpixel((0, 0))
    assert pix[0] == 255, f"Canal R debe ser 255, es {pix[0]}"
    assert pix[1] == 0,   f"Canal G debe ser 0, es {pix[1]}"
    assert pix[2] == 0,   f"Canal B debe ser 0, es {pix[2]}"


def test_preview_returns_valid_png_dimensions(dispatcher):
    """El PNG devuelto tiene dimensiones ≥ 1×93 (1 fila PER_BAR, 93 LEDs, escala 2×)."""
    import io

    from PIL import Image
    res = call(dispatcher, "preview_effect_frame", {
        "effect_id": 1004,
        "params": {"r": 128, "g": 64, "b": 200},
        "t_ms": 500,
    })
    assert res["ok"]
    img = Image.open(io.BytesIO(base64.b64decode(res["frame_b64"])))
    w, h = img.size
    assert w == 93 * 2,  f"Ancho esperado {93*2}, obtenido {w}"
    assert h == 1 * 2,   f"Alto esperado {1*2} (PER_BAR×scale), obtenido {h}"


def test_per_bar_effect_gives_1_row(dispatcher):
    """rainbow_wave (PER_BAR, id=1017) → imagen de 1 fila × scale."""
    import io

    from PIL import Image
    res = call(dispatcher, "preview_effect_frame", {
        "effect_id": 1017,
        "params": {"speed": 1.0, "saturation": 1.0, "value": 1.0, "reverse": False},
        "t_ms": 0,
    })
    assert res["ok"]
    img = Image.open(io.BytesIO(base64.b64decode(res["frame_b64"])))
    _w, h = img.size
    # rainbow_wave es PER_BAR → (1, 93, 3) → con scale=2 → h=2
    assert h == 1 * 2, f"Alto esperado {1*2} (PER_BAR×scale), obtenido {h}"


# ── Error limpio para efecto inexistente ─────────────────────────────────────

def test_unknown_effect_returns_error(dispatcher):
    """Efecto inexistente → ok=False, no lanza excepción."""
    res = call(dispatcher, "preview_effect_frame", {"effect_id": 99999})
    assert res["ok"] is False
    assert "error" in res


def test_missing_effect_id_returns_error(dispatcher):
    """Sin effect_id → ValidationError limpia."""
    res = call(dispatcher, "preview_effect_frame", {})
    assert res["ok"] is False


# ── Fallback sin Pillow ───────────────────────────────────────────────────────

def test_no_pillow_returns_frame_raw(dispatcher, monkeypatch):
    """Con LUCES_NO_PILLOW=1 → frame_raw en vez de frame_b64."""
    monkeypatch.setenv("LUCES_NO_PILLOW", "1")
    res = call(dispatcher, "preview_effect_frame", {
        "effect_id": 1004,
        "params": {"r": 0, "g": 255, "b": 0},
        "t_ms": 0,
    })
    assert res["ok"]
    assert "frame_raw" in res, "Debe devolver frame_raw cuando LUCES_NO_PILLOW=1"
    assert "frame_b64" not in res
    # frame_raw: lista de listas de [r,g,b]
    raw = res["frame_raw"]
    assert isinstance(raw, list)
    assert len(raw) >= 1  # al menos 1 fila (PER_BAR)
    monkeypatch.delenv("LUCES_NO_PILLOW", raising=False)


# ── t_ms se pasa al render ───────────────────────────────────────────────────

def test_different_t_ms_gives_different_frame(dispatcher):
    """Para un efecto animado, t_ms=0 y t_ms=500 deben dar frames distintos."""
    def get_frame(t):
        res = call(dispatcher, "preview_effect_frame", {
            "effect_id": 1011,  # pixel_chase
            "params": {"r": 255, "g": 0, "b": 0, "speed": 30.0, "width": 3.0,
                       "mode": "bounce", "tail_decay": 0.8},
            "t_ms": t,
        })
        assert res["ok"]
        return res["frame_b64"]

    frame0 = get_frame(0)
    frame500 = get_frame(500)
    assert frame0 != frame500, "t_ms=0 y t_ms=500 deben dar frames distintos para pixel_chase"
