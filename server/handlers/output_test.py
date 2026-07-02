"""
handlers/output_test.py — E4 test de output (identify/test/blackout/status) + J4 chase (ADR-005).
"""
from __future__ import annotations

# ── E4 — Test de output y patch visual ───────────────────────────────────────

def _h_identify_fixture(session, params):
    """identify_fixture(fixture_id, color=(255,255,255), duration_ms=2000) → {ok}.

    Enciende el fixture al color dado durante duration_ms ms.
    Estado efímero en session._identify (fixture_id → {t_expires, color}).
    Backwards-compatible: sin color → blanco; sin duration_ms → 2000 ms.
    """
    import asyncio
    import time

    fixture_id = params.get("fixture_id")
    if not fixture_id:
        return {"ok": False, "error": "fixture_id requerido"}

    # Validar que el fixture existe
    rig = getattr(session, 'fixture_rig', None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}

    fx = None
    for f in getattr(rig, 'fixtures', []):
        if getattr(f, 'fixture_id', None) == fixture_id:
            fx = f
            break
    if fx is None:
        return {"ok": False, "error": f"Fixture '{fixture_id}' no encontrado"}

    duration_ms = int(params.get("duration_ms", 2000))
    if duration_ms < 100 or duration_ms > 30000:
        return {"ok": False, "error": "duration_ms debe ser 100..30000"}

    # J4: color configurable (r,g,b) 0..255 — por defecto blanco
    raw_color = params.get("color", [255, 255, 255])
    if isinstance(raw_color, (list, tuple)) and len(raw_color) >= 3:
        color = tuple(max(0, min(255, int(v))) for v in raw_color[:3])
    else:
        color = (255, 255, 255)

    t_expires = time.monotonic() + duration_ms / 1000.0
    if not hasattr(session, '_identify'):
        session._identify = {}
    session._identify[fixture_id] = {"t_expires": t_expires, "color": color}

    async def _auto_off():
        await asyncio.sleep(duration_ms / 1000.0)
        if hasattr(session, '_identify'):
            session._identify.pop(fixture_id, None)

    try:
        asyncio.ensure_future(_auto_off())
    except RuntimeError:
        pass  # sin event loop (tests)

    return {"ok": True, "fixture_id": fixture_id, "duration_ms": duration_ms,
            "color": list(color)}


# J4 — Chase automático de fixtures ──────────────────────────────────────────

_CHASE_SEQUENCE = [
    (255, 0, 0),    # rojo
    (0, 255, 0),    # verde
    (0, 0, 255),    # azul
    (255, 255, 255),# blanco
]
_CHASE_STEP_MS = 500


def _h_chase_test(session, params):
    """chase_test(universe) → {ok, chase_id}.

    Cicla rojo→verde→azul→blanco por los fixtures del universo, 500 ms cada color.
    Estado efímero en session._active_chases: {universe: asyncio.Task}.
    """
    import asyncio

    universe = int(params.get("universe", 0))
    if universe < 1:
        return {"ok": False, "error": "universe debe ser >= 1"}

    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}

    fixtures_in_uni = [fx for fx in rig.fixtures if fx.universe == universe]
    if not fixtures_in_uni:
        return {"ok": False, "error": f"No hay fixtures en el universo {universe}"}

    if not hasattr(session, "_active_chases"):
        session._active_chases = {}

    # Cancelar chase anterior en este universo
    prev = session._active_chases.pop(universe, None)
    if prev is not None:
        try:
            prev.cancel()
        except Exception:
            pass

    if not hasattr(session, "_identify"):
        session._identify = {}

    chase_id = f"chase_u{universe}"

    async def _run_chase():
        step = 0
        while True:
            color = _CHASE_SEQUENCE[step % len(_CHASE_SEQUENCE)]
            for fx in fixtures_in_uni:
                import time as _time
                session._identify[fx.fixture_id] = {
                    "t_expires": _time.monotonic() + _CHASE_STEP_MS / 1000.0 + 0.05,
                    "color": color,
                }
            await asyncio.sleep(_CHASE_STEP_MS / 1000.0)
            step += 1

    try:
        task = asyncio.ensure_future(_run_chase())
        session._active_chases[universe] = task
    except RuntimeError:
        pass  # sin event loop (tests)

    return {"ok": True, "chase_id": chase_id, "universe": universe}


def _h_chase_stop(session, params):
    """chase_stop(universe) → {ok}.

    Cancela el chase activo del universo y apaga sus fixtures.
    """
    universe = int(params.get("universe", 0))
    if universe < 1:
        return {"ok": False, "error": "universe debe ser >= 1"}

    chases = getattr(session, "_active_chases", {})
    task = chases.pop(universe, None)
    if task is not None:
        try:
            task.cancel()
        except Exception:
            pass

    # Apagar identify de todos los fixtures del universo
    rig = getattr(session, "fixture_rig", None)
    if rig is not None and hasattr(session, "_identify"):
        for fx in rig.fixtures:
            if fx.universe == universe:
                session._identify.pop(fx.fixture_id, None)

    return {"ok": True, "universe": universe}


def _h_test_universe(session, params):
    """test_universe(universe, r, g, b) → {ok}.

    Llena ese universo Art-Net con el color dado.
    Toggle: segunda llamada con el mismo universo lo apaga.
    universe: 1..10, r/g/b: 0..255.
    """
    try:
        universe = int(params.get("universe", 0))
        r = int(params.get("r", 255))
        g = int(params.get("g", 255))
        b = int(params.get("b", 255))
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": f"Parámetro inválido: {e}"}

    if universe < 1 or universe > 10:
        return {"ok": False, "error": "universe debe ser 1..10"}
    for name, v in [("r", r), ("g", g), ("b", b)]:
        if v < 0 or v > 255:
            return {"ok": False, "error": f"{name} debe ser 0..255"}

    if not hasattr(session, '_test_universes'):
        session._test_universes = {}

    # Toggle: si ya está activo con esos mismos datos, apagar
    current = session._test_universes.get(universe)
    if current is not None and current == (r, g, b):
        del session._test_universes[universe]
        return {"ok": True, "universe": universe, "active": False}

    session._test_universes[universe] = (r, g, b)
    return {"ok": True, "universe": universe, "active": True, "r": r, "g": g, "b": b}


def _h_blackout(session, params):
    """blackout(enabled: bool) → {ok, blackout: bool}.

    Override instantáneo de master brightness a 0 cuando enabled=True.
    No muta timeline.mixer (para no perder el valor del usuario).
    Estado en session.blackout_override (no se persiste en show.json).
    Distinto de blackout_fade (B2): este es de pánico, instantáneo.
    """
    enabled = bool(params.get("enabled", False))
    session.blackout_override = enabled

    # Emitir evento al stream
    import asyncio
    hub = getattr(session, "hub", None)
    if hub:
        try:
            asyncio.ensure_future(
                hub.broadcast_json({"type": "blackout_changed", "enabled": enabled})
            )
        except Exception:
            pass

    return {"ok": True, "blackout": enabled}


def _h_get_output_status(session, params):
    """get_output_status() → {ok, blackout, has_ffmpeg, render_ready, active_test_universe}.

    Estado unificado de las herramientas de output de E3/E4.
    """
    import shutil

    blackout = getattr(session, 'blackout_override', False)
    has_ffmpeg = shutil.which("ffmpeg") is not None
    render_ready = (session.project.folder / "render.npz").is_file()
    test_uni = getattr(session, '_test_universes', {})
    active_test_universe = list(test_uni.keys())[0] if test_uni else None

    return {
        "ok": True,
        "blackout": blackout,
        "has_ffmpeg": has_ffmpeg,
        "render_ready": render_ready,
        "active_test_universe": active_test_universe,
    }


HANDLERS = {
    "identify_fixture": _h_identify_fixture,
    "test_universe": _h_test_universe,
    "blackout": _h_blackout,
    "get_output_status": _h_get_output_status,
    "chase_test": _h_chase_test,
    "chase_stop": _h_chase_stop,
}
