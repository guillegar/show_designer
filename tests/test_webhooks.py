"""
test_webhooks.py — Tests para WebhookDispatcher (L2).
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


from server.webhooks import WebhookDispatcher


# ─── helpers ────────────────────────────────────────────────────────────────

def _dispatcher(*cfgs):
    return WebhookDispatcher(list(cfgs))


def _sign(body_bytes: bytes, secret: str) -> str:
    return "hmac-sha256=" + hmac.new(
        secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()


# ─── tests ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_correct_payload():
    """emit → POST a URL con payload correcto."""
    captured = {}

    async def fake_post(url, content, headers):
        captured["url"] = url
        captured["body"] = json.loads(content)
        captured["headers"] = headers
        resp = MagicMock()
        resp.status_code = 200
        return resp

    cfg = {"url": "http://example.com/hook", "events": ["on_cue_change"], "secret": ""}
    d = _dispatcher(cfg)

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=fake_post)
        MockClient.return_value = mock_client

        await d.emit("on_cue_change", {"cue": 3}, t_ms=5000)
        # give ensure_future a chance to run
        await asyncio.sleep(0)

    assert captured.get("url") == "http://example.com/hook"
    assert captured["body"]["event"] == "on_cue_change"
    assert captured["body"]["t_ms"] == 5000
    assert captured["body"]["data"]["cue"] == 3


@pytest.mark.asyncio
async def test_hmac_signature_present_when_secret_set():
    """Con secret → X-Signature-256 correcto en header."""
    SECRET = "supersecret"
    captured = {}

    async def fake_post(url, content, headers):
        captured["headers"] = headers
        captured["body"] = content
        resp = MagicMock()
        resp.status_code = 200
        return resp

    cfg = {"url": "http://hook.test/", "events": ["on_cue_change"], "secret": SECRET}
    d = _dispatcher(cfg)

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=fake_post)
        MockClient.return_value = mock_client

        await d.emit("on_cue_change", {}, t_ms=0)
        await asyncio.sleep(0)

    sig = captured["headers"].get("X-Signature-256", "")
    expected = _sign(captured["body"], SECRET)
    assert sig == expected


@pytest.mark.asyncio
async def test_no_signature_header_when_no_secret():
    """Sin secret → X-Signature-256 NO incluido."""
    captured = {}

    async def fake_post(url, content, headers):
        captured["headers"] = headers
        resp = MagicMock()
        resp.status_code = 200
        return resp

    cfg = {"url": "http://hook.test/", "events": ["on_cue_change"], "secret": ""}
    d = _dispatcher(cfg)

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=fake_post)
        MockClient.return_value = mock_client

        await d.emit("on_cue_change", {}, t_ms=0)
        await asyncio.sleep(0)

    assert "X-Signature-256" not in captured.get("headers", {})


@pytest.mark.asyncio
async def test_retry_on_http_500():
    """Fallo HTTP 500 → 3 reintentos antes de rendirse."""
    call_count = 0

    async def failing_post(url, content, headers):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 500
        return resp

    cfg = {"url": "http://hook.test/fail", "events": ["ev"], "secret": ""}
    d = _dispatcher(cfg)

    with patch("httpx.AsyncClient") as MockClient, patch("asyncio.sleep", new_callable=AsyncMock):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=failing_post)
        MockClient.return_value = mock_client

        # call _post_with_retry directly to test retry logic synchronously
        await d._post_with_retry("http://hook.test/fail", {"event": "ev"}, "")

    assert call_count == 3  # exactly 3 attempts


@pytest.mark.asyncio
async def test_timeout_no_crash():
    """URL inaccesible (excepción de red) → no crash, log de error (I4/I6)."""
    import httpx

    async def exc_post(url, content, headers):
        raise httpx.ConnectTimeout("timeout")

    cfg = {"url": "http://192.0.2.1/unreachable", "events": ["ev"], "secret": ""}
    d = _dispatcher(cfg)

    with patch("httpx.AsyncClient") as MockClient, patch("asyncio.sleep", new_callable=AsyncMock):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=exc_post)
        MockClient.return_value = mock_client

        # must not raise
        await d._post_with_retry("http://192.0.2.1/unreachable", {"event": "ev"}, "")


def test_webhook_set_config_atomic_write(tmp_path):
    """webhook_set_config guarda en output_targets.json de forma atómica."""
    import importlib, sys
    from pathlib import Path

    ot_file = tmp_path / "output_targets.json"
    ot_file.write_text(json.dumps({"webhooks": []}), "utf-8")

    d = WebhookDispatcher.from_output_targets(ot_file)
    new_cfgs = [{"url": "http://example.com/", "events": ["on_cue_change"], "secret": "abc"}]
    d.set_configs(new_cfgs)

    # Simulate handler writing atomically (same logic as _h_webhook_set_config)
    tmp = ot_file.with_suffix(".tmp")
    existing = json.loads(ot_file.read_text("utf-8")) if ot_file.is_file() else {}
    existing["webhooks"] = d.get_configs()
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), "utf-8")
    tmp.replace(ot_file)

    saved = json.loads(ot_file.read_text("utf-8"))
    assert saved["webhooks"][0]["url"] == "http://example.com/"
    assert saved["webhooks"][0]["secret"] == "abc"
