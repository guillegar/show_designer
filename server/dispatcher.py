"""
dispatcher.py — Capa JSON-RPC Qt-free reutilizando los 52 handlers del bridge.

En vez de re-escribir los handlers de `src/mcp/mcp_bridge.py` (riesgo de
divergencia), los **reutilizamos** tal cual:

  * Los handlers son funciones de módulo `_h_<name>(app, params)` que acceden al
    modelo SOLO vía atributos de `app` (timeline/show_engine/fixture_rig/
    analysis/library/audio). `ShowSession` expone exactamente esos atributos
    (+ shims `tl_view`/`props`/`_pm`/`_project`), así que es un `app` válido.
  * El marshalling de mutaciones del bridge (`_qt_call`/`_qt_call_dual`) lo provee
    la sesión vía `_qt_call_impl`/`_qt_call_dual_impl`: ejecuta `fn()` inline
    (estamos en un único loop asyncio) y dispara `session.notify_changed()` para
    que el stream avise al navegador (los `_dual` además notifican cambios de rig).
    La rama Qt original (QTimer) se retiró en la Fase 8.

Resultado: `Dispatcher.handle(msg)` procesa un mensaje JSON-RPC 2.0 idéntico al
del bridge — el MISMO protocolo que ya habla `mcp_show_server.py` (Claude).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Setup MINIMAL de sys.path ANTES de importar src._setup_paths
# (necesario porque src._setup_paths es lo que configura sys.path correctamente)
_root = Path(__file__).resolve().parent.parent  # server/dispatcher.py → show-director/
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Setup centralizado de sys.path (única fuente de verdad)
import src.mcp.mcp_bridge as bridge  # noqa: E402
from server.toggles import toggle_set_membership  # noqa: E402
from server.validators import ValidationError, require_int  # noqa: E402
from src._setup_paths import *
from src.log import get_logger

_log = get_logger(__name__)

# ── Desacople (B1) ───────────────────────────────────────────────────────────
# Antes aquí se parcheaba el módulo global `bridge._qt_call`/`_qt_call_dual`.
# Ahora la política headless vive en ShowSession (`_qt_call_impl` /
# `_qt_call_dual_impl`) y el bridge la detecta vía getattr sobre `app`. Esto
# elimina la mutación de estado global del módulo (más robusto y testeable).


# Métodos de debug que dependen de widgets Qt concretos (tabs, canvas): se
# excluyen del dispatcher web (no aplican sin la ventana PyQt5).
_EXCLUDED = {"debug_switch_tab", "debug_analyzer"}


# ── Handlers locales (web-only) — no existen en el bridge MCP ────────────────
# Operan directamente sobre el ShowSession. Tienen prioridad sobre HANDLERS.
def _h_set_loop(session, params):
    session.loop = bool(params.get("on", not session.loop))
    return {"ok": True, "loop": session.loop}


def _h_set_loop_range(session, params):
    """set_loop_range(start_ms, end_ms) | set_loop_range(clear=True) → {ok, loop_range}.

    D (Timeline v2): región de loop A/B. Runtime-only (no persiste). El tick
    hace wrap del reloj de audio al llegar a end_ms mientras suena.
    """
    if params.get("clear") or (params.get("start_ms") is None and params.get("end_ms") is None):
        session.loop_range = None
        return {"ok": True, "loop_range": None}
    try:
        start_ms = int(params["start_ms"])
        end_ms = int(params["end_ms"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "start_ms y end_ms enteros requeridos (o clear=true)"}
    dur_ms = int(session.duration * 1000)
    if start_ms < 0 or end_ms <= start_ms:
        return {"ok": False, "error": "rango inválido: 0 <= start_ms < end_ms"}
    if dur_ms > 0:
        end_ms = min(end_ms, dur_ms)
        if end_ms <= start_ms:
            return {"ok": False, "error": "rango fuera de la canción"}
    if end_ms - start_ms < 100:
        return {"ok": False, "error": "región demasiado corta (mínimo 100 ms)"}
    session.loop_range = (start_ms, end_ms)
    return {"ok": True, "loop_range": [start_ms, end_ms]}


def _h_set_rec(session, params):
    session.rec = bool(params.get("on", not session.rec))
    return {"ok": True, "rec": session.rec}


def _h_set_volume(session, params):
    session.audio.set_volume(float(params.get("value", 1.0)))
    return {"ok": True}


def _h_set_track_mute(session, params):
    try:
        track = require_int(params, "track")
        on = toggle_set_membership(session.muted_tracks, track, params.get("on"))
        session.notify_changed("tracks")
        return {"ok": True, "muted": sorted(session.muted_tracks)}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}


def _h_set_track_solo(session, params):
    try:
        track = require_int(params, "track")
        on = toggle_set_membership(session.solo_tracks, track, params.get("on"))
        session.notify_changed("tracks")
        return {"ok": True, "solo": sorted(session.solo_tracks)}
    except ValidationError as e:
        return {"ok": False, "error": str(e)}


def _h_get_tracks_state(session, params):
    return {"muted": sorted(session.muted_tracks), "solo": sorted(session.solo_tracks)}


def _h_undo(session, params):
    ok = session.undo()
    return {"ok": ok, "clip_count": len(session.timeline.clips)}


def _h_redo(session, params):
    ok = session.redo()
    return {"ok": ok, "clip_count": len(session.timeline.clips)}


# Métodos que mutan los clips del timeline → snapshot para undo
_TIMELINE_MUTATORS = {
    "add_clip", "delete_clip", "move_clip", "set_clip_color", "set_clip_params",
    "set_clip_mute", "set_clip_lock", "set_clip_scope",
    "add_channel_clip",
    "generate_section", "mirror_clips_lr", "apply_palette_to_range", "load_show",
    # A3 — mutadores de patterns/instances (el snapshot se hace dentro del handler,
    # no en el dispatcher, porque necesitan snapshotear ANTES de resolver lookup)
    # create_pattern_from_clips y los demás llaman session.snapshot() internamente.
}

# Métodos que mutan el rig de fixtures → regenerar rig_layout.json para el visor 3D
# (si no, el visor muestra posiciones obsoletas tras mover/editar fixtures en Patch).
_RIG_MUTATORS = {
    "set_fixture_property", "add_fixture", "delete_fixture",
    "save_rig", "load_show",
}


def _h_get_effect_schema(session, params):
    """get_effect_schema(effect_id) → {ok, schema: dict}
    Devuelve el PARAM_SCHEMA del efecto indicado. Schema vacío ({}) si no tiene."""
    try:
        effect_id = require_int(params, "effect_id", min_val=0)
    except ValidationError as e:
        return {"ok": False, "error": str(e)}
    lib = getattr(session, "library", None)
    effect = lib.get_effect(effect_id) if lib else None
    if effect is None:
        return {"ok": False, "error": f"effect_id {effect_id} no encontrado"}
    return {"ok": True, "schema": getattr(effect, "PARAM_SCHEMA", {})}


def _h_preview_effect_frame(session, params):
    """preview_effect_frame(effect_id, params={}, t_ms=0) → {ok, frame_b64: str}
    Renderiza un frame del efecto con los params dados y lo devuelve como PNG base64.
    Sin estado en la sesión, sin tocar el timeline. < 50 ms (síncrono OK).
    Fallback sin Pillow: devuelve el array raw como lista JSON."""
    try:
        effect_id = require_int(params, "effect_id", min_val=0)
    except ValidationError as e:
        return {"ok": False, "error": str(e)}

    lib = getattr(session, "library", None)
    effect = lib.get_effect(effect_id) if lib else None
    if effect is None:
        return {"ok": False, "error": f"effect_id {effect_id} no encontrado"}

    import numpy as np

    from src.core.effects_engine import LEDS_PER_BAR, NUM_BARS

    t_ms = float(params.get("t_ms", 0))
    effect_params = dict(params.get("params") or {})
    bars_state = np.zeros((NUM_BARS, LEDS_PER_BAR, 3), dtype=np.uint8)
    audio_ctx: dict = {}

    try:
        frame = effect.render(t_ms, bars_state, audio_ctx, **effect_params)
    except Exception as e:
        return {"ok": False, "error": f"render error: {e}"}

    # Normalizar shape a (rows, LEDS_PER_BAR, 3)
    if frame.ndim == 3 and frame.shape[0] == 1:
        img_arr = frame[0:1]   # PER_BAR → 1 fila
    else:
        img_arr = frame        # ALL_BARS → 10 filas

    import os as _os
    no_pillow = _os.environ.get("LUCES_NO_PILLOW") == "1"
    if no_pillow:
        return {"ok": True, "frame_raw": img_arr.tolist()}

    try:
        import base64
        import io

        from PIL import Image
        # Escalar 2× para visibilidad mínima
        scale = 2
        h, w = img_arr.shape[:2]
        pil = Image.fromarray(img_arr.astype(np.uint8), "RGB")
        pil = pil.resize((w * scale, h * scale), Image.NEAREST)
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {"ok": True, "frame_b64": b64, "width": w * scale, "height": h * scale}
    except ImportError:
        return {"ok": True, "frame_raw": img_arr.tolist()}


def _h_list_clips(session, params):
    """list_clips(filter?, offset?, limit?) → {ok, clips, total, next_offset?}

    H4: si hay > 1000 clips devuelve cursor (offset, limit) en vez de N clips
    en un solo JSON. offset y limit son enteros opcionales.
    filter: {track?, start_ms_min?, start_ms_max?}
    """
    flt = params.get("filter") or {}
    track_f = flt.get("track")
    t_lo = flt.get("start_ms_min")
    t_hi = flt.get("start_ms_max")

    clips = list(getattr(session, "timeline", None).clips
                 if getattr(session, "timeline", None) else [])

    if track_f is not None:
        clips = [c for c in clips if c.track == int(track_f)]
    if t_lo is not None:
        clips = [c for c in clips if c.start_ms >= int(t_lo)]
    if t_hi is not None:
        clips = [c for c in clips if c.start_ms <= int(t_hi)]

    total = len(clips)
    offset = int(params.get("offset", 0))
    limit_raw = params.get("limit")

    if limit_raw is not None:
        limit = int(limit_raw)
        page = clips[offset: offset + limit]
        next_offset = offset + limit if offset + limit < total else None
    else:
        page = clips[offset:]
        next_offset = None

    return {
        "ok": True,
        "clips": [c.to_dict() for c in page],
        "total": total,
        "count": total,       # alias para compat con test_dispatcher.py
        "next_offset": next_offset,
    }


_LOCAL = {
    # H4 — list_clips con paginación (offset/limit)
    "list_clips": _h_list_clips,
    "undo": _h_undo,
    "redo": _h_redo,
    "set_loop": _h_set_loop,
    "set_loop_range": _h_set_loop_range,
    "set_rec": _h_set_rec,
    "set_volume": _h_set_volume,
    "set_track_mute": _h_set_track_mute,
    "set_track_solo": _h_set_track_solo,
    "get_tracks_state": _h_get_tracks_state,
    # Heartbeat — keep-alive ligero (el frontend lo usa para detectar
    # conexiones medio-abiertas y forzar la reconexión).
    "ping": lambda session, params: {"ok": True},
    # F2 — Plugin UI auto-generada (ROADMAP v3)
    "get_effect_schema": _h_get_effect_schema,
    # F4 — Live preview en el inspector (ROADMAP v3)
    "preview_effect_frame": _h_preview_effect_frame,
    # L3 — Multiusuario: rol del token actual
    "auth_get_role": lambda session, params: {"ok": True, "role": "operator"},
}

# ── ADR-005: dominios extraídos a server/handlers/ ────────────────────────────
# Cada módulo de dominio define HANDLERS (+ mutadores propios); aquí se mergean.
from server import handlers as _handlers_pkg  # noqa: E402

_handlers_pkg.load_all()
_LOCAL.update(_handlers_pkg.LOCAL)
_TIMELINE_MUTATORS |= _handlers_pkg.TIMELINE_MUTATORS
_RIG_MUTATORS |= _handlers_pkg.RIG_MUTATORS

# Compat: tests y server/web.py importan estos nombres desde server.dispatcher.
from server.handlers.automation import (  # noqa: E402,F401
    _h_add_automation_lane,
    _h_delete_automation_lane,
    _h_list_automation_lanes,
    _h_list_modulation_sources,
    _h_set_automation_points,
    _h_set_clip_param_links,
)
from server.handlers.autosave import (  # noqa: E402,F401
    _h_discard_autosave_prompt,
    _h_list_autosaves,
    _h_restore_autosave,
)
from server.handlers.autovj import (  # noqa: E402,F401
    _h_autovj_activate_preset,
    _h_autovj_get_state,
    _h_autovj_load,
    _h_autovj_save,
    _h_autovj_set_ruleset,
    _h_autovj_update_rule,
    _h_live_input_get_state,
    _h_live_input_list_devices,
    _h_live_input_start,
    _h_live_input_stop,
)
from server.handlers.bundle_market import (  # noqa: E402,F401
    _h_export_show_bundle,
    _h_import_show_bundle,
    _h_install_plugin,
    _h_list_marketplace_plugins,
)
from server.handlers.clips_edit import (  # noqa: E402,F401
    _h_add_micro_event,
    _h_delete_micro_event,
    _h_delete_range,
    _h_duplicate_clip,
    _h_duplicate_range,
    _h_set_clip_effect,
    _h_set_clip_preset,
    _h_split_clip,
    _h_update_micro_event,
)
from server.handlers.cues import (  # noqa: E402,F401
    _h_add_cue,
    _h_delete_cue,
    _h_get_cue_state,
    _h_go_cue,
    _h_go_next_cue,
    _h_go_prev_cue,
    _h_list_cues,
    _h_reorder_cues,
    _h_update_cue,
)
from server.handlers.feedback import (  # noqa: E402,F401
    _h_add_feedback,
    _h_analyzer_waveform_peaks,
    _h_list_feedback,
)
from server.handlers.gdtf import (  # noqa: E402,F401
    _gdtf_cache,
    _gdtf_metadata,
    _h_add_fixture_from_gdtf,
    _h_list_gdtf_profiles,
)
from server.handlers.live import (  # noqa: E402,F401
    _h_get_live_state,
    _h_get_record_state,
    _h_live_assign_slot,
    _h_live_release,
    _h_live_stop_all,
    _h_live_trigger,
    _h_set_macro,
    _h_start_record,
    _h_stop_record,
)
from server.handlers.markers import (  # noqa: E402,F401
    _h_add_marker,
    _h_delete_marker,
    _h_get_group_clips,
    _h_list_markers,
    _h_update_marker,
)
from server.handlers.mixer import (  # noqa: E402,F401
    _h_get_mixer,
    _h_set_master,
    _h_set_track_chain,
)
from server.handlers.movers import (  # noqa: E402,F401
    _h_delete_clip_channel_effect,
    _h_get_fixture_pan_tilt,
    _h_list_channel_effects,
    _h_list_dmx_ports,
    _h_set_clip_channel_effect,
    _h_set_output_target,
)
from server.handlers.osc import (  # noqa: E402,F401
    _h_osc_get_state,
    _h_osc_set_config,
)
from server.handlers.output_test import (  # noqa: E402,F401
    _h_blackout,
    _h_chase_stop,
    _h_chase_test,
    _h_get_output_status,
    _h_identify_fixture,
    _h_test_universe,
)
from server.handlers.patch import (  # noqa: E402,F401
    _get_artnet_ip_for_universe,
    _h_duplicate_fixture,
    _h_get_fixture_detail,
    _h_get_output_targets,
    _h_get_universe_channel_map,
    _h_list_fixture_types,
    _h_next_free_address,
    _h_update_fixture,
    _update_rig_layout_height,
)
from server.handlers.patch_visual import (  # noqa: E402,F401
    _h_move_fixture,
    _h_set_fixture_type,
    _update_layout_floor,
)
from server.handlers.patterns import (  # noqa: E402,F401
    _h_add_pattern_instance,
    _h_create_pattern_from_clips,
    _h_delete_pattern,
    _h_delete_pattern_instance,
    _h_dissolve_instance,
    _h_list_pattern_instances,
    _h_list_patterns,
    _h_move_pattern_instance,
    _h_update_pattern,
)
from server.handlers.pixelmap import (  # noqa: E402,F401
    _h_set_clip_pixel_map,
)
from server.handlers.presets import (  # noqa: E402,F401
    _h_add_preset_clip,
    _h_create_preset,
    _h_delete_preset,
    _h_list_presets,
    _h_update_preset,
)
from server.handlers.projects import (  # noqa: E402,F401
    _h_apply_autovj,
    _h_apply_presets,
    _h_apply_rig,
    _h_apply_song,
    _h_create_project_from_components,
    _h_duplicate_project,
    _h_list_available_analyses,
    _h_list_components,
    _h_list_projects_detailed,
    _h_load_sequence,
    _h_update_project,
    _safe_project_slug,
)
from server.handlers.render_export import (  # noqa: E402,F401
    _h_export_csv,
    _h_export_dmx_csv,
    _h_export_patch_pdf,
    _h_export_qlc,
    _h_export_video,
    _h_get_render_status,
    _h_render_offline,
    _h_toggle_baked,
)
from server.handlers.showgen import (  # noqa: E402,F401
    _h_clear_gesture_history,
    _h_generate_show,
    _h_list_gesture_history,
    _h_replay_gesture,
)
from server.handlers.switch import (  # noqa: E402,F401
    _h_list_projects,
    _h_switch_project,
)
from server.handlers.tempo import (  # noqa: E402,F401
    _h_get_key_info,
    _h_tap_bpm,
    _h_tempo_sync_get_state,
    _h_tempo_sync_list_midi_ports,
    _h_tempo_sync_set_mode,
)
from server.handlers.viewer3d import (  # noqa: E402,F401
    _h_get_rig_layout,
    _h_set_fixture_3d,
)
from server.handlers.waveform import (  # noqa: E402,F401
    _compute_waveform,
    _ensure_waveform_cached,
    _h_get_waveform,
)
from server.handlers.webhooks_config import (  # noqa: E402,F401
    _h_webhook_get_config,
    _h_webhook_set_config,
)


class Dispatcher:
    """Procesa mensajes JSON-RPC contra un ShowSession."""

    def __init__(self, session):
        self.session = session

    @property
    def methods(self):
        return ([m for m in bridge.HANDLERS if m not in _EXCLUDED]
                + list(_LOCAL.keys()))

    def handle(self, msg: dict[str, Any], token: str = "") -> dict[str, Any]:
        """Procesa un mensaje JSON-RPC 2.0 completo y devuelve la respuesta."""
        import traceback
        method = msg.get("method")
        msg_id = msg.get("id")
        if method in _EXCLUDED:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601,
                              "message": f"Método no disponible en web: {method}"}}

        # L3: control de acceso por rol
        if method == "auth_get_role":
            from server.auth import role_for_token
            tokens_cfg = getattr(self.session, "_tokens_config", [])
            if not isinstance(tokens_cfg, list):
                tokens_cfg = []
            role = role_for_token(token, tokens_cfg)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"ok": True, "role": role}}

        from server.auth import check_permission
        tokens_cfg = getattr(self.session, "_tokens_config", [])
        if not isinstance(tokens_cfg, list):
            tokens_cfg = []
        perm = check_permission(token, method or "", tokens_cfg)
        if not perm["ok"]:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"ok": False, "error": perm["error"]}}
        # Snapshot para undo antes de mutar el timeline
        if method in _TIMELINE_MUTATORS:
            try:
                self.session.snapshot()
            except Exception:
                pass
        # Handlers locales (web-only) tienen prioridad
        params = msg.get("params") or {}
        if method in _LOCAL:
            try:
                import asyncio
                import concurrent.futures
                result = _LOCAL[method](self.session, params)
                # FIX 3: support async handlers (e.g. marketplace) without changing
                # the sync dispatcher contract — run in a thread when already in a loop
                if asyncio.iscoroutine(result):
                    try:
                        asyncio.get_running_loop()
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                            result = ex.submit(asyncio.run, result).result(timeout=30)
                    except RuntimeError:
                        result = asyncio.run(result)
                self._maybe_sync_rig(method)
                self._record_gesture(method, params)
                return {"jsonrpc": "2.0", "id": msg_id, "result": result}
            except Exception as e:
                return {"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32000, "message": str(e),
                                  "data": traceback.format_exc()}}
        resp = bridge._dispatch(self.session, msg)
        self._maybe_sync_rig(method)
        self._record_gesture(method, params)
        return resp

    def _record_gesture(self, method: str | None, params: dict) -> None:
        """M3: graba el gesto en el GestureLog de la sesión."""
        if not method:
            return
        gl = getattr(self.session, "_gesture_log", None)
        if gl is None:
            return
        t_ms = 0
        try:
            t_ms = self.session._current_t_ms()
        except Exception:
            pass
        gl.record(method, params, t_ms)

    def _maybe_sync_rig(self, method: str) -> None:
        """Tras mutar el rig, regenera rig_layout.json para que el visor 3D lo
        refleje al recargar (la tab del visor re-monta el iframe al volver a ella)."""
        if method in _RIG_MUTATORS:
            try:
                self.session.sync_rig_layout()
            except Exception:
                pass

    def call(self, method: str, params: dict | None = None) -> dict[str, Any]:
        """Atajo: invoca un método y devuelve el `result` (o lanza en error)."""
        resp = self.handle({"jsonrpc": "2.0", "id": 1,
                             "method": method, "params": params or {}})
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error'].get('message')}")
        return resp["result"]
