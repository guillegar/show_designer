"""
handlers/bundle_market.py — N1 marketplace de plugins + N2 backup/restore de show (ADR-005).
"""
from __future__ import annotations

from server.validators import require_key

# ── N1 — Marketplace de plugins ───────────────────────────────────────────────

_DEFAULT_MARKETPLACE_URL = (
    "https://raw.githubusercontent.com/example/sd-plugins/main/manifest.json"
)


def _get_marketplace_url(session) -> str:
    try:
        import json
        from pathlib import Path as _Path
        data = json.loads(_Path("output_targets.json").read_text("utf-8"))
        return data.get("marketplace_url", _DEFAULT_MARKETPLACE_URL)
    except Exception:
        return _DEFAULT_MARKETPLACE_URL


async def _h_list_marketplace_plugins(session, params):
    """list_marketplace_plugins() → {ok, plugins: [...], cached: bool}.
    FIX 3: async to avoid blocking the event loop during HTTP fetch."""
    from server.marketplace import fetch_manifest
    url = _get_marketplace_url(session)
    try:
        plugins, cached = await fetch_manifest(url)
        return {"ok": True, "plugins": plugins, "cached": cached}
    except TimeoutError:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _h_install_plugin(session, params):
    """install_plugin(download_url) → {ok, name} or {ok: false, error}.
    FIX 3: async to avoid blocking; FIX 2: URL validated against manifest."""
    from pathlib import Path as _Path

    from server.marketplace import install_plugin
    download_url = require_key(params, "download_url")
    plugins_dir = _Path("plugins/effects")
    return await install_plugin(download_url, plugins_dir)


# ── N2 — Backup y restauración de show ───────────────────────────────────────

def _h_export_show_bundle(session, params):
    """export_show_bundle(include_audio?) → {ok, path}."""
    include_audio = bool(params.get("include_audio", False))
    from server.show_bundle import export_show_bundle
    try:
        path = export_show_bundle(session, include_audio=include_audio)
        return {"ok": True, "path": path}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _h_import_show_bundle(session, params):
    """import_show_bundle(zip_path) → {ok, slug, warnings} or {ok: false, error}."""
    from pathlib import Path as _Path

    from server.show_bundle import import_show_bundle
    zip_path = require_key(params, "zip_path")
    try:
        slug, warnings = import_show_bundle(zip_path, _Path("projects"))
        return {"ok": True, "slug": slug, "warnings": warnings}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


HANDLERS = {
    "list_marketplace_plugins": _h_list_marketplace_plugins,
    "install_plugin": _h_install_plugin,
    "export_show_bundle": _h_export_show_bundle,
    "import_show_bundle": _h_import_show_bundle,
}
