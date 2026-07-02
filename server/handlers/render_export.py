"""
handlers/render_export.py — B3 render offline + E3 export de vídeo + I5 export PDF/CSV (ADR-005).
"""
from __future__ import annotations

import asyncio

from src.log import get_logger

_log = get_logger(__name__)

# ── B3 — Render offline + playback baked ────────────────────────────────────

def _h_render_offline(session, params):
    """render_offline() — lanza el render del timeline completo en background.

    Corre en loop.run_in_executor (thread pool) — no bloquea el tick (I4).
    El progreso se emite como {type:'render_progress', pct:float} en el stream.
    Devuelve {ok, message} inmediatamente (el render continúa en background).
    """
    if getattr(session, 'render_in_progress', False):
        return {"ok": False, "error": "Ya hay un render en curso"}

    from server.offline_render import start_render
    try:
        asyncio.ensure_future(start_render(session))
    except RuntimeError as e:
        return {"ok": False, "error": f"No se pudo lanzar render: {e}"}
    return {"ok": True, "message": "Render iniciado en background"}


def _h_toggle_baked(session, params):
    """toggle_baked(enabled: bool) → {ok, baked: bool}.

    Si enabled=True: intenta cargar los frames bakeados del npz en memoria.
    Si no hay render válido (hash no coincide o no existe), devuelve error.
    Si enabled=False: descarga los frames de memoria (vuelve al modo live).
    """
    enabled = bool(params.get("enabled", True))

    if not enabled:
        session.baked_frames = None
        session.baked_hash = None
        return {"ok": True, "baked": False}

    ok = session.load_baked_frames()
    if not ok:
        return {
            "ok": False,
            "error": "Sin render válido. Lanza render_offline primero.",
            "baked": False,
        }
    return {"ok": True, "baked": True}


# ── E3 — Export de video preview ─────────────────────────────────────────────

def _h_export_video(session, params):
    """export_video(format='gif', scale=4) → {ok} + eventos export_progress.

    Lanza el export en executor (I4). Solo un export a la vez (flag
    export_in_progress en session). Emite {type:'export_progress', pct:float}
    al stream.
    Si no hay render.npz → {ok: False, error}.
    """
    import shutil

    if getattr(session, 'export_in_progress', False):
        return {"ok": False, "error": "Ya hay un export en curso"}

    fmt = params.get("format", "gif")
    if fmt not in ("gif", "mp4"):
        return {"ok": False, "error": "format debe ser 'gif' o 'mp4'"}

    if fmt == "mp4" and shutil.which("ffmpeg") is None:
        return {"ok": False, "error": "ffmpeg no encontrado en PATH"}

    npz_path = session.project.folder / "render.npz"
    if not npz_path.is_file():
        return {"ok": False, "error": "Sin render. Ejecuta render_offline primero."}

    scale = int(params.get("scale", 4))
    if scale < 1 or scale > 16:
        return {"ok": False, "error": "scale debe ser 1..16"}

    out_path = session.project.folder / f"preview.{fmt}"
    session.export_in_progress = True

    async def _run():
        loop = asyncio.get_event_loop()

        def _progress_fn(pct: float):
            hub = getattr(session, "hub", None)
            if hub:
                try:
                    asyncio.run_coroutine_threadsafe(
                        hub.broadcast_json({"type": "export_progress", "pct": pct}),
                        loop,
                    )
                except Exception:
                    pass

        def _worker():
            from server.video_export import export_preview
            export_preview(str(npz_path), str(out_path), format=fmt,
                           scale=scale, progress_cb=_progress_fn)

        try:
            await loop.run_in_executor(None, _worker)
        except Exception as e:
            _log.error(f"[export_video] error: {e}")
        finally:
            session.export_in_progress = False
            hub = getattr(session, "hub", None)
            if hub:
                try:
                    await hub.broadcast_json({"type": "export_progress", "pct": 100.0, "done": True})
                except Exception:
                    pass

    try:
        asyncio.ensure_future(_run())
    except RuntimeError as e:
        session.export_in_progress = False
        return {"ok": False, "error": f"No se pudo lanzar export: {e}"}
    return {"ok": True, "message": f"Export {fmt} iniciado"}


def _h_get_render_status(session, params):
    """get_render_status() → {ok, status, pct, hash, has_ffmpeg, render_ready}.

    Amplía la versión de B3 con has_ffmpeg (E3) para que el frontend
    sepa si mostrar el botón de MP4.
    """
    import json as _json
    import shutil

    from server.offline_render import compute_timeline_hash

    has_ffmpeg = shutil.which("ffmpeg") is not None

    if getattr(session, 'render_in_progress', False):
        return {
            "ok": True,
            "status": "rendering",
            "pct": getattr(session, 'render_pct', 0.0),
            "hash": None,
            "has_ffmpeg": has_ffmpeg,
            "render_ready": False,
        }

    out_path = session.project.folder / "render.npz"
    meta_path = session.project.folder / "render_meta.json"
    if not out_path.is_file() or not meta_path.is_file():
        return {"ok": True, "status": "idle", "pct": 0.0, "hash": None,
                "has_ffmpeg": has_ffmpeg, "render_ready": False}

    try:
        with open(meta_path, encoding='utf-8') as f:
            meta = _json.load(f)
        current_hash = compute_timeline_hash(session.timeline.to_dict())
        stored_hash = meta.get("show_hash")
        if stored_hash == current_hash:
            return {
                "ok": True,
                "status": "ready",
                "pct": 100.0,
                "hash": stored_hash,
                "n_frames": meta.get("n_frames"),
                "duration_s": meta.get("duration_s"),
                "has_ffmpeg": has_ffmpeg,
                "render_ready": True,
            }
    except Exception:
        pass

    return {"ok": True, "status": "idle", "pct": 0.0, "hash": None,
            "has_ffmpeg": has_ffmpeg, "render_ready": False}


# ── I5 — Exportación PDF patch + CSV DMX ─────────────────────────────────────

def _h_export_patch_pdf(session, params):
    """export_patch_pdf() → {ok, path}.

    Genera PDF (o TXT fallback) con clips del timeline ordenados por pista y
    tiempo. Usa fpdf2 si disponible; si no, crea un .txt equivalente.
    """
    from server.timeline_export import export_patch_pdf
    out_path = str(session.project.folder / "patch.pdf")
    try:
        path = export_patch_pdf(session, out_path)
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _h_export_dmx_csv(session, params):
    """export_dmx_csv(fps=1) → {ok, path}.

    Genera CSV con frames DMX muestreados a fps FPS.
    Cabecera: t_ms,universe,ch_1,...,ch_512.
    Reutiliza render.npz si existe y es coherente; si no, compute_frame.
    """
    from server.timeline_export import export_dmx_csv
    fps = int(params.get("fps", 1))
    if fps < 1:
        return {"ok": False, "error": "fps debe ser >= 1"}
    out_path = str(session.project.folder / "dmx_export.csv")
    try:
        path = export_dmx_csv(session, out_path, fps=fps)
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}


HANDLERS = {
    "render_offline": _h_render_offline,
    "toggle_baked": _h_toggle_baked,
    "export_video": _h_export_video,
    "get_render_status": _h_get_render_status,
    "export_patch_pdf": _h_export_patch_pdf,
    "export_dmx_csv": _h_export_dmx_csv,
}
