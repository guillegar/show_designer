"""
rest_api.py — API REST pública en /api/v1/ (L1).

Wrappers sobre los handlers del Dispatcher. Sin duplicar lógica de negocio.

Autenticación: header X-API-Key.
  - Si output_targets.json["api_key"] está configurada → requerida.
  - Si no configurada → sin autenticación (dev local).

Respuestas: {"ok": true, "data": {...}} | {"ok": false, "error": "..."}
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse


def _ok(data: Any) -> Dict:
    return {"ok": True, "data": data}


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


def _check_auth(request: Request, x_api_key: Optional[str]) -> Optional[JSONResponse]:
    """Valida X-API-Key contra la configuración. None = OK."""
    api_key: str = getattr(request.app.state, "_rest_api_key", "") or ""
    if not api_key:
        return None  # Sin auth configurada → libre
    if not x_api_key or x_api_key != api_key:
        return JSONResponse({"ok": False, "error": "X-API-Key inválida o ausente"}, status_code=401)
    return None


def create_rest_router() -> APIRouter:
    """Devuelve el router /api/v1 para montar en la app FastAPI."""
    router = APIRouter(prefix="/api/v1")

    # ── GET /api/v1/status ────────────────────────────────────────────────────
    @router.get("/status")
    async def get_status(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        err = _check_auth(request, x_api_key)
        if err:
            return err
        disp = request.app.state.dispatcher
        if disp is None:
            return _err("Backend no listo", 503)
        result = disp.handle({"method": "get_transport_state", "params": {}, "id": 0})
        return _ok(result.get("state", result))

    # ── GET /api/v1/clips ─────────────────────────────────────────────────────
    @router.get("/clips")
    async def list_clips(
        request: Request,
        offset: int = 0,
        limit: int = 100,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        err = _check_auth(request, x_api_key)
        if err:
            return err
        disp = request.app.state.dispatcher
        if disp is None:
            return _err("Backend no listo", 503)
        result = disp.handle({"method": "list_clips",
                               "params": {"offset": offset, "limit": limit}, "id": 0})
        return _ok(result)

    # ── POST /api/v1/clips ────────────────────────────────────────────────────
    @router.post("/clips", status_code=201)
    async def add_clip(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        err = _check_auth(request, x_api_key)
        if err:
            return err
        disp = request.app.state.dispatcher
        if disp is None:
            return _err("Backend no listo", 503)
        try:
            body = await request.json()
        except Exception:
            return _err("Body JSON inválido")
        result = disp.handle({"method": "add_clip", "params": body, "id": 0})
        if not result.get("ok"):
            return _err(result.get("error", "Error al crear clip"), 400)
        return JSONResponse(_ok(result), status_code=201)

    # ── GET /api/v1/cues ──────────────────────────────────────────────────────
    @router.get("/cues")
    async def get_cues(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        err = _check_auth(request, x_api_key)
        if err:
            return err
        disp = request.app.state.dispatcher
        if disp is None:
            return _err("Backend no listo", 503)
        result = disp.handle({"method": "get_cue_state", "params": {}, "id": 0})
        return _ok(result)

    # ── POST /api/v1/cues/go ─────────────────────────────────────────────────
    @router.post("/cues/go")
    async def go_next_cue(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        err = _check_auth(request, x_api_key)
        if err:
            return err
        disp = request.app.state.dispatcher
        if disp is None:
            return _err("Backend no listo", 503)
        result = disp.handle({"method": "go_next_cue", "params": {}, "id": 0})
        return _ok(result)

    # ── POST /api/v1/macros/{name} ────────────────────────────────────────────
    @router.post("/macros/{name}")
    async def set_macro(
        name: str,
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        err = _check_auth(request, x_api_key)
        if err:
            return err
        disp = request.app.state.dispatcher
        if disp is None:
            return _err("Backend no listo", 503)
        try:
            body = await request.json()
        except Exception:
            body = {}
        value = body.get("value")
        result = disp.handle({"method": "set_macro",
                               "params": {"name": name, "value": value}, "id": 0})
        if not result.get("ok"):
            return _err(result.get("error", "Error al aplicar macro"), 400)
        return _ok(result)

    # ── GET /api/v1/fixtures ──────────────────────────────────────────────────
    @router.get("/fixtures")
    async def list_fixtures(
        request: Request,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ):
        err = _check_auth(request, x_api_key)
        if err:
            return err
        disp = request.app.state.dispatcher
        if disp is None:
            return _err("Backend no listo", 503)
        result = disp.handle({"method": "list_fixtures", "params": {}, "id": 0})
        return _ok(result)

    return router
