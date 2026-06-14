"""
marketplace.py — Marketplace de plugins (N1).

Descarga y valida plugins de la comunidad desde un manifest JSON remoto.
Cache en memoria 5 min. Validación vía plugin_test_harness (H1).
"""
from __future__ import annotations

import importlib
import importlib.util
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# (time, plugins_list) — _CACHE[0] = monotonic timestamp, _CACHE[1] = plugin list
_CACHE: Optional[Tuple[float, List[Dict]]] = None
_CACHE_TTL = 300.0  # 5 minutos
# FIX 6: threading.Lock protects the check+assign atomically across threads
_CACHE_LOCK = threading.Lock()

DEFAULT_MARKETPLACE_URL = (
    "https://raw.githubusercontent.com/example/sd-plugins/main/manifest.json"
)


def _is_cached() -> bool:
    return _CACHE is not None and (time.monotonic() - _CACHE[0]) < _CACHE_TTL


def _assert_url_in_manifest(url: str) -> None:
    """FIX 2: SSRF guard — raises ValueError if url is not in the cached manifest."""
    if _CACHE is None:
        raise ValueError("Manifiesto no cargado; llama list_marketplace_plugins primero")
    allowed = {p.get("download_url") for p in _CACHE[1]}
    if url not in allowed:
        raise ValueError(f"URL no autorizada: {url}")


async def fetch_manifest(url: str) -> Tuple[List[Dict], bool]:
    """Fetch manifest remoto con timeout 10 s. Devuelve (plugins, from_cache).
    Lanza TimeoutError o RuntimeError en caso de error.
    FIX 3: usa httpx.AsyncClient (non-blocking).
    FIX 6: _CACHE_LOCK protege el check+assign del cache."""
    global _CACHE
    # Fast path under lock (avoids re-fetching when cache is hot)
    with _CACHE_LOCK:
        if _is_cached():
            return _CACHE[1], True

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException as exc:
        raise TimeoutError("timeout fetching manifest") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    if not isinstance(data, list):
        raise ValueError("manifest must be a JSON array")

    with _CACHE_LOCK:
        _CACHE = (time.monotonic(), data)
    return data, False


async def install_plugin(download_url: str, plugins_dir: Path) -> Dict:
    """Descarga un .py, lo valida con el harness H1 y lo instala.
    Devuelve {ok, name} o {ok: false, error}.
    FIX 2: valida download_url contra el manifiesto cacheado ANTES de descargar.
    FIX 3: usa httpx.AsyncClient (non-blocking)."""
    # FIX 2: SSRF guard — raises ValueError if URL not in manifest
    _assert_url_in_manifest(download_url)

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.get(download_url)
            resp.raise_for_status()
            code = resp.text
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout downloading plugin"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    filename = download_url.rstrip("/").split("/")[-1]
    if not filename.endswith(".py"):
        return {"ok": False, "error": "plugin must be a .py file"}

    plugins_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = plugins_dir / f"_mp_tmp_{filename}"
    dest_path = plugins_dir / filename

    tmp_path.write_text(code, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location("_mp_validate_mod", tmp_path)
        if spec is None or spec.loader is None:
            return {"ok": False, "error": "cannot import plugin module"}
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_mp_validate_mod"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        from tests.plugin_test_harness import assert_valid_plugin_effect
        from src.core.effects_engine import Effect

        found: List[str] = []
        for attr_name in dir(mod):
            cls = getattr(mod, attr_name)
            if (
                isinstance(cls, type)
                and issubclass(cls, Effect)
                and cls is not Effect
                and not attr_name.startswith("_")
            ):
                assert_valid_plugin_effect(cls())
                found.append(attr_name)

        if not found:
            return {"ok": False, "error": "no Effect subclass found in plugin"}

        shutil.copy(str(tmp_path), str(dest_path))
        return {"ok": True, "name": filename}

    except AssertionError as exc:
        return {"ok": False, "error": f"harness validation failed: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        tmp_path.unlink(missing_ok=True)
        sys.modules.pop("_mp_validate_mod", None)


def invalidate_cache() -> None:
    global _CACHE
    _CACHE = None
