"""
test_security_hardening.py — Hardening de seguridad (FIX 1-10).

Cubre: zip slip, marketplace SSRF/RCE, timing-safe tokens, webhook SSRF.
"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── FIX 1: Zip Slip ─────────────────────────────────────────────────────────

def test_zip_slip_blocked(tmp_path):
    """import_show_bundle debe lanzar ValueError ante un entry con path traversal."""
    from server.show_bundle import _MANIFEST_FILE

    # Crear un ZIP malicioso con entry "../evil.txt"
    zip_path = tmp_path / "evil_bundle.zip"
    manifest = '{"show_slug": "test", "sd_version": "2.0", "bundle_version": "1", "plugins": []}'
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(_MANIFEST_FILE, manifest)
        zf.writestr("audio/../evil.txt", "evil content")  # path traversal in audio

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    from server.show_bundle import import_show_bundle
    with pytest.raises(ValueError, match="Zip Slip"):
        import_show_bundle(str(zip_path), projects_dir)


# ─── FIX 2: Marketplace SSRF/RCE ─────────────────────────────────────────────

def test_marketplace_url_not_in_manifest(tmp_path):
    """install_plugin con URL no listada en el manifiesto → ValueError."""
    import server.marketplace as mp

    # Populate cache with a manifest that does NOT include the evil URL
    mp._CACHE = (time.monotonic(), [
        {"name": "legit", "download_url": "https://example.com/legit.py"},
    ])

    with pytest.raises(ValueError, match="URL no autorizada"):
        mp._assert_url_in_manifest("https://evil.com/evil.py")


def test_marketplace_blocks_before_fetch():
    """_assert_url_in_manifest sin manifest previo → ValueError."""
    import server.marketplace as mp
    mp.invalidate_cache()

    with pytest.raises(ValueError, match="Manifiesto no cargado"):
        mp._assert_url_in_manifest("https://example.com/plugin.py")


# ─── FIX 5: Webhook SSRF ─────────────────────────────────────────────────────

def test_webhook_url_http_rejected():
    """webhook_set_config con url http:// debe retornar error (no https)."""
    from server.webhooks import _validate_webhook_url

    with pytest.raises(ValueError, match="https"):
        _validate_webhook_url("http://example.com/hook")


def test_webhook_url_private_ip_rejected():
    """webhook_set_config con URL apuntando a IP privada → error."""
    from server.webhooks import _validate_webhook_url

    with pytest.raises(ValueError, match="IP no permitida"):
        _validate_webhook_url("https://192.168.1.1/hook")


def test_webhook_url_loopback_rejected():
    """URL loopback (127.0.0.1) también rechazada."""
    from server.webhooks import _validate_webhook_url

    with pytest.raises(ValueError, match="IP no permitida"):
        _validate_webhook_url("https://127.0.0.1/hook")


def test_webhook_url_valid_dns_accepted():
    """URL con hostname DNS público → no lanza excepción."""
    from server.webhooks import _validate_webhook_url

    _validate_webhook_url("https://hooks.example.com/notify")  # must not raise


# ─── FIX 4: Timing-safe token comparison ─────────────────────────────────────

def test_timing_safe_token_compare():
    """check_permission usa hmac.compare_digest para la comparación de tokens."""
    import hmac as hmac_mod
    from server.auth import check_permission

    tokens_cfg = [{"token": "secret123", "role": "operator"}]

    compare_calls = []
    original = hmac_mod.compare_digest

    def spy_compare_digest(a, b):
        compare_calls.append((a, b))
        return original(a, b)

    with patch("server.auth.hmac.compare_digest", side_effect=spy_compare_digest):
        result = check_permission("secret123", "some_handler", tokens_cfg)

    assert result["ok"] is True
    # Verify compare_digest was actually called (not plain ==)
    assert any("secret123" in pair for pair in compare_calls)
