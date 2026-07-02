"""
webhooks.py — Dispatcher de webhooks de eventos (L2).

Configuración en output_targets.json["webhooks"]:
  [{"url": "https://...", "events": ["on_cue_change"], "secret": "opcional"}]

Payload enviado: {"event": "on_cue_change", "t_ms": 12345, "data": {...}}
Header de firma: X-Signature-256: hmac-sha256=<hex> (solo si secret configurado).

Reintentos: 3 intentos con backoff 1s, 3s, 9s.
Sin crash ante fallos (I4/I6).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import urllib.parse
from typing import Any

log = logging.getLogger(__name__)


def _validate_webhook_url(url: str) -> None:
    """FIX 5: SSRF guard — rejects non-https URLs and private/loopback IPs."""
    p = urllib.parse.urlparse(url)
    if p.scheme != "https":
        raise ValueError("Webhook URL debe usar https")
    try:
        ip = ipaddress.ip_address(p.hostname or "")
    except ValueError:
        return  # hostname DNS, not an IP literal — OK
    if ip.is_private or ip.is_link_local or ip.is_loopback:
        raise ValueError(f"IP no permitida: {ip}")


class WebhookDispatcher:
    def __init__(self, configs: list[dict]):
        """
        Args:
            configs: lista de {url, events: [str], secret?: str}
        """
        self._configs = configs or []

    @classmethod
    def from_output_targets(cls, path) -> WebhookDispatcher:
        """Carga la config desde output_targets.json."""
        from pathlib import Path
        p = Path(path)
        configs: list[dict] = []
        if p.is_file():
            try:
                data = json.loads(p.read_text("utf-8"))
                configs = data.get("webhooks", [])
            except Exception:
                pass
        return cls(configs)

    def _sign(self, body_bytes: bytes, secret: str) -> str:
        """HMAC-SHA256 del body con el secret."""
        return "hmac-sha256=" + hmac.new(
            secret.encode("utf-8"), body_bytes, hashlib.sha256
        ).hexdigest()

    async def _post_with_retry(self, url: str, payload: dict, secret: str):
        """POST con 3 reintentos y backoff 1s/3s/9s."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-Signature-256"] = self._sign(body, secret)

        delays = [1, 3, 9]
        last_err = None
        for attempt, delay in enumerate(delays, start=1):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(url, content=body, headers=headers)
                    # FIX 7: 4xx means misconfigured URL/secret — log and don't retry
                    if 400 <= resp.status_code < 500:
                        log.warning(
                            "Webhook %s retornó %s — verificar URL/secret",
                            url, resp.status_code,
                        )
                        return
                    if resp.status_code < 500:
                        return  # 2xx/3xx OK
                    last_err = f"HTTP {resp.status_code}"
            except Exception as e:
                last_err = str(e)
            if attempt < len(delays):
                await asyncio.sleep(delay)

        log.warning("Webhook %s falló tras %d intentos: %s", url, len(delays), last_err)

    async def emit(self, event: str, data: dict[str, Any], t_ms: int = 0):
        """Dispara el evento a todas las URLs suscritas (fire-and-forget)."""
        payload = {"event": event, "t_ms": t_ms, "data": data}
        for cfg in self._configs:
            if event not in (cfg.get("events") or []):
                continue
            url = cfg.get("url", "")
            secret = cfg.get("secret", "") or ""
            if not url:
                continue
            asyncio.ensure_future(self._post_with_retry(url, payload, secret))

    def get_configs(self) -> list[dict]:
        return [dict(c) for c in self._configs]

    def set_configs(self, configs: list[dict]):
        self._configs = configs or []
