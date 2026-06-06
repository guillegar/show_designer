"""
mcp_bridge.py — Servidor WebSocket JSON-RPC dentro de dual_app.

Expone el estado del editor (timeline, clips, cues, audio) a clientes externos
(típicamente mcp_show_server.py que traduce a/desde protocolo MCP).

Arquitectura:
   - Corre en un thread daemon con su propio event loop asyncio
   - Mantiene referencias débiles a timeline_editor/audio/show_engine de la app
   - Cada request JSON-RPC se enrutea a un handler Python
   - Para operaciones que tocan Qt: usamos QTimer.singleShot(0, fn) para
     asegurar que se ejecutan en el thread de Qt

Protocolo (JSON-RPC 2.0):
    request:  {"jsonrpc":"2.0", "id":1, "method":"play", "params":{}}
    response: {"jsonrpc":"2.0", "id":1, "result":{...}}
    error:    {"jsonrpc":"2.0", "id":1, "error":{"code":-32601, "message":"..."}}

Lanzar standalone (para testing sin Qt):
    python mcp_bridge.py --mock
"""
from __future__ import annotations
import asyncio
import json
import logging
import threading
import traceback
from dataclasses import asdict
from typing import Any, Callable, Dict, Optional

# v1.9 F2 — silenciar logs ERROR de la librería websockets cuando llegan
# conexiones TCP mal formadas (Test-NetConnection, healthchecks, etc.).
# El handshake fallido es esperable y nuestro exception_handler ya lo gestiona,
# así que no queremos manchar stderr con tracebacks ruidosos.
logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
logging.getLogger("websockets.asyncio.server").setLevel(logging.CRITICAL)

try:
    import websockets
except ImportError:
    raise SystemExit("Falta dependencia: pip install websockets")

HOST = "127.0.0.1"
PORT = 9876


# ───────────────────────────────────────────────────────────────
# Handlers — implementan cada método JSON-RPC.
# Reciben (app, params) y devuelven un dict serializable.
# `app` = TimelineEditorWindow (acceso a .audio, .timeline, .show_engine, .tl_view)
# ───────────────────────────────────────────────────────────────

def _h_ping(app, params):
    return {"pong": True, "version": "1.0"}


def _h_get_state(app, params):
    tl = app.timeline
    audio = app.audio
    section = 0
    try:
        if app.show_engine and app.show_engine.state:
            section = app.show_engine.state.section_at(audio.get_time())
    except Exception:
        pass
    return {
        "time_sec": float(audio.get_time()),
        "duration_sec": float(audio.duration_s),
        "playing": bool(audio.playing),
        "current_section": int(section),
        "audio_path": getattr(audio, "_path", None),
        "clip_count": len(tl.clips),
        "group_count": len(tl.groups) if tl.groups else 0,
        "cue_count": sum(1 for c in tl.cue_points if c.is_set()),
        "snap_grid": app.tl_view._snap_grid,
        "snap_on": app.tl_view._snap_on,
    }


def _h_play(app, params):
    start = params.get("start_sec")
    if start is not None:
        app.audio.play(float(start))
    else:
        app.audio.play(app.audio.get_time())
    return {"ok": True, "time_sec": float(app.audio.get_time())}


def _h_pause(app, params):
    app.audio.pause()
    return {"ok": True}


def _h_stop(app, params):
    app.audio.stop()
    return {"ok": True}


def _h_seek(app, params):
    t = float(params["t_sec"])
    app.audio.seek(t)
    return {"ok": True, "time_sec": float(app.audio.get_time())}


def _h_set_blackout(app, params):
    try:
        app._send_blackout()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def _h_open_3d_viewer(app, params):
    """Abre el viewer 3D en el navegador del servidor (donde corre dual_app)."""
    import webbrowser
    url = params.get("url", "http://localhost:8080/")
    try:
        webbrowser.open(url)
        return {"ok": True, "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Fixtures (Fase 3) ─────────────────────────────────────────

def _h_list_fixtures(app, params):
    """Lista los fixtures del rig configurado."""
    rig = getattr(app, 'fixture_rig', None)
    if rig is None:
        return {"fixtures": [], "rig_loaded": False}
    return {
        "fixtures": [f.to_dict() for f in rig.fixtures],
        "universes": rig.universes(),
        "count": len(rig.fixtures),
        "rig_loaded": True,
    }


def _h_list_fixture_profiles(app, params):
    """Lista los profiles disponibles en profiles/."""
    try:
        from src.core.fixtures import list_available_profiles, load_profile
        names = list_available_profiles()
        details = []
        for name in names:
            p = load_profile(name)
            if p:
                details.append({
                    "profile_id": p.profile_id,
                    "name": p.name,
                    "kind": p.kind,
                    "num_channels": p.num_channels,
                    "led_count": p.led_count,
                })
        return {"profiles": details, "count": len(details)}
    except Exception as e:
        return {"profiles": [], "error": str(e)}


def _h_save_rig(app, params):
    """Persiste el rig actual a fixtures.json."""
    rig = getattr(app, 'fixture_rig', None)
    if rig is None:
        return {"ok": False, "error": "no hay rig cargado"}
    try:
        from src.core.fixtures import DEFAULT_RIG_FILE
        rig.save(params.get('path') or DEFAULT_RIG_FILE)
        return {"ok": True, "fixtures": len(rig.fixtures)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _h_add_fixture(app, params):
    """Añade un fixture al rig."""
    rig = getattr(app, 'fixture_rig', None)
    if rig is None:
        return {"ok": False, "error": "no hay rig cargado"}
    try:
        from src.core.fixtures import Fixture
        fid = params["fixture_id"]
        if rig.by_id(fid):
            return {"ok": False, "error": f"ya existe fixture_id={fid}"}
        fx = Fixture(
            fixture_id=fid,
            profile_id=params["profile_id"],
            universe=int(params.get("universe", 1)),
            dmx_start=int(params.get("dmx_start", 1)),
            position=tuple(params.get("position", (0.0, 1.0, 0.0))),
            rotation=tuple(params.get("rotation", (0.0, 0.0, 0.0))),
            label=params.get("label", fid),
            target_ip=params.get("target_ip"),
            legacy_bar_idx=params.get("legacy_bar_idx"),
        )
        rig.fixtures.append(fx)
        # Refrescar patch panel si está
        _qt_call_dual(app, "_refresh_patch")
        return {"ok": True, "fixture": fx.to_dict()}
    except KeyError as e:
        return {"ok": False, "error": f"falta parámetro {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _h_delete_fixture(app, params):
    rig = getattr(app, 'fixture_rig', None)
    if rig is None:
        return {"ok": False, "error": "no hay rig cargado"}
    fid = params["fixture_id"]
    fx = rig.by_id(fid)
    if not fx:
        return {"ok": False, "error": "fixture_id no encontrado"}
    rig.fixtures.remove(fx)
    _qt_call_dual(app, "_refresh_patch")
    return {"ok": True}


def _h_move_fixture(app, params):
    """Mueve un fixture (cambia su position y/o rotation)."""
    rig = getattr(app, 'fixture_rig', None)
    if rig is None:
        return {"ok": False, "error": "no hay rig cargado"}
    fx = rig.by_id(params["fixture_id"])
    if not fx:
        return {"ok": False, "error": "fixture_id no encontrado"}
    if "position" in params:
        fx.position = tuple(params["position"])
    if "rotation" in params:
        fx.rotation = tuple(params["rotation"])
    _qt_call_dual(app, "_refresh_patch")
    return {"ok": True, "fixture": fx.to_dict()}


def _h_set_fixture_property(app, params):
    """Cambia cualquier campo simple del fixture (universe, dmx_start, label, target_ip, profile_id)."""
    rig = getattr(app, 'fixture_rig', None)
    if rig is None:
        return {"ok": False, "error": "no hay rig cargado"}
    fx = rig.by_id(params["fixture_id"])
    if not fx:
        return {"ok": False, "error": "fixture_id no encontrado"}
    key = params["key"]
    val = params["value"]
    allowed = {'label', 'universe', 'dmx_start', 'profile_id', 'target_ip', 'legacy_bar_idx'}
    if key not in allowed:
        return {"ok": False, "error": f"key '{key}' no permitida (válidas: {allowed})"}
    if key in ('universe', 'dmx_start') and val is not None:
        val = int(val)
    setattr(fx, key, val)
    _qt_call_dual(app, "_refresh_patch")
    return {"ok": True, "fixture": fx.to_dict()}


def _h_set_fixture_channel(app, params):
    """Set un canal DMX manual de un fixture (override 0..1).

    params:
      fixture_id: str
      channel_name: str (debe existir en profile.channel_map)
      value: float 0..1   (None o "auto" para limpiar el override)

    El override persiste en `Fixture.manual_channels`. Pisa lo que generen
    los clips channel-level. El viewer 3D lo refleja en el siguiente tick.
    """
    rig = getattr(app, 'fixture_rig', None)
    if rig is None:
        return {"ok": False, "error": "no hay rig cargado"}
    fx = rig.by_id(params["fixture_id"])
    if not fx:
        return {"ok": False, "error": "fixture_id no encontrado"}
    prof = rig.get_profile(fx.profile_id)
    if prof is None:
        return {"ok": False, "error": f"profile {fx.profile_id} no carga"}

    ch_name = params["channel_name"]
    if ch_name not in prof.channel_map:
        return {"ok": False,
                "error": f"channel '{ch_name}' no en profile "
                         f"(válidos: {list(prof.channel_map.keys())})"}

    val = params.get("value")
    if not hasattr(fx, 'manual_channels') or fx.manual_channels is None:
        fx.manual_channels = {}
    if val is None or val == "auto":
        fx.manual_channels.pop(ch_name, None)
    else:
        try:
            v = float(val)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"value no numérico: {val!r}"}
        fx.manual_channels[ch_name] = max(0.0, min(1.0, v))

    return {"ok": True, "fixture_id": fx.fixture_id,
            "manual_channels": dict(fx.manual_channels)}


# ─── Channel Effects (Fase 7 v1.7) ─────────────────────────────────

def _h_list_channel_effects(app, params):
    """Lista todos los ChannelEffect disponibles, opcionalmente filtrados.

    params:
      category: str (opcional) — filtra por categoría (position/color/intensity/optical/strobe)
      fixture_id: str (opcional) — devuelve solo efectos compatibles con ese fixture/profile
    """
    try:
        from src.core.channel_effects import ChannelEffectLibrary
        lib = ChannelEffectLibrary()
    except Exception as e:
        return {"ok": False, "error": str(e), "effects": []}

    category = params.get("category")
    fixture_id = params.get("fixture_id")

    if fixture_id:
        rig = getattr(app, 'fixture_rig', None)
        if rig is None:
            return {"ok": False, "error": "No hay rig disponible", "effects": []}
        fx = rig.by_id(fixture_id)
        if fx is None:
            return {"ok": False, "error": f"Fixture '{fixture_id}' no encontrado", "effects": []}
        prof = rig.get_profile(fx.profile_id)
        if prof is None:
            return {"ok": False, "error": f"Profile '{fx.profile_id}' no encontrado", "effects": []}
        effects = lib.compatible_with_profile(prof)
        if category:
            effects = [e for e in effects if e.category == category]
    elif category:
        effects = lib.by_category(category)
    else:
        effects = lib.all()

    return {"ok": True, "effects": [e.describe() for e in effects], "count": len(effects)}


def _h_add_channel_clip(app, params):
    """Añade un clip de canal (category != 'pixel') al timeline para un fixture.

    params:
      fixture_id: str — id del fixture destino
      channel_effect_id: str — id del ChannelEffect (ej. 'pos_circle')
      start_ms: int
      duration_ms: int
      layer: int (default 0)
      clip_params: dict (default {}) — parámetros del efecto (speed, radius, etc.)

    El clip se crea con scope='fixture:<fixture_id>', category=<efecto.category>.
    """
    from src.core.timeline_model import Clip

    fixture_id = params.get("fixture_id")
    eff_id = params.get("channel_effect_id")
    start_ms = params.get("start_ms")
    duration_ms = params.get("duration_ms")

    for k, v in [("fixture_id", fixture_id), ("channel_effect_id", eff_id),
                 ("start_ms", start_ms), ("duration_ms", duration_ms)]:
        if v is None:
            return {"ok": False, "error": f"Falta parámetro '{k}'"}

    # Validar effect
    try:
        from src.core.channel_effects import ChannelEffectLibrary
        lib = ChannelEffectLibrary()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    effect = lib.get(eff_id)
    if effect is None:
        return {"ok": False, "error": f"ChannelEffect '{eff_id}' no existe. "
                                       f"Usa list_channel_effects para ver opciones."}

    # Validar fixture
    rig = getattr(app, 'fixture_rig', None)
    if rig is not None:
        fx = rig.by_id(fixture_id)
        if fx is None:
            return {"ok": False, "error": f"Fixture '{fixture_id}' no en el rig"}

    tl = getattr(app, 'timeline', None)
    if tl is None:
        return {"ok": False, "error": "No hay timeline activo"}

    start_ms = int(start_ms)
    end_ms = start_ms + int(duration_ms)
    layer = int(params.get("layer", 0))
    clip_params = dict(params.get("clip_params") or {})
    # Merge con default_params del efecto
    merged = dict(effect.default_params)
    merged.update(clip_params)

    clip = Clip(
        track=-1,                             # -1 = channel clip (no en track de barra)
        start_ms=start_ms,
        end_ms=end_ms,
        effect_id=0,                          # no aplica para channel clips
        scope=f"fixture:{fixture_id}",
        params=merged,
        label=effect.name,
        color="#aa5566",
        layer=layer,
        category=effect.category,
        channel_effect_id=eff_id,
    )

    # v1.9 F5 — BUG FIX: antes esta mutación iba dentro de _qt_call, pero
    # QTimer.singleShot desde el thread del bridge NO dispara → los clips
    # respondían `ok` pero nunca se añadían. Patrón correcto (igual que
    # _h_add_clip pixel): mutación directa al modelo + _qt_call solo para
    # refrescar UI.
    tl.add(clip)
    _qt_call(app, lambda: _dirty_timeline(app))
    return {"ok": True, "clip": clip.to_dict()}


def _h_get_dmx_universe(app, params):
    """Devuelve el último estado DMX ensamblado de un universo.

    params:
      universe_id: int
      format: 'int_list' | 'hex' (default 'int_list')

    Returns:
      {'universe': N, 'data': [0-255, ...] o 'RRGGBB...' hex}
    """
    uni = params.get("universe_id")
    if uni is None:
        return {"ok": False, "error": "Falta universe_id"}
    uni = int(uni)

    # Intentar obtener del OutputRouter (solo sim_only los guarda)
    tl = getattr(app, 'show_engine', None)
    router = getattr(tl, 'router', None) if tl else None
    raw = None
    if router is not None:
        raw = router.last_sent_for(uni)

    # Si no está en router, ensamblar en el momento
    if raw is None and tl is not None and getattr(tl, 'rig', None) is not None:
        try:
            t = getattr(app, '_last_t', 0.0)
            raw = tl.assemble_universe(uni, t, audio_context=None,
                                       rgb_frames_by_bar=None, timeline=None)
        except Exception as e:
            return {"ok": False, "error": f"Error ensamblando universo: {e}"}

    if raw is None:
        return {"ok": False, "error": f"Universo {uni} no disponible o sin datos",
                "universe": uni}

    fmt = params.get("format", "int_list")
    if fmt == "hex":
        data = raw.hex()
    else:
        data = list(raw)

    return {"ok": True, "universe": uni, "format": fmt, "data": data}


def _h_apply_channel_preset(app, params):
    """Aplica un preset de canales manuales a un fixture.

    params:
      fixture_id: str
      preset: dict {channel_name: 0..1} — valores normalizados

    Ejemplo:
      preset={'pan': 0.5, 'tilt': 0.3, 'dim': 1.0, 'r': 1.0, 'g': 0.0, 'b': 0.0}
    """
    fixture_id = params.get("fixture_id")
    preset = params.get("preset")
    if not fixture_id or not isinstance(preset, dict):
        return {"ok": False, "error": "Requiere 'fixture_id' y 'preset' (dict)"}

    rig = getattr(app, 'fixture_rig', None)
    if rig is None:
        return {"ok": False, "error": "No hay rig disponible"}
    fx = rig.by_id(fixture_id)
    if fx is None:
        return {"ok": False, "error": f"Fixture '{fixture_id}' no encontrado"}

    prof = rig.get_profile(fx.profile_id)
    valid = set(prof.channel_map.keys()) if prof else set()

    if not hasattr(fx, 'manual_channels') or fx.manual_channels is None:
        fx.manual_channels = {}

    applied = {}
    skipped = {}
    for ch_name, val in preset.items():
        if valid and ch_name not in valid:
            skipped[ch_name] = f"no en profile (validos: {sorted(valid)})"
            continue
        try:
            v = max(0.0, min(1.0, float(val)))
            fx.manual_channels[ch_name] = v
            applied[ch_name] = v
        except (TypeError, ValueError):
            skipped[ch_name] = f"valor no numérico: {val!r}"

    return {"ok": True, "fixture_id": fixture_id, "applied": applied,
            "skipped": skipped, "manual_channels": dict(fx.manual_channels)}


def _qt_call_dual(app, method_name):
    """Si dual_app está disponible, invoca un método en el thread Qt.

    Desacople (B1): si `app` provee `_qt_call_dual_impl` (ShowSession headless),
    se delega en él (típicamente notifica el cambio al stream del navegador)."""
    impl = getattr(app, '_qt_call_dual_impl', None)
    if impl is not None:
        impl(method_name)
        return
    try:
        dual = getattr(app, '_dual_window', None)
        if dual is None:
            return
        target = getattr(dual, method_name, None)
        if target:
            _qt_call(app, target)
    except Exception:
        pass


# ─── Analyzer (Fase B v1.6) ─────────────────────────────────────
#
# Toda la API expuesta vía AnalysisService (analyzer_service.py). El servicio
# vive en app.analysis (lo inyecta timeline_editor en __init__).

def _get_svc(app):
    """Devuelve el AnalysisService del editor, o None si no está disponible."""
    svc = getattr(app, 'analysis', None)
    return svc


def _h_analyzer_summary(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"available": False, "error": "AnalysisService no inicializado"}
    return {"available": True, "summary": svc.summary}


def _h_analyzer_list_sections(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"sections": [], "error": "AnalysisService no inicializado"}
    with_curated = bool(params.get("with_curated", True))
    secs = svc.list_sections(with_curated=with_curated)
    return {"sections": [s.to_dict() for s in secs], "count": len(secs)}


def _h_analyzer_list_beats(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"beats": []}
    t0 = float(params.get("start_sec", 0.0))
    t1 = params.get("end_sec")
    t1 = float(t1) if t1 is not None else None
    beats = svc.list_beats(t0, t1)
    return {"beats": beats, "count": len(beats)}


def _h_analyzer_list_downbeats(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"downbeats": []}
    t0 = float(params.get("start_sec", 0.0))
    t1 = params.get("end_sec")
    t1 = float(t1) if t1 is not None else None
    downbeats = svc.list_downbeats(t0, t1)
    source = svc.summary.get("downbeats_source", "?")
    return {"downbeats": downbeats, "count": len(downbeats), "source": source}


def _h_analyzer_list_events(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"events": []}
    kind = params.get("kind")
    if not kind:
        return {"events": [], "error": "param 'kind' requerido"}
    t0 = float(params.get("start_sec", 0.0))
    t1 = params.get("end_sec")
    t1 = float(t1) if t1 is not None else None
    evs = svc.list_events(kind, t0, t1)
    return {
        "events": [e.to_dict() for e in evs],
        "count": len(evs),
        "kind": kind,
    }


def _h_analyzer_get_features_at(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"features": {}}
    t = float(params["time_sec"])
    names = params.get("names")
    feats = svc.features_at(t, names=names)
    # Asegurar serialización: listas en vez de numpy arrays
    out = {}
    for k, v in feats.items():
        if hasattr(v, 'tolist'):
            out[k] = v.tolist()
        else:
            out[k] = v
    return {"time_sec": t, "features": out}


def _h_analyzer_get_features_range(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"times": [], "features": {}}
    t0 = float(params["start_sec"])
    t1 = float(params["end_sec"])
    ds = params.get("downsample_to")
    ds = int(ds) if ds is not None else None
    names = params.get("names")
    return svc.features_range(t0, t1, downsample_to=ds, names=names)


def _h_analyzer_find_drops(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"drops": []}
    jump = float(params.get("min_energy_jump", 0.4))
    drops = svc.find_drops(min_energy_jump=jump)
    return {"drops": drops, "count": len(drops)}


def _h_analyzer_find_breakdowns(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"breakdowns": []}
    min_sec = float(params.get("min_low_energy_sec", 4.0))
    bdws = svc.find_breakdowns(min_low_energy_sec=min_sec)
    return {"breakdowns": bdws, "count": len(bdws)}


def _h_analyzer_list_stems_events(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"available": False}
    stem = params.get("stem", "drums")
    return svc.list_stems_events(stem)


# ── Curación (writes) ───────────────────────────────────────────

def _h_analyzer_set_section_label(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"ok": False, "error": "no svc"}
    idx = int(params["idx"])
    name = str(params.get("name", ""))
    type_ = str(params.get("type", ""))
    svc.curation.set_section_label(idx, name=name, type=type_)
    svc.curation.save()
    _qt_call_dual(app, "_refresh_analyzer_overlays")
    return {"ok": True, "idx": idx, "name": name, "type": type_}


def _h_analyzer_add_manual_event(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"ok": False, "error": "no svc"}
    t = float(params["time_sec"])
    kind = str(params["kind"])
    name = str(params.get("name", ""))
    svc.curation.add_manual_event(t, kind, name=name)
    svc.curation.save()
    _qt_call_dual(app, "_refresh_analyzer_overlays")
    return {"ok": True, "time_sec": t, "kind": kind, "name": name}


def _h_analyzer_disable_event(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"ok": False, "error": "no svc"}
    t = float(params["time_sec"])
    kind = str(params["kind"])
    tol = int(params.get("tolerance_ms", 20))
    n = svc.curation.disable_event(t, kind, tolerance_ms=tol)
    svc.curation.save()
    _qt_call_dual(app, "_refresh_analyzer_overlays")
    return {"ok": True, "marked": n}


def _h_analyzer_set_event_threshold(app, params):
    svc = _get_svc(app)
    if svc is None:
        return {"ok": False, "error": "no svc"}
    kind = str(params["kind"])
    val = float(params["value"])
    svc.curation.set_event_threshold(kind, val)
    svc.curation.save()
    return {"ok": True, "kind": kind, "value": val}


# ─── Clips ──────────────────────────────────────────────────────

def _h_list_clips(app, params):
    flt = params.get("filter", {})
    t_lo = flt.get("start_ms_min")
    t_hi = flt.get("start_ms_max")
    track = flt.get("track")
    scope = flt.get("scope")
    out = []
    for c in app.timeline.clips:
        if t_lo is not None and c.end_ms < t_lo: continue
        if t_hi is not None and c.start_ms > t_hi: continue
        if track is not None and c.track != track: continue
        if scope is not None and c.scope != scope: continue
        out.append(c.to_dict())
    return {"clips": out, "count": len(out)}


def _dirty_timeline(app, refresh_props=False):
    """
    Marca el timeline como modificado: invalida cachés y agenda rebuild.
    Se llama tras add/delete/move/set de clips.

    Separated concerns:
    1. Pure cache invalidation (now in session.invalidate_caches)
    2. Qt-only UI rebuilds (happens here after cache invalidation)
    """
    def _do():
        try:
            # 1. Pure cache invalidation (works in both Qt and headless mode)
            if hasattr(app, 'invalidate_caches'):
                app.invalidate_caches()

            # 2. Qt-only UI rebuilds (skipped in headless via hasattr guards)
            if hasattr(app, 'tl_view'):
                app.tl_view._layers_cache = {}
                app.tl_view._update_snap_pts()
                app.tl_view._rebuild_scene()

            # 3. Qt-only properties refresh (after delete)
            if refresh_props and hasattr(app, 'props') and hasattr(app, 'tl_view'):
                app.props.set_clips([c for c in app.tl_view.selected_clips
                                     if c in app.timeline.clips])
        except Exception as e:
            print(f"[mcp_bridge] _dirty_timeline error: {e}")
    _qt_call(app, _do)


def _find_clip_by_id(app, clip_id):
    """Devuelve el clip cuyo id(clip) coincide con clip_id (entero)."""
    # ShowSession (headless): use el método optimizado
    if hasattr(app, 'find_clip_by_id'):
        return app.find_clip_by_id(clip_id)
    # TimelineEditorWindow (legacy Qt): fallback a búsqueda manual
    for c in app.timeline.clips:
        if id(c) == int(clip_id):
            return c
    return None


# ─── Clips: write operations ────────────────────────────────────

def _h_add_clip(app, params):
    """Añade un clip nuevo al timeline."""
    from src.core.timeline_model import Clip
    try:
        new_clip = Clip(
            track=int(params.get("track", 0)),
            start_ms=int(params["start_ms"]),
            end_ms=int(params["end_ms"]),
            effect_id=int(params["effect_id"]),
            scope=params.get("scope", "per_bar"),
            color=params.get("color", "#3a7acc"),
            layer=int(params.get("layer", 0)),
            label=params.get("label", ""),
            locked=bool(params.get("locked", False)),
            muted=bool(params.get("muted", False)),
            params=dict(params.get("params", {})),
        )
        if new_clip.end_ms <= new_clip.start_ms:
            return {"ok": False, "error": "end_ms debe ser mayor que start_ms"}
        app.timeline.add(new_clip)
        _dirty_timeline(app)
        return {"ok": True, "clip": new_clip.to_dict()}
    except KeyError as e:
        return {"ok": False, "error": f"falta parámetro {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _h_delete_clip(app, params):
    """Borra un clip por su id (id(clip))."""
    c = _find_clip_by_id(app, params["clip_id"])
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    if c.locked:
        return {"ok": False, "error": "clip bloqueado"}
    app.timeline.remove(c)
    _dirty_timeline(app, refresh_props=True)
    return {"ok": True}


def _h_move_clip(app, params):
    """Cambia start/end/track de un clip. Mantiene duración si solo se da new_start_ms."""
    c = _find_clip_by_id(app, params["clip_id"])
    if c is None:
        return {"ok": False, "error": "clip_id no encontrado"}
    if c.locked:
        return {"ok": False, "error": "clip bloqueado"}
    dur = c.end_ms - c.start_ms
    if "new_start_ms" in params:
        c.start_ms = max(0, int(params["new_start_ms"]))
        c.end_ms = c.start_ms + dur
    if "new_end_ms" in params:
        c.end_ms = max(c.start_ms + 50, int(params["new_end_ms"]))
    if "new_track" in params:
        c.track = int(params["new_track"])
    if "new_layer" in params:
        c.layer = max(0, int(params["new_layer"]))
    _dirty_timeline(app)
    return {"ok": True, "clip": c.to_dict()}


def _h_set_clip_color(app, params):
    c = _find_clip_by_id(app, params["clip_id"])
    if c is None: return {"ok": False, "error": "clip_id no encontrado"}
    c.color = params["color"]
    _dirty_timeline(app)
    return {"ok": True}


def _h_set_clip_params(app, params):
    """Actualiza el dict de params (hue/sat/speed) del clip."""
    c = _find_clip_by_id(app, params["clip_id"])
    if c is None: return {"ok": False, "error": "clip_id no encontrado"}
    c.params.update(params.get("params", {}))
    _dirty_timeline(app)
    return {"ok": True, "params": dict(c.params)}


def _h_set_clip_mute(app, params):
    c = _find_clip_by_id(app, params["clip_id"])
    if c is None: return {"ok": False, "error": "clip_id no encontrado"}
    c.muted = bool(params["muted"])
    _dirty_timeline(app)
    return {"ok": True, "muted": c.muted}


def _h_set_clip_lock(app, params):
    c = _find_clip_by_id(app, params["clip_id"])
    if c is None: return {"ok": False, "error": "clip_id no encontrado"}
    c.locked = bool(params["locked"])
    _dirty_timeline(app)
    return {"ok": True, "locked": c.locked}


def _h_set_clip_scope(app, params):
    c = _find_clip_by_id(app, params["clip_id"])
    if c is None: return {"ok": False, "error": "clip_id no encontrado"}
    c.scope = params["scope"]
    # invalidar cache visual_track del clip
    try:
        del c._vt_cached
    except AttributeError:
        pass
    _dirty_timeline(app)
    return {"ok": True, "scope": c.scope}


# ─── Grupos: write operations ───────────────────────────────────

def _h_add_group(app, params):
    """Añade un nuevo BarGroup."""
    from src.core.timeline_model import BarGroup
    name = params["name"]
    # Comprobar duplicado
    if any(g.name == name for g in (app.timeline.groups or [])):
        return {"ok": False, "error": f"ya existe grupo '{name}'"}
    g = BarGroup(
        name=name,
        bars=list(params.get("bars", [])),
        color=params.get("color", "#888888"),
        subgroups=list(params.get("subgroups", [])),
    )
    if app.timeline.groups is None:
        app.timeline.groups = []
    app.timeline.groups.append(g)
    _dirty_timeline(app)
    # refresh dropdown de scope en props
    _qt_call(app, lambda: app.props.refresh_groups(app.timeline.groups))
    return {"ok": True, "group": g.to_dict()}


def _h_delete_group(app, params):
    name = params["name"]
    grp = next((g for g in (app.timeline.groups or []) if g.name == name), None)
    if grp is None:
        return {"ok": False, "error": "grupo no encontrado"}
    app.timeline.groups.remove(grp)
    _dirty_timeline(app)
    _qt_call(app, lambda: app.props.refresh_groups(app.timeline.groups))
    return {"ok": True}


def _h_set_group_bars(app, params):
    name = params["name"]
    grp = next((g for g in (app.timeline.groups or []) if g.name == name), None)
    if grp is None:
        return {"ok": False, "error": "grupo no encontrado"}
    grp.bars = list(params.get("bars", []))
    if "subgroups" in params:
        grp.subgroups = list(params["subgroups"])
    if "color" in params:
        grp.color = params["color"]
    _dirty_timeline(app)
    return {"ok": True, "group": grp.to_dict()}


# ─── Markers ────────────────────────────────────────────────────

def _h_list_markers(app, params):
    return {"markers": list(app.tl_view.time_markers)}


def _h_add_marker(app, params):
    t_ms = int(params["time_ms"]) if "time_ms" in params else int(float(params["t_sec"]) * 1000)
    name = params.get("name", "Marker")
    color = params.get("color", "#ff9933")
    app.tl_view.time_markers.append({"time_ms": t_ms, "name": name, "color": color})
    _qt_call(app, lambda: (app.tl_view._update_snap_pts(), app.tl_view._rebuild_scene()))
    return {"ok": True}


def _h_delete_marker(app, params):
    t_ms = int(params["time_ms"])
    before = len(app.tl_view.time_markers)
    app.tl_view.time_markers = [m for m in app.tl_view.time_markers if m["time_ms"] != t_ms]
    _qt_call(app, lambda: (app.tl_view._update_snap_pts(), app.tl_view._rebuild_scene()))
    return {"ok": True, "deleted": before - len(app.tl_view.time_markers)}


# ─── Cues: rename ──────────────────────────────────────────────

def _h_rename_cue(app, params):
    slot = int(params["slot"])
    cue = next((c for c in app.timeline.cue_points if c.slot == slot), None)
    if cue is None:
        return {"ok": False, "error": "slot fuera de rango"}
    cue.name = params.get("name", "")
    _qt_call(app, app._refresh_cue_buttons)
    return {"ok": True, "cue": cue.to_dict()}


# ─── Persistencia: load_show / list_saved_shows ────────────────

def _h_load_show(app, params):
    from src.core.timeline_model import Timeline
    path = params["path"]
    try:
        new_tl = Timeline.load(path)
        app.timeline.clips = new_tl.clips
        app.timeline.duration_ms = new_tl.duration_ms
        if new_tl.groups:
            app.timeline.groups = new_tl.groups
        if hasattr(new_tl, 'cue_points') and new_tl.cue_points:
            app.timeline.cue_points = new_tl.cue_points
        _dirty_timeline(app)
        _qt_call(app, lambda: app.props.refresh_groups(app.timeline.groups or []))
        _qt_call(app, app._refresh_cue_buttons)
        return {"ok": True, "clips": len(app.timeline.clips),
                "groups": len(app.timeline.groups or [])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _h_list_saved_shows(app, params):
    from src._paths import SHOWS_SAVED_DIR
    saved_dir = SHOWS_SAVED_DIR
    if not saved_dir.is_dir():
        return {"shows": []}
    out = []
    for p in saved_dir.glob('*.json'):
        out.append({
            "name": p.stem,
            "path": str(p),
            "size_kb": round(p.stat().st_size / 1024, 1),
        })
    return {"shows": out, "count": len(out)}


def _h_get_active_clips(app, params):
    t = params.get("t_sec", app.audio.get_time())
    t_ms = int(float(t) * 1000)
    return {"clips": [c.to_dict() for c in app.timeline.clips if c.contains(t_ms)]}


# ─── Cues ──────────────────────────────────────────────────────

def _h_list_cue_points(app, params):
    return {"cues": [c.to_dict() for c in app.timeline.cue_points]}


def _h_set_cue(app, params):
    slot = int(params["slot"])
    t_sec = float(params.get("t_sec", app.audio.get_time()))
    name = params.get("name")
    cue = next((c for c in app.timeline.cue_points if c.slot == slot), None)
    if cue is None:
        return {"ok": False, "error": f"slot {slot} fuera de rango"}
    cue.time_ms = int(t_sec * 1000)
    if name is not None:
        cue.name = name
    # Refrescar UI en el thread de Qt
    _qt_call(app, app._refresh_cue_buttons)
    return {"ok": True, "cue": cue.to_dict()}


def _h_trigger_cue(app, params):
    slot = int(params["slot"])
    _qt_call(app, lambda: app._trigger_cue(slot))
    return {"ok": True}


def _h_clear_cue(app, params):
    slot = int(params["slot"])
    # Aplicar el cambio directamente en el modelo (sin pasar por método del
    # editor, que tenía race condition con _qt_call).
    cue = next((c for c in app.timeline.cue_points if c.slot == slot), None)
    if cue:
        cue.time_ms = -1
        cue.name = ""
    # Refrescar la UI en el thread de Qt
    _qt_call(app, app._refresh_cue_buttons)
    return {"ok": True}


# ─── Grupos ─────────────────────────────────────────────────────

def _h_list_groups(app, params):
    return {"groups": [g.to_dict() for g in (app.timeline.groups or [])]}


# ─── Catálogo ───────────────────────────────────────────────────

def _h_list_effects(app, params):
    out = []
    for eid, eff in app.library.effects.items():
        out.append({
            "id": eid,
            "name": eff.name,
            "family": getattr(eff, "family", ""),
            "duration_ms": getattr(eff, "duration_ms", 0),
            "scope": getattr(eff, "scope", "").value if hasattr(getattr(eff, "scope", None), "value") else str(getattr(eff, "scope", "")),
            "description": getattr(eff, "description", ""),
        })
    return {"effects": out, "count": len(out)}


# ─── Persistencia ───────────────────────────────────────────────

def _h_save_show(app, params):
    path = params.get("path")
    try:
        if path:
            app.timeline.save(path)
            saved = str(path)
        elif getattr(app, '_pm', None) and getattr(app, '_project', None):
            app._pm.save_show(app.timeline)
            saved = str(app._project.show_file)
        else:
            app.timeline.save()
            saved = "default(legacy)"
        return {"ok": True, "path": saved}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Generation tools (v1.8) ────────────────────────────────────

_NAMED_PALETTES = {
    "warm":    [0, 20, 40, 60],
    "cool":    [180, 200, 220, 240],
    "fire":    [0, 10, 20, 30, 40],
    "ocean":   [180, 195, 210, 225],
    "rainbow": [0, 30, 60, 120, 180, 240, 300],
    "purple":  [260, 275, 290, 300],
    "neon":    [120, 180, 280, 0],
    "mono":    [60],
}


def _h_generate_section(app, params):
    """Genera clips pixel en un rango temporal sincronizados con eventos de audio."""
    import re as _re
    from src.core.timeline_model import Clip

    svc = _get_svc(app)

    # ── Resolver rango temporal ──
    start_sec = params.get("start_sec")
    end_sec = params.get("end_sec")
    section_name = params.get("section_name")

    if section_name and svc is not None:
        sections = svc.list_sections(with_curated=True)
        # list_sections() returns Section objects with .to_dict()
        dicts = [s.to_dict() if hasattr(s, "to_dict") else s for s in sections]
        matched = [s for s in dicts if s.get("label", "").lower() == section_name.lower()
                   or s.get("type", "").lower() == section_name.lower()]
        if not matched:
            return {"ok": False, "error": f"sección '{section_name}' no encontrada"}
        start_sec = matched[0]["start"]
        end_sec = matched[0]["end"]

    if start_sec is None or end_sec is None:
        return {"ok": False, "error": "se requiere start_sec+end_sec o section_name"}

    start_sec = float(start_sec)
    end_sec = float(end_sec)
    start_ms = int(start_sec * 1000)
    end_ms = int(end_sec * 1000)

    # ── Parámetros del clip ──
    effect_id = int(params.get("effect_id", 0))
    scope = params.get("scope", "per_bar")
    track = int(params.get("track", 0))
    layer = int(params.get("layer", 0))
    color = params.get("color", "#3a7acc")
    clip_params = dict(params.get("clip_params") or {})
    spacing_ms = int(params.get("spacing_ms", 0))
    max_clips = int(params.get("max_clips", 200))
    dry_run = bool(params.get("dry_run", False))

    # ── Duración del clip ──
    # Si no se especifica, usar duration_ms del efecto del catálogo
    clip_dur_ms = params.get("clip_duration_ms")
    if clip_dur_ms is None:
        try:
            from src.core.effects_engine import EffectLibrary
            lib = EffectLibrary()
            eff = lib.get(effect_id)
            clip_dur_ms = eff.duration_ms if eff else 200
        except Exception:
            clip_dur_ms = 200
    clip_dur_ms = int(clip_dur_ms)

    # ── Calcular posiciones de trigger ──
    trigger = params.get("trigger", "on_beat")
    trigger_positions_ms = []

    if trigger == "fill":
        # Un solo clip que rellena toda la sección
        trigger_positions_ms = [start_ms]
        clip_dur_ms = end_ms - start_ms

    elif trigger.startswith("every_"):
        # Formato: "every_500ms"
        m = _re.match(r"every_(\d+)ms", trigger)
        if m:
            step = int(m.group(1))
            t = start_ms
            while t < end_ms:
                trigger_positions_ms.append(t)
                t += step
        else:
            return {"ok": False, "error": f"formato inválido: '{trigger}'. Usar 'every_500ms'"}

    elif trigger in ("on_beat", "on_downbeat") and svc is not None:
        beats = svc.list_beats(start_sec, end_sec) if trigger == "on_beat" else svc.list_downbeats(start_sec, end_sec)
        trigger_positions_ms = [int(b * 1000) for b in beats]

    elif trigger in ("on_kick", "on_snare", "on_hat") and svc is not None:
        kind = {"on_kick": "kick", "on_snare": "snare", "on_hat": "hat"}[trigger]
        evs = svc.list_events(kind, start_sec, end_sec)
        trigger_positions_ms = [int(e.time * 1000) for e in evs]

    elif trigger == "on_drop" and svc is not None:
        drops = svc.find_drops()
        trigger_positions_ms = [int(d["time"] * 1000) for d in drops
                                 if start_ms <= int(d["time"] * 1000) < end_ms]

    else:
        # Sin analyzer o trigger desconocido → on_beat fallback cada 500ms
        t = start_ms
        while t < end_ms:
            trigger_positions_ms.append(t)
            t += 500

    # ── Filtrar y limitar ──
    trigger_positions_ms = [p for p in trigger_positions_ms if start_ms <= p < end_ms]

    # Aplicar spacing mínimo
    if spacing_ms > 0:
        filtered = []
        last = -999999
        for p in sorted(trigger_positions_ms):
            if p - last >= spacing_ms:
                filtered.append(p)
                last = p
        trigger_positions_ms = filtered

    trigger_positions_ms = trigger_positions_ms[:max_clips]

    # ── Generar clips ──
    clips_preview = []
    for pos_ms in trigger_positions_ms:
        clip_end = min(pos_ms + clip_dur_ms, end_ms)
        if clip_end <= pos_ms:
            continue
        clips_preview.append({
            "start_ms": pos_ms,
            "end_ms": clip_end,
            "effect_id": effect_id,
            "scope": scope,
            "track": track,
            "layer": layer,
            "color": color,
            "params": clip_params,
        })

    if dry_run:
        return {"ok": True, "dry_run": True, "clips": clips_preview, "count": len(clips_preview)}

    created = []
    for cd in clips_preview:
        c = Clip(
            track=cd["track"],
            start_ms=cd["start_ms"],
            end_ms=cd["end_ms"],
            effect_id=cd["effect_id"],
            scope=cd["scope"],
            color=cd["color"],
            layer=cd["layer"],
            params=dict(cd["params"]),
        )
        app.timeline.add(c)
        created.append(c.to_dict())

    if created:
        _dirty_timeline(app)

    return {"ok": True, "count": len(created), "clips": created}


def _h_mirror_clips_lr(app, params):
    """Espeja clips bar:N → bar:(9-N) en un rango temporal."""
    from src.core.timeline_model import Clip

    start_ms = int(params.get("start_ms", 0))
    end_ms = params.get("end_ms")
    end_ms = int(end_ms) if end_ms is not None else None
    filter_track = params.get("track")  # None = todos
    layer_offset = int(params.get("layer_offset", 1))
    color_override = params.get("color")
    dry_run = bool(params.get("dry_run", False))

    clips_in_range = [
        c for c in app.timeline.clips
        if c.start_ms >= start_ms
        and (end_ms is None or c.start_ms < end_ms)
        and (filter_track is None or c.track == int(filter_track))
        and c.scope.startswith("bar:")
    ]

    if not clips_in_range:
        return {"ok": False, "error": "no hay clips con scope 'bar:N' en el rango indicado"}

    created = []
    for c in clips_in_range:
        try:
            bar_n = int(c.scope.split(":")[1])
        except (IndexError, ValueError):
            continue
        mirror_bar = 9 - bar_n
        if mirror_bar == bar_n:
            continue  # bar 4 o 5 (centro) — no espejar
        mirror_scope = f"bar:{mirror_bar}"
        if any(x.start_ms == c.start_ms and x.scope == mirror_scope and x.track == c.track
               for x in app.timeline.clips):
            continue  # ya existe un clip espejo

        created.append({
            "track": c.track,
            "start_ms": c.start_ms,
            "end_ms": c.end_ms,
            "effect_id": c.effect_id,
            "scope": mirror_scope,
            "color": color_override or c.color,
            "layer": c.layer + layer_offset,
            "params": dict(c.params),
        })

    if dry_run:
        return {"ok": True, "dry_run": True, "mirrors": created, "count": len(created)}

    added = []
    for cd in created:
        nc = Clip(
            track=cd["track"],
            start_ms=cd["start_ms"],
            end_ms=cd["end_ms"],
            effect_id=cd["effect_id"],
            scope=cd["scope"],
            color=cd["color"],
            layer=cd["layer"],
            params=dict(cd["params"]),
        )
        app.timeline.add(nc)
        added.append(nc.to_dict())

    if added:
        _dirty_timeline(app)

    return {"ok": True, "count": len(added), "clips": added}


def _h_apply_palette_to_range(app, params):
    """Cambia el parámetro 'hue' de los clips en un rango según una paleta de colores."""
    import random as _random

    start_ms = int(params.get("start_ms", 0))
    end_ms = params.get("end_ms")
    end_ms = int(end_ms) if end_ms is not None else None
    filter_track = params.get("track")
    palette_input = params.get("palette", "rainbow")
    mode = params.get("mode", "cycle")  # "cycle" | "random" | "gradient"

    # Resolver paleta
    if isinstance(palette_input, str):
        hues = _NAMED_PALETTES.get(palette_input.lower())
        if hues is None:
            return {"ok": False, "error": f"paleta desconocida '{palette_input}'. Opciones: {list(_NAMED_PALETTES.keys())}"}
    elif isinstance(palette_input, list):
        hues = [int(h) % 360 for h in palette_input]
    else:
        return {"ok": False, "error": "palette debe ser str o lista de enteros (hue 0-360)"}

    clips_in_range = [
        c for c in app.timeline.clips
        if c.start_ms >= start_ms
        and (end_ms is None or c.start_ms < end_ms)
        and (filter_track is None or c.track == int(filter_track))
        and not c.locked
    ]

    if not clips_in_range:
        return {"ok": False, "error": "no hay clips desbloqueados en el rango indicado"}

    # Ordenar por start_ms para gradient/cycle
    clips_in_range = sorted(clips_in_range, key=lambda c: c.start_ms)

    updated = []
    for i, c in enumerate(clips_in_range):
        if mode == "cycle":
            hue = hues[i % len(hues)]
        elif mode == "random":
            hue = _random.choice(hues)
        elif mode == "gradient":
            ratio = i / max(1, len(clips_in_range) - 1)
            idx_f = ratio * (len(hues) - 1)
            idx_lo = int(idx_f)
            idx_hi = min(idx_lo + 1, len(hues) - 1)
            frac = idx_f - idx_lo
            hue = int(hues[idx_lo] + frac * (hues[idx_hi] - hues[idx_lo])) % 360
        else:
            return {"ok": False, "error": f"mode desconocido '{mode}'. Opciones: cycle, random, gradient"}

        c.params["hue"] = hue
        updated.append({"clip_id": id(c), "hue": hue})

    if updated:
        _dirty_timeline(app)

    return {"ok": True, "count": len(updated), "updates": updated}


# ─── Mapa de métodos ────────────────────────────────────────────

HANDLERS: Dict[str, Callable] = {
    # Read / transport
    "ping": _h_ping,
    "get_state": _h_get_state,
    "play": _h_play,
    "pause": _h_pause,
    "stop": _h_stop,
    "seek": _h_seek,
    "set_blackout": _h_set_blackout,
    "open_3d_viewer": _h_open_3d_viewer,
    # Fixtures (Fase 3)
    "list_fixtures": _h_list_fixtures,
    "list_fixture_profiles": _h_list_fixture_profiles,
    "save_rig": _h_save_rig,
    "add_fixture": _h_add_fixture,
    "delete_fixture": _h_delete_fixture,
    "move_fixture": _h_move_fixture,
    "set_fixture_property": _h_set_fixture_property,
    "set_fixture_channel": _h_set_fixture_channel,
    # Channel Effects (Fase 7 v1.7)
    "list_channel_effects": _h_list_channel_effects,
    "add_channel_clip": _h_add_channel_clip,
    "get_dmx_universe": _h_get_dmx_universe,
    "apply_channel_preset": _h_apply_channel_preset,
    # Generation tools (v1.8)
    "generate_section": _h_generate_section,
    "mirror_clips_lr": _h_mirror_clips_lr,
    "apply_palette_to_range": _h_apply_palette_to_range,
    # Clips (read)
    "list_clips": _h_list_clips,
    "get_active_clips": _h_get_active_clips,
    # Clips (write)
    "add_clip": _h_add_clip,
    "delete_clip": _h_delete_clip,
    "move_clip": _h_move_clip,
    "set_clip_color": _h_set_clip_color,
    "set_clip_params": _h_set_clip_params,
    "set_clip_mute": _h_set_clip_mute,
    "set_clip_lock": _h_set_clip_lock,
    "set_clip_scope": _h_set_clip_scope,
    # Grupos
    "list_groups": _h_list_groups,
    "add_group": _h_add_group,
    "delete_group": _h_delete_group,
    "set_group_bars": _h_set_group_bars,
    # Cues
    "list_cue_points": _h_list_cue_points,
    "set_cue": _h_set_cue,
    "trigger_cue": _h_trigger_cue,
    "clear_cue": _h_clear_cue,
    "rename_cue": _h_rename_cue,
    # Markers
    "list_markers": _h_list_markers,
    "add_marker": _h_add_marker,
    "delete_marker": _h_delete_marker,
    # Catálogo
    "list_effects": _h_list_effects,
    # Persistencia
    "save_show": _h_save_show,
    "load_show": _h_load_show,
    "list_saved_shows": _h_list_saved_shows,
    # Analyzer (Fase B v1.6) — reads
    "analyzer_summary": _h_analyzer_summary,
    "analyzer_list_sections": _h_analyzer_list_sections,
    "analyzer_list_beats": _h_analyzer_list_beats,
    "analyzer_list_downbeats": _h_analyzer_list_downbeats,
    "analyzer_list_events": _h_analyzer_list_events,
    "analyzer_get_features_at": _h_analyzer_get_features_at,
    "analyzer_get_features_range": _h_analyzer_get_features_range,
    "analyzer_find_drops": _h_analyzer_find_drops,
    "analyzer_find_breakdowns": _h_analyzer_find_breakdowns,
    "analyzer_list_stems_events": _h_analyzer_list_stems_events,
    # Analyzer — writes (curación)
    "analyzer_set_section_label": _h_analyzer_set_section_label,
    "analyzer_add_manual_event": _h_analyzer_add_manual_event,
    "analyzer_disable_event": _h_analyzer_disable_event,
    "analyzer_set_event_threshold": _h_analyzer_set_event_threshold,
}


# ───────────────────────────────────────────────────────────────
# Qt thread bridge
# ───────────────────────────────────────────────────────────────

def _qt_call(app, fn):
    """Ejecuta `fn()` en el thread principal de Qt usando QTimer.singleShot(0).

    Desacople (B1): si `app` provee `_qt_call_impl` (lo hace ShowSession headless),
    se delega en él en vez de tocar Qt. Antes esto se hacía parcheando el módulo
    global desde el dispatcher; ahora cada sesión decide su propia política.
    """
    impl = getattr(app, '_qt_call_impl', None)
    if impl is not None:
        impl(fn)
        return
    try:
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, fn)
    except Exception:
        # Fallback: ejecutar directamente (no thread-safe pero mejor que nada)
        try:
            fn()
        except Exception as e:
            print(f"[mcp_bridge] _qt_call fallback error: {e}")


# ───────────────────────────────────────────────────────────────
# JSON-RPC dispatch
# ───────────────────────────────────────────────────────────────

def _dispatch(app, msg: dict) -> dict:
    """Procesa un mensaje JSON-RPC y devuelve la respuesta."""
    msg_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method not in HANDLERS:
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"Método desconocido: {method}"}}
    try:
        result = HANDLERS[method](app, params)
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[mcp_bridge] Error en {method}:\n{tb}")
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32000, "message": str(e), "data": tb}}


async def _handle_client(websocket, app_provider):
    """Cada conexión WebSocket entrante.

    v1.9 F2: el except Exception genérico evita que excepciones inesperadas
    (cliente muere a media respuesta, payload corrupto, etc.) tumben el
    thread del bridge. Las InvalidMessage durante handshake se manejan en
    el exception handler del loop (set_exception_handler en MCPBridge.start).
    """
    print(f"[mcp_bridge] cliente conectado")
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as e:
                await websocket.send(json.dumps({
                    "jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": f"JSON parse error: {e}"}
                }))
                continue
            app = app_provider()
            if app is None:
                await websocket.send(json.dumps({
                    "jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32002, "message": "App no inicializada"}
                }))
                continue
            response = _dispatch(app, msg)
            await websocket.send(json.dumps(response))
    except websockets.ConnectionClosed:
        pass
    except Exception as e:
        # v1.9 F2: cualquier otra cosa (cliente que se va, payload roto,
        # error de socket) se loguea pero NO mata el thread/loop.
        print(f"[mcp_bridge] conexión cerrada por error: "
              f"{type(e).__name__}: {e}")
    finally:
        print(f"[mcp_bridge] cliente desconectado")


async def _server_main(app_provider):
    print(f"[mcp_bridge] WebSocket listening on ws://{HOST}:{PORT}")
    async with websockets.serve(lambda ws: _handle_client(ws, app_provider),
                                HOST, PORT, ping_interval=20):
        await asyncio.Future()  # corre para siempre


# ───────────────────────────────────────────────────────────────
# Public API: arrancar el bridge desde dual_app.py
# ───────────────────────────────────────────────────────────────

class MCPBridge:
    """Wrapper para arrancar y parar el servidor desde la app principal."""

    def __init__(self, app_provider: Callable):
        """
        app_provider: callable que devuelve la TimelineEditorWindow viva
                      (o None si aún no está lista). Se llama en cada request.
        """
        self.app_provider = app_provider
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self):
        if self._thread is not None:
            return

        def _exc_handler(loop, ctx):
            """v1.9 F2 — Exception handler global del loop asyncio.

            Atrapa errores que la librería websockets levanta DURANTE el
            handshake (antes de invocar _handle_client). Casos típicos:
              • Cliente que hace TCP raw sin HTTP (Test-NetConnection,
                healthchecks): websockets.exceptions.InvalidMessage
              • Cliente que tira la conexión a la mitad del handshake:
                ConnectionResetError, EOFError, BrokenPipeError
            Sin este handler, la excepción no capturada mata el thread y
            la app entera (race condition con Qt).
            """
            exc = ctx.get('exception')
            msg = ctx.get('message', 'unknown')
            try:
                _silenciables = (websockets.exceptions.InvalidMessage,
                                 ConnectionResetError, EOFError, BrokenPipeError,
                                 OSError)
            except AttributeError:
                _silenciables = (ConnectionResetError, EOFError, BrokenPipeError, OSError)
            if exc is not None and isinstance(exc, _silenciables):
                return   # ignorar silencioso — son normales
            # Errores reales sí se loguean
            exc_name = type(exc).__name__ if exc else 'no-exc'
            print(f"[mcp_bridge] async error: {msg} ({exc_name})")

        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.set_exception_handler(_exc_handler)
            try:
                self._loop.run_until_complete(_server_main(self.app_provider))
            except Exception as e:
                print(f"[mcp_bridge] thread terminated: {e}")
        self._thread = threading.Thread(target=_run, daemon=True, name="mcp_bridge")
        self._thread.start()

    def stop(self):
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)


# ───────────────────────────────────────────────────────────────
# Modo standalone (para testing sin Qt)
# ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if "--mock" in sys.argv:
        # Mock minimal para probar el dispatcher sin Qt
        class MockApp:
            class _A:
                playing = False
                duration_s = 273.3
                _path = "mock.mp3"
                def get_time(self): return 12.5
                def play(self, s=0.0): self.playing = True
                def pause(self): self.playing = False
                def stop(self): self.playing = False
                def seek(self, t): pass
            class _TL:
                clips = []
                groups = []
                cue_points = []
            audio = _A()
            timeline = _TL()
            show_engine = None
            tl_view = type("V", (), {"_snap_grid": "beat", "_snap_on": True})()
            library = type("L", (), {"effects": {}})()
            def _send_blackout(self): print("blackout!")
            def _refresh_cue_buttons(self): pass
            def _trigger_cue(self, s): print(f"trigger cue {s}")
            def _clear_cue(self, s): pass
        app = MockApp()
        print("[mock] Servidor WS arrancando con MockApp en ws://127.0.0.1:9876")
        try:
            asyncio.run(_server_main(lambda: app))
        except KeyboardInterrupt:
            print("\n[mock] Cerrado")
    else:
        print("Este módulo se importa desde dual_app.py.")
        print("Para test standalone: python mcp_bridge.py --mock")
