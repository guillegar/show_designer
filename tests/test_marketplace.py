"""
test_marketplace.py — Tests del Marketplace de plugins (N1).
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── helpers ─────────────────────────────────────────────────────────────────

_DUMMY_PLUGIN = """\
import numpy as np
from src.core.effects_engine import Effect, EffectScope

class DummyEffect(Effect):
    EFFECT_ID = 9901
    NAME = "Dummy Marketplace Effect"
    FAMILY = "test"
    scope = EffectScope.PER_BAR
    PARAM_SCHEMA = {}

    def render(self, elapsed_time, bars_state, audio_context, **params):
        return np.zeros((1, bars_state.shape[1], 3), dtype=np.uint8)
"""

_BAD_PLUGIN = """\
# Plugin que falla la validación (render devuelve None)
from src.core.effects_engine import Effect, EffectScope
class BadEffect(Effect):
    EFFECT_ID = 9902
    NAME = "Bad"
    FAMILY = "test"
    scope = EffectScope.PER_BAR
    PARAM_SCHEMA = {}

    def render(self, elapsed_time, bars_state, audio_context, **params):
        return None  # invalido: debe ser ndarray
"""

_MANIFEST = [
    {
        "name": "gradient_sweep_pro",
        "author": "comunidad",
        "version": "1.1",
        "effect_ids": [9901],
        "download_url": "http://example.com/plugins/dummy.py",
        "description": "Sweep mejorado",
    }
]


def _mock_httpx_response(json_data=None, text_data=None, status=200):
    resp = MagicMock()
    resp.status_code = status
    if json_data is not None:
        resp.json.return_value = json_data
    if text_data is not None:
        resp.text = text_data
    resp.raise_for_status = MagicMock()
    return resp


# ─── tests ───────────────────────────────────────────────────────────────────

def test_list_marketplace_plugins_returns_manifest(tmp_path, monkeypatch):
    """list_marketplace_plugins devuelve la lista del manifest."""
    import server.marketplace as mp
    mp.invalidate_cache()

    with patch("httpx.get", return_value=_mock_httpx_response(json_data=_MANIFEST)):
        data, cached = mp.fetch_manifest("http://example.com/manifest.json")

    assert len(data) == 1
    assert data[0]["name"] == "gradient_sweep_pro"
    assert cached is False


def test_fetch_manifest_cache(monkeypatch):
    """Segunda llamada en < 5 min usa caché sin HTTP."""
    import server.marketplace as mp
    mp.invalidate_cache()

    with patch("httpx.get", return_value=_mock_httpx_response(json_data=_MANIFEST)) as mock_get:
        mp.fetch_manifest("http://example.com/manifest.json")
        data2, cached2 = mp.fetch_manifest("http://example.com/manifest.json")

    assert cached2 is True
    assert mock_get.call_count == 1  # solo una llamada HTTP


def test_fetch_manifest_timeout():
    """Timeout en el fetch → lanza TimeoutError."""
    import server.marketplace as mp
    import httpx
    mp.invalidate_cache()

    with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
        with pytest.raises(TimeoutError):
            mp.fetch_manifest("http://example.com/manifest.json")


def test_install_plugin_valid(tmp_path):
    """install_plugin con .py válido → instalado y ok."""
    import server.marketplace as mp

    with patch("httpx.get", return_value=_mock_httpx_response(text_data=_DUMMY_PLUGIN)):
        result = mp.install_plugin("http://example.com/plugins/dummy.py", tmp_path)

    assert result["ok"] is True
    assert result["name"] == "dummy.py"
    assert (tmp_path / "dummy.py").exists()


def test_install_plugin_harness_fail(tmp_path):
    """install_plugin con .py que falla el harness → rechazado sin instalar."""
    import server.marketplace as mp

    with patch("httpx.get", return_value=_mock_httpx_response(text_data=_BAD_PLUGIN)):
        result = mp.install_plugin("http://example.com/plugins/bad.py", tmp_path)

    assert result["ok"] is False
    assert "harness" in result["error"] or "error" in result
    # el archivo destino NO debe haberse instalado
    assert not (tmp_path / "bad.py").exists()
