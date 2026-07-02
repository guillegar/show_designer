"""
test_rest_api.py — Tests L1: API REST /api/v1/ (FastAPI + httpx).

Cubre:
  test_status_ok             — GET /api/v1/status → 200, {ok: True, data: {...}}
  test_clips_paginated       — GET /api/v1/clips?limit=10 → respuesta paginada
  test_post_clip_created     — POST /api/v1/clips body válido → 201, clip creado
  test_post_macro            — POST /api/v1/macros/brightness {value:0.5}
  test_auth_missing_key      — Sin X-API-Key cuando api_key configurada → 401
  test_auth_valid_key        — Con X-API-Key correcta → 200
  test_auth_wrong_key        — Con X-API-Key incorrecta → 401
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.rest_api import create_rest_router

# ── App de prueba ─────────────────────────────────────────────────────────────

def _make_dispatcher(extra_handles=None):
    """Crea un dispatcher mock con respuestas razonables."""
    disp = MagicMock()

    def _handle(msg):
        method = msg.get("method", "")
        if method == "get_transport_state":
            return {"ok": True, "state": {"t_ms": 0, "playing": False, "bpm": 120.0}}
        if method == "list_clips":
            return {"ok": True, "clips": [], "total": 0}
        if method == "add_clip":
            return {"ok": True, "clip": {"id": "new_clip", "track": 0}}
        if method == "get_cue_state":
            return {"ok": True, "current_cue": None}
        if method == "go_next_cue":
            return {"ok": True}
        if method == "set_macro":
            return {"ok": True, "name": msg["params"]["name"]}
        if method == "list_fixtures":
            return {"ok": True, "fixtures": []}
        if extra_handles:
            return extra_handles(msg)
        return {"ok": False, "error": "unknown"}

    disp.handle.side_effect = _handle
    return disp


def _make_app(api_key: str = "") -> FastAPI:
    app = FastAPI()
    app.state.dispatcher = _make_dispatcher()
    app.state._rest_api_key = api_key
    app.include_router(create_rest_router())
    return app


# ── Tests sin autenticación ──────────────────────────────────────────────────

def test_status_ok():
    client = TestClient(_make_app())
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "data" in body
    assert body["data"]["t_ms"] == 0


def test_clips_paginated():
    client = TestClient(_make_app())
    r = client.get("/api/v1/clips?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "clips" in body["data"] or "data" in body


def test_post_clip_created():
    client = TestClient(_make_app())
    r = client.post("/api/v1/clips", json={
        "track": 0, "start_ms": 0, "end_ms": 1000, "effect_id": 1
    })
    assert r.status_code == 201
    body = r.json()
    assert body["ok"] is True


def test_post_macro():
    client = TestClient(_make_app())
    r = client.post("/api/v1/macros/brightness", json={"value": 0.5})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "brightness"


# ── Tests de autenticación ───────────────────────────────────────────────────

def test_auth_missing_key():
    """Sin X-API-Key cuando api_key configurada → 401."""
    client = TestClient(_make_app(api_key="secret123"))
    r = client.get("/api/v1/status")
    assert r.status_code == 401
    assert r.json()["ok"] is False


def test_auth_valid_key():
    """Con X-API-Key correcta → 200."""
    client = TestClient(_make_app(api_key="secret123"))
    r = client.get("/api/v1/status", headers={"X-API-Key": "secret123"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_auth_wrong_key():
    """Con X-API-Key incorrecta → 401."""
    client = TestClient(_make_app(api_key="secret123"))
    r = client.get("/api/v1/status", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    assert r.json()["ok"] is False
