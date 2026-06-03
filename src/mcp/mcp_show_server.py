"""
mcp_show_server.py — MCP server estándar que envuelve mcp_bridge (JSON-RPC).

Se ejecuta como proceso aparte (Claude Code lo lanza por stdio).
Por cada tool invocada por Claude, abre una conexión WebSocket a
ws://127.0.0.1:9876 (donde dual_app.py corre el mcp_bridge) y reenvía
el JSON-RPC. Devuelve el resultado a Claude por MCP.

Lanzar manualmente para test:
    python mcp_show_server.py
"""
from __future__ import annotations
import asyncio
import json
import sys
from typing import Any, Dict, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Falta dependencia: pip install mcp", file=sys.stderr)
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("Falta dependencia: pip install websockets", file=sys.stderr)
    sys.exit(1)


BRIDGE_URL = "ws://127.0.0.1:9876"

mcp = FastMCP("show-control")


# ───────────────────────────────────────────────────────────────
# Cliente JSON-RPC a través de mcp_bridge
# ───────────────────────────────────────────────────────────────

async def _rpc(method: str, params: Optional[dict] = None) -> dict:
    """Envía una llamada JSON-RPC al bridge y devuelve el result/error."""
    if params is None:
        params = {}
    msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        async with websockets.connect(BRIDGE_URL, open_timeout=2,
                                       close_timeout=2) as ws:
            await ws.send(json.dumps(msg))
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            resp = json.loads(raw)
            if "error" in resp:
                return {"_error": resp["error"]}
            return resp.get("result", {})
    except (OSError, ConnectionRefusedError) as e:
        return {"_error": f"Bridge no conectado en {BRIDGE_URL}. "
                          f"¿Está dual_app.py corriendo? ({e})"}
    except asyncio.TimeoutError:
        return {"_error": "Timeout esperando respuesta del bridge"}
    except Exception as e:
        return {"_error": f"Error RPC: {e}"}


import threading as _threading

# Loop dedicado en thread aparte: evita "Cannot run the event loop while another
# loop is running" cuando FastMCP nos llama desde su propio event loop.
_bg_loop: Optional[asyncio.AbstractEventLoop] = None

def _ensure_bg_loop():
    global _bg_loop
    if _bg_loop is None:
        _bg_loop = asyncio.new_event_loop()
        t = _threading.Thread(target=_bg_loop.run_forever, daemon=True,
                              name="mcp_rpc_loop")
        t.start()
    return _bg_loop


def _sync_rpc(method: str, params: Optional[dict] = None) -> dict:
    """Wrapper sincrono: ejecuta _rpc en un thread/loop dedicado."""
    loop = _ensure_bg_loop()
    fut = asyncio.run_coroutine_threadsafe(_rpc(method, params), loop)
    try:
        return fut.result(timeout=10)
    except Exception as e:
        return {"_error": f"RPC timeout/error: {e}"}


# ───────────────────────────────────────────────────────────────
# Tools MCP — expuestas a Claude
# ───────────────────────────────────────────────────────────────

@mcp.tool()
def get_state() -> dict:
    """
    Devuelve el estado actual del show: tiempo de reproducción, si está
    reproduciéndose, sección actual, conteos de clips/cues/grupos.
    """
    return _sync_rpc("get_state")


@mcp.tool()
def play(start_sec: Optional[float] = None) -> dict:
    """
    Reproduce el audio del show. Si se pasa start_sec, salta a ese tiempo antes.
    """
    params = {}
    if start_sec is not None:
        params["start_sec"] = float(start_sec)
    return _sync_rpc("play", params)


@mcp.tool()
def pause() -> dict:
    """Pausa la reproducción manteniendo el cursor en su posición actual."""
    return _sync_rpc("pause")


@mcp.tool()
def stop() -> dict:
    """Detiene la reproducción y devuelve el cursor al inicio."""
    return _sync_rpc("stop")


@mcp.tool()
def seek(t_sec: float) -> dict:
    """Salta el cursor de reproducción a un tiempo concreto (en segundos)."""
    return _sync_rpc("seek", {"t_sec": float(t_sec)})


@mcp.tool()
def blackout() -> dict:
    """Apaga todas las barras enviando ceros por Art-Net (panic button)."""
    return _sync_rpc("set_blackout")


@mcp.tool()
def open_3d_viewer(url: str = "http://localhost:8080/") -> dict:
    """
    Abre el visualizador 3D del rig en el navegador (donde corre dual_app).
    El viewer muestra las barras LED iluminadas en tiempo real desde una
    escena Three.js con bloom y cámara orbital.
    """
    return _sync_rpc("open_3d_viewer", {"url": url})


# ─── Fixtures (Fase 3) ──────────────────────────────────────────

@mcp.tool()
def list_fixtures() -> dict:
    """
    Lista los fixtures del rig actual.
    Cada fixture incluye fixture_id, profile_id, universe, dmx_start,
    posición física (x, y, z), label y target_ip (si es WLED Art-Net directo).
    """
    return _sync_rpc("list_fixtures")


@mcp.tool()
def list_fixture_profiles() -> dict:
    """
    Lista los profiles disponibles (plantillas de tipos de fixture).
    Profiles actuales: wled_strip_93 (93 LEDs WLED), generic_mover_16ch
    (mover 16 canales con pan/tilt/RGB/gobo), dimmer_1ch.
    """
    return _sync_rpc("list_fixture_profiles")


@mcp.tool()
def save_rig(path: Optional[str] = None) -> dict:
    """
    Guarda el rig actual a fixtures.json (o al path indicado).
    El rig persistirá entre sesiones de la app.
    """
    params = {}
    if path is not None:
        params['path'] = path
    return _sync_rpc("save_rig", params)


@mcp.tool()
def add_fixture(fixture_id: str, profile_id: str, universe: int = 1,
                dmx_start: int = 1, position: Optional[list] = None,
                rotation: Optional[list] = None, label: str = "",
                target_ip: Optional[str] = None) -> dict:
    """
    Añade un fixture al rig.

    - fixture_id: identificador único (ej. 'mover_stage_L', 'dimmer_back_3')
    - profile_id: uno de los profiles disponibles (ver list_fixture_profiles)
    - universe: universo DMX (1-32768)
    - dmx_start: canal DMX inicial (1-512)
    - position: [x, y, z] en metros (Y=up, X=lateral, Z=profundidad)
    - rotation: [pan, tilt, roll] en grados
    - target_ip: IP del nodo Art-Net (solo si el fixture es Art-Net directo)
    """
    params = {
        "fixture_id": fixture_id, "profile_id": profile_id,
        "universe": universe, "dmx_start": dmx_start,
        "position": position or [0.0, 1.0, 0.0],
        "rotation": rotation or [0.0, 0.0, 0.0],
        "label": label or fixture_id,
    }
    if target_ip is not None: params["target_ip"] = target_ip
    return _sync_rpc("add_fixture", params)


@mcp.tool()
def delete_fixture(fixture_id: str) -> dict:
    """Borra un fixture del rig por su id."""
    return _sync_rpc("delete_fixture", {"fixture_id": fixture_id})


@mcp.tool()
def move_fixture(fixture_id: str, position: Optional[list] = None,
                 rotation: Optional[list] = None) -> dict:
    """
    Mueve un fixture cambiando su posición (x,y,z metros) y/o rotación
    (pan,tilt,roll grados).
    """
    params: Dict[str, Any] = {"fixture_id": fixture_id}
    if position is not None: params["position"] = position
    if rotation is not None: params["rotation"] = rotation
    return _sync_rpc("move_fixture", params)


@mcp.tool()
def set_fixture_property(fixture_id: str, key: str, value) -> dict:
    """
    Cambia un campo simple del fixture.
    Keys permitidas: 'label', 'universe', 'dmx_start', 'profile_id',
    'target_ip', 'legacy_bar_idx'.
    """
    return _sync_rpc("set_fixture_property", {
        "fixture_id": fixture_id, "key": key, "value": value
    })


@mcp.tool()
def set_fixture_channel(fixture_id: str, channel_name: str,
                         value: Optional[float] = None) -> dict:
    """
    Override manual de un canal DMX de un fixture (0..1 normalizado).
    El override pisa lo que generen los clips channel-level. El viewer 3D
    lo refleja en el siguiente tick (movers giran, cambian color, etc.).

    Args:
      fixture_id: id del fixture (e.g. "mover_wash_L_back")
      channel_name: nombre canónico del canal ('pan', 'tilt', 'dim',
                    'r', 'g', 'b', 'shutter', etc.) — debe existir en el
                    profile.channel_map.
      value: 0.0..1.0  (None / "auto" para limpiar override y volver a auto)

    Returns: {"ok": True, "fixture_id": ..., "manual_channels": {...}}
    """
    return _sync_rpc("set_fixture_channel", {
        "fixture_id": fixture_id,
        "channel_name": channel_name,
        "value": value,
    })


# ─── Channel Effects (Fase 7 v1.7) ─────────────────────────────


@mcp.tool()
def list_channel_effects(category: Optional[str] = None,
                         fixture_id: Optional[str] = None) -> dict:
    """
    Lista los ChannelEffect disponibles para fixtures no-LED.

    Args:
      category: filtra por categoría: 'position', 'color', 'intensity',
                'optical' o 'strobe'. Si None, devuelve todos.
      fixture_id: si se da, devuelve solo efectos compatibles con ese fixture
                  (cuyas required_channels están en el profile del fixture).

    Returns: {"effects": [{effect_id, name, category, required_channels,
                           optional_channels, default_params}, ...]}
    """
    p: dict = {}
    if category:   p["category"]   = category
    if fixture_id: p["fixture_id"] = fixture_id
    return _sync_rpc("list_channel_effects", p)


@mcp.tool()
def add_channel_clip(fixture_id: str, channel_effect_id: str,
                     start_ms: int, duration_ms: int,
                     layer: int = 0,
                     clip_params: Optional[dict] = None) -> dict:
    """
    Añade un clip de canal (category != 'pixel') al timeline para un fixture.

    El clip queda asociado al fixture vía scope='fixture:<fixture_id>' y
    el ShowEngine lo aplica en tiempo real con layer-mixing (LTP).

    Args:
      fixture_id: id del fixture (e.g. 'mover_wash_L_back')
      channel_effect_id: id del ChannelEffect (e.g. 'pos_circle', 'col_rainbow').
                         Usa list_channel_effects para ver disponibles.
      start_ms: inicio del clip en ms
      duration_ms: duración del clip en ms
      layer: capa (0=base, mayor pisa). Default 0.
      clip_params: dict con parámetros del efecto (speed, radius, color, etc.).
                   Los no especificados usan default_params del efecto.

    Returns: {"ok": True, "clip": {...}}
    """
    return _sync_rpc("add_channel_clip", {
        "fixture_id": fixture_id,
        "channel_effect_id": channel_effect_id,
        "start_ms": start_ms,
        "duration_ms": duration_ms,
        "layer": layer,
        "clip_params": clip_params or {},
    })


@mcp.tool()
def get_dmx_universe(universe_id: int,
                     format: str = "int_list") -> dict:
    """
    Devuelve el último estado DMX ensamblado de un universo.

    Útil para debug, verificar valores de canal, o exportar estado.
    Solo funciona para universos con target sim_only (u otros que guarden
    el último estado). Para WLED el dato viaja directo por UDP.

    Args:
      universe_id: número de universo (1-based)
      format: 'int_list' → lista de 512 enteros 0-255 (default)
              'hex'      → string hexadecimal de 1024 caracteres

    Returns: {"universe": N, "data": [...] o "AABB...", "format": "..."}
    """
    return _sync_rpc("get_dmx_universe", {
        "universe_id": universe_id,
        "format": format,
    })


@mcp.tool()
def apply_channel_preset(fixture_id: str, preset: dict) -> dict:
    """
    Aplica un preset de canales manuales a un fixture (override inmediato).

    Los valores se guardan en Fixture.manual_channels y el viewer 3D los
    refleja en el siguiente tick. Para limpiar un canal específico usa
    set_fixture_channel(fixture_id, channel_name, value=None).

    Args:
      fixture_id: id del fixture (e.g. 'mover_wash_L_back')
      preset: dict {channel_name: 0.0..1.0}
              Ejemplo: {'pan': 0.5, 'tilt': 0.3, 'dim': 1.0, 'r': 1.0}

    Returns: {"ok": True, "applied": {...}, "skipped": {...}}
    """
    return _sync_rpc("apply_channel_preset", {
        "fixture_id": fixture_id,
        "preset": preset,
    })


@mcp.tool()
def generate_section(
    effect_id: int,
    trigger: str = "on_beat",
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
    section_name: Optional[str] = None,
    scope: str = "per_bar",
    track: int = 0,
    layer: int = 0,
    clip_duration_ms: Optional[int] = None,
    spacing_ms: int = 0,
    color: str = "#3a7acc",
    clip_params: Optional[dict] = None,
    max_clips: int = 200,
    dry_run: bool = False,
) -> dict:
    """Genera clips de pixel en una sección del timeline sincronizados con eventos de audio.

    Usa el análisis de audio para colocar clips automáticamente en posiciones
    rítmicamente relevantes (beats, kicks, drops, etc.).

    Args:
      effect_id: ID del efecto pixel (0..50). Ver list_effects().
      trigger: Cuándo colocar clips. Opciones:
               "on_beat"      — en cada beat de la sección
               "on_downbeat"  — en cada downbeat (tiempo fuerte)
               "on_kick"      — en cada kick detectado
               "on_snare"     — en cada snare detectado
               "on_drop"      — en los drops de energía
               "fill"         — un solo clip que rellena toda la sección
               "every_500ms"  — cada N milisegundos (ej. every_250ms)
      start_sec / end_sec: Rango temporal en segundos.
      section_name: Alternativa a start/end — nombre o tipo de sección ("chorus", "drop", etc.)
      scope: "per_bar" | "all_bars" | "bar:N" | "group:id"
      track: Pista (0..9)
      layer: Capa de mezcla (mayor = prioridad más alta)
      clip_duration_ms: Duración de cada clip. Si None, usa la del efecto.
      spacing_ms: Mínimo espacio en ms entre clips consecutivos.
      color: Color hex del clip en el timeline (visual only).
      clip_params: Dict de parámetros del efecto (ej. {"hue": 120, "speed": 2.0}).
      max_clips: Límite de seguridad (evitar generar miles de clips).
      dry_run: Si True, retorna la preview sin añadir nada al timeline.

    Returns: {"ok": True, "count": N, "clips": [...]}
    """
    return _sync_rpc("generate_section", {
        "effect_id": effect_id,
        "trigger": trigger,
        "start_sec": start_sec,
        "end_sec": end_sec,
        "section_name": section_name,
        "scope": scope,
        "track": track,
        "layer": layer,
        "clip_duration_ms": clip_duration_ms,
        "spacing_ms": spacing_ms,
        "color": color,
        "clip_params": clip_params or {},
        "max_clips": max_clips,
        "dry_run": dry_run,
    })


@mcp.tool()
def mirror_clips_lr(
    start_ms: int,
    end_ms: Optional[int] = None,
    track: Optional[int] = None,
    layer_offset: int = 1,
    color: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Espeja clips bar:N → bar:(9-N) para crear simetría lateral.

    Busca clips con scope "bar:N" en el rango indicado y crea clips
    simétricos en la barra opuesta (bar 0 ↔ bar 9, bar 1 ↔ bar 8, etc.).
    Útil para crear efectos simétricos después de generar clips en un lado.

    Args:
      start_ms: Inicio del rango en ms.
      end_ms: Fin del rango en ms. None = hasta el final del show.
      track: Filtrar por pista. None = todas las pistas.
      layer_offset: Capa adicional para los clips espejo (default 1).
      color: Color hex para los espejo. None = mismo color que el original.
      dry_run: Si True, retorna preview sin añadir clips.

    Returns: {"ok": True, "count": N, "clips": [...]}
    """
    return _sync_rpc("mirror_clips_lr", {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "track": track,
        "layer_offset": layer_offset,
        "color": color,
        "dry_run": dry_run,
    })


@mcp.tool()
def apply_palette_to_range(
    palette: str,
    start_ms: int = 0,
    end_ms: Optional[int] = None,
    track: Optional[int] = None,
    mode: str = "cycle",
) -> dict:
    """Aplica una paleta de colores (parámetro 'hue') a los clips de un rango.

    Útil para dar coherencia cromática a una sección del show después
    de generar clips con generate_section.

    Args:
      palette: Nombre de paleta predefinida o lista JSON de hues (0-360).
               Paletas disponibles: warm, cool, fire, ocean, rainbow, purple, neon, mono.
               O bien pasar lista directamente, ej. "[0, 60, 120, 240]".
      start_ms: Inicio del rango en ms.
      end_ms: Fin del rango en ms. None = hasta el final.
      track: Filtrar por pista. None = todas las pistas.
      mode: Cómo asignar hues a clips:
            "cycle"    — cicla por la paleta en orden
            "random"   — asignación aleatoria de la paleta
            "gradient" — interpola linealmente entre el primer y último hue

    Returns: {"ok": True, "count": N, "updates": [{clip_id, hue}, ...]}
    """
    import json as _json
    # Intentar parsear si es JSON list string
    parsed_palette = palette
    try:
        if palette.startswith("["):
            parsed_palette = _json.loads(palette)
    except Exception:
        pass
    return _sync_rpc("apply_palette_to_range", {
        "palette": parsed_palette,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "track": track,
        "mode": mode,
    })


@mcp.tool()
def list_clips(track: Optional[int] = None,
               scope: Optional[str] = None,
               start_ms_min: Optional[int] = None,
               start_ms_max: Optional[int] = None) -> dict:
    """
    Lista clips del timeline. Filtra opcionalmente por track, scope o rango temporal.
    Cada clip incluye: id, track, start_ms, end_ms, effect_id, scope, color, layer.
    """
    flt = {}
    if track is not None: flt["track"] = track
    if scope is not None: flt["scope"] = scope
    if start_ms_min is not None: flt["start_ms_min"] = start_ms_min
    if start_ms_max is not None: flt["start_ms_max"] = start_ms_max
    return _sync_rpc("list_clips", {"filter": flt})


@mcp.tool()
def get_active_clips(t_sec: Optional[float] = None) -> dict:
    """
    Devuelve los clips activos en un tiempo dado (el que está sonando ahora
    si no se especifica).
    """
    params = {}
    if t_sec is not None:
        params["t_sec"] = float(t_sec)
    return _sync_rpc("get_active_clips", params)


@mcp.tool()
def list_cue_points() -> dict:
    """Lista los 9 cue points (Performance Mode) y cuáles están asignados."""
    return _sync_rpc("list_cue_points")


@mcp.tool()
def set_cue(slot: int, t_sec: Optional[float] = None,
            name: Optional[str] = None) -> dict:
    """
    Asigna un cue point: slot 1..9 al tiempo dado (o al actual si no se da).
    Opcionalmente con nombre descriptivo (ej. "DROP 1").
    """
    params = {"slot": int(slot)}
    if t_sec is not None: params["t_sec"] = float(t_sec)
    if name is not None: params["name"] = name
    return _sync_rpc("set_cue", params)


@mcp.tool()
def trigger_cue(slot: int) -> dict:
    """Dispara un cue (slot 1..9): salta al tiempo y empieza a reproducir."""
    return _sync_rpc("trigger_cue", {"slot": int(slot)})


@mcp.tool()
def clear_cue(slot: int) -> dict:
    """Borra el cue del slot indicado."""
    return _sync_rpc("clear_cue", {"slot": int(slot)})


@mcp.tool()
def list_groups() -> dict:
    """
    Lista los grupos de barras (IZQ, DER, EXTREMOS, CENTRO, PARES, IMPARES)
    y group_sets (TODO, BORDES+CENTRO).
    """
    return _sync_rpc("list_groups")


@mcp.tool()
def list_effects() -> dict:
    """
    Lista los 51 efectos disponibles con id, name, family, duration_ms,
    scope y descripción.
    """
    return _sync_rpc("list_effects")


@mcp.tool()
def save_show(path: Optional[str] = None) -> dict:
    """
    Guarda el timeline actual. Si no se pasa path, guarda en show_timeline.json
    por defecto.
    """
    params = {}
    if path is not None:
        params["path"] = path
    return _sync_rpc("save_show", params)


@mcp.tool()
def load_show(path: str) -> dict:
    """Carga un show desde un archivo JSON (sustituye el actual)."""
    return _sync_rpc("load_show", {"path": path})


@mcp.tool()
def list_saved_shows() -> dict:
    """Lista shows guardados en la carpeta shows_saved/."""
    return _sync_rpc("list_saved_shows")


# ─── Clip write operations ──────────────────────────────────────

@mcp.tool()
def add_clip(track: int, start_ms: int, end_ms: int, effect_id: int,
             scope: str = "per_bar", color: str = "#3a7acc",
             layer: int = 0, label: str = "") -> dict:
    """
    Añade un clip al timeline.

    - track: 0-9 para barras físicas; ignorado si scope es group:X/global
    - start_ms / end_ms: posición temporal del clip en milisegundos
    - effect_id: 0-50 (ver list_effects)
    - scope: 'per_bar' | 'global' | 'group:NOMBRE' | 'group_set:NOMBRE'
    - color: hex string
    - layer: 0=base, 1=overlay, 2=...
    """
    return _sync_rpc("add_clip", {
        "track": track, "start_ms": start_ms, "end_ms": end_ms,
        "effect_id": effect_id, "scope": scope, "color": color,
        "layer": layer, "label": label,
    })


@mcp.tool()
def delete_clip(clip_id: int) -> dict:
    """Borra un clip por su id (id(clip) entero). Devuelve error si está locked."""
    return _sync_rpc("delete_clip", {"clip_id": clip_id})


@mcp.tool()
def move_clip(clip_id: int, new_start_ms: Optional[int] = None,
              new_end_ms: Optional[int] = None,
              new_track: Optional[int] = None) -> dict:
    """
    Mueve/redimensiona un clip.
    Si solo se da new_start_ms, mantiene la duración.
    """
    params: Dict[str, Any] = {"clip_id": clip_id}
    if new_start_ms is not None: params["new_start_ms"] = new_start_ms
    if new_end_ms is not None: params["new_end_ms"] = new_end_ms
    if new_track is not None: params["new_track"] = new_track
    return _sync_rpc("move_clip", params)


@mcp.tool()
def set_clip_color(clip_id: int, color: str) -> dict:
    """Cambia el color de un clip (hex string ej '#ff4040')."""
    return _sync_rpc("set_clip_color", {"clip_id": clip_id, "color": color})


@mcp.tool()
def set_clip_params(clip_id: int, params: dict) -> dict:
    """
    Actualiza parámetros del efecto del clip (hue, saturation, speed, etc.).
    Solo merge: los keys no incluidos se mantienen.
    """
    return _sync_rpc("set_clip_params", {"clip_id": clip_id, "params": params})


@mcp.tool()
def set_clip_mute(clip_id: int, muted: bool) -> dict:
    """Activa/desactiva el mute individual de un clip."""
    return _sync_rpc("set_clip_mute", {"clip_id": clip_id, "muted": muted})


@mcp.tool()
def set_clip_lock(clip_id: int, locked: bool) -> dict:
    """Bloquea/desbloquea un clip (los bloqueados no se mueven ni borran)."""
    return _sync_rpc("set_clip_lock", {"clip_id": clip_id, "locked": locked})


@mcp.tool()
def set_clip_scope(clip_id: int, scope: str) -> dict:
    """
    Cambia el scope de un clip.
    Valores: 'per_bar', 'global', 'group:IZQ', 'group_set:TODO', etc.
    """
    return _sync_rpc("set_clip_scope", {"clip_id": clip_id, "scope": scope})


# ─── Group write operations ─────────────────────────────────────

@mcp.tool()
def add_group(name: str, bars: Optional[list] = None,
              subgroups: Optional[list] = None, color: str = "#888888") -> dict:
    """
    Crea un nuevo grupo de barras.
    - bars: lista de índices de barra (0-9)
    - subgroups: lista de nombres de otros grupos (para crear group_sets)
    """
    return _sync_rpc("add_group", {
        "name": name,
        "bars": bars or [],
        "subgroups": subgroups or [],
        "color": color,
    })


@mcp.tool()
def delete_group(name: str) -> dict:
    """Borra un grupo por nombre."""
    return _sync_rpc("delete_group", {"name": name})


@mcp.tool()
def set_group_bars(name: str, bars: Optional[list] = None,
                   subgroups: Optional[list] = None,
                   color: Optional[str] = None) -> dict:
    """Modifica las barras / subgrupos / color de un grupo existente."""
    params: Dict[str, Any] = {"name": name}
    if bars is not None: params["bars"] = bars
    if subgroups is not None: params["subgroups"] = subgroups
    if color is not None: params["color"] = color
    return _sync_rpc("set_group_bars", params)


# ─── Cues ───────────────────────────────────────────────────────

@mcp.tool()
def rename_cue(slot: int, name: str) -> dict:
    """Renombra un cue point."""
    return _sync_rpc("rename_cue", {"slot": slot, "name": name})


# ─── Markers ────────────────────────────────────────────────────

@mcp.tool()
def list_markers() -> dict:
    """Lista los time markers nombrables del timeline."""
    return _sync_rpc("list_markers")


@mcp.tool()
def add_marker(t_sec: float, name: str = "Marker",
               color: str = "#ff9933") -> dict:
    """Añade un time marker en un instante con nombre."""
    return _sync_rpc("add_marker", {
        "t_sec": t_sec, "name": name, "color": color
    })


@mcp.tool()
def delete_marker(time_ms: int) -> dict:
    """Borra el marker con ese time_ms exacto."""
    return _sync_rpc("delete_marker", {"time_ms": time_ms})


# ───────────────────────────────────────────────────────────────
# Analyzer (Fase B v1.6) — tools de razonamiento musical para Claude
# ───────────────────────────────────────────────────────────────

@mcp.tool()
def analyzer_summary() -> dict:
    """
    Resumen del análisis musical de la canción actualmente cargada en el
    show: BPM, tonalidad, duración, número de secciones, qué piezas del
    análisis avanzado están disponibles (stems, piano_roll, lyrics).

    Úsalo como primera llamada para entender qué canción estás manipulando
    y qué heurísticas tienen sentido.
    """
    return _sync_rpc("analyzer_summary")


@mcp.tool()
def analyzer_list_sections(with_curated: bool = True) -> dict:
    """
    Lista las secciones detectadas en el audio (intro, verso, drop, etc).
    Cada sección tiene idx, start, end, energy, label automático.
    Si with_curated=True (default), incluye el nombre y tipo curado por
    el humano (drop/verse/chorus/...) cuando esté etiquetado.
    """
    return _sync_rpc("analyzer_list_sections", {"with_curated": with_curated})


@mcp.tool()
def analyzer_list_beats(start_sec: float = 0.0,
                        end_sec: Optional[float] = None) -> dict:
    """
    Tiempos (segundos) de los beats detectados en el rango [start_sec, end_sec].
    Útil para alinear clips exactamente con el ritmo. Si end_sec es None,
    devuelve todos a partir de start_sec.
    """
    params = {"start_sec": start_sec}
    if end_sec is not None:
        params["end_sec"] = end_sec
    return _sync_rpc("analyzer_list_beats", params)


@mcp.tool()
def analyzer_list_downbeats(start_sec: float = 0.0,
                            end_sec: Optional[float] = None) -> dict:
    """
    Tiempos (segundos) de los downbeats (primer beat de cada compás).
    Devuelve también `source`: 'madmom' (real), 'fallback_4_4' (asumido 4/4
    desde beats_librosa), o 'none' (no disponibles).
    Útil para colocar transiciones de sección.
    """
    params = {"start_sec": start_sec}
    if end_sec is not None:
        params["end_sec"] = end_sec
    return _sync_rpc("analyzer_list_downbeats", params)


@mcp.tool()
def analyzer_list_events(kind: str,
                         start_sec: float = 0.0,
                         end_sec: Optional[float] = None) -> dict:
    """
    Eventos musicales detectados de un tipo concreto. Respeta la curación:
    excluye los marcados como disabled e incluye los manuales añadidos.

    `kind` admite:
      - Percusivos: 'kick', 'snare', 'hat'
      - Bandas de frecuencia: 'sub', 'bass', 'low_mid', 'mid', 'high_mid',
        'presence', 'brilliance', 'air'
      - Harmónicos: 'bass_notes', 'mids', 'highs'
      - Onsets: 'onsets_all', 'onsets_percussive', 'onsets_harmonic'

    Cada evento tiene time_sec, kind, source ('auto'|'manual') y opcional
    end_sec/name.
    """
    params = {"kind": kind, "start_sec": start_sec}
    if end_sec is not None:
        params["end_sec"] = end_sec
    return _sync_rpc("analyzer_list_events", params)


@mcp.tool()
def analyzer_get_features_at(time_sec: float,
                             names: Optional[list] = None) -> dict:
    """
    Features de audio interpolados a un instante concreto. Devuelve un dict
    con las features pedidas.

    `names` admite (omitir para todos los 1D):
      - 1D: 'rms', 'rms_db', 'centroid', 'rolloff', 'flux', 'zcr',
            'bandwidth', 'flatness'
      - 2D (devuelve list): 'mfcc' (13), 'chroma' (12), 'tonnetz' (6),
            'contrast' (7), 'mel_bands' (8)
    """
    params = {"time_sec": time_sec}
    if names is not None:
        params["names"] = names
    return _sync_rpc("analyzer_get_features_at", params)


@mcp.tool()
def analyzer_get_features_range(start_sec: float,
                                end_sec: float,
                                downsample_to: Optional[int] = None,
                                names: Optional[list] = None) -> dict:
    """
    Series temporales de features en un rango. Si `downsample_to` está dado
    (ej. 200), decima para que no devuelva miles de puntos.

    Devuelve {times: [...], features: {name: [...] o [[...]]}}.
    """
    params = {"start_sec": start_sec, "end_sec": end_sec}
    if downsample_to is not None:
        params["downsample_to"] = downsample_to
    if names is not None:
        params["names"] = names
    return _sync_rpc("analyzer_get_features_range", params)


@mcp.tool()
def analyzer_find_drops(min_energy_jump: float = 0.4) -> dict:
    """
    Heurística para detectar drops: secciones cuya energía sube
    `min_energy_jump` (ratio) respecto a la anterior. Útil para alinear
    flashes/explosiones de luz con el momento del drop.

    Cada drop tiene idx, start, end, energy, energy_jump_ratio, y
    curated_name/curated_type si la sección está etiquetada.
    """
    return _sync_rpc("analyzer_find_drops",
                     {"min_energy_jump": min_energy_jump})


@mcp.tool()
def analyzer_find_breakdowns(min_low_energy_sec: float = 4.0) -> dict:
    """
    Heurística para detectar breakdowns: secciones largas (≥
    `min_low_energy_sec`) con energía < 60% del promedio del show.
    Útil para programar momentos calmados.
    """
    return _sync_rpc("analyzer_find_breakdowns",
                     {"min_low_energy_sec": min_low_energy_sec})


@mcp.tool()
def analyzer_list_stems_events(stem: str = "drums") -> dict:
    """
    Si demucs procesó la canción, devuelve onsets y regiones activas del
    stem indicado: 'drums', 'vocals', 'bass', 'other'.

    Si no hay stems, devuelve {available: False}.
    """
    return _sync_rpc("analyzer_list_stems_events", {"stem": stem})


# ── Curación (writes) ───────────────────────────────────────────

@mcp.tool()
def analyzer_set_section_label(idx: int, name: str = "", type: str = "") -> dict:
    """
    Etiqueta una sección con nombre humano + tipo. Persiste en curation.json
    aparte del análisis crudo, así que re-analizar no lo pisa.

    `type` admite vocabulario: intro, verse, chorus, drop, breakdown,
    buildup, bridge, outro, silence — o cualquier string libre.

    Llamar con name="" y type="" elimina la etiqueta.
    """
    return _sync_rpc("analyzer_set_section_label",
                     {"idx": idx, "name": name, "type": type})


@mcp.tool()
def analyzer_add_manual_event(time_sec: float, kind: str,
                              name: str = "") -> dict:
    """
    Añade un evento manual al análisis (kick que el detector se saltó, etc).
    Persiste en curation.json. Aparecerá en `analyzer_list_events(kind)`.
    """
    return _sync_rpc("analyzer_add_manual_event",
                     {"time_sec": time_sec, "kind": kind, "name": name})


@mcp.tool()
def analyzer_disable_event(time_sec: float, kind: str,
                           tolerance_ms: int = 20) -> dict:
    """
    Marca como deshabilitado un evento detectado cercano a `time_sec`
    (dentro de `tolerance_ms`). Útil para suprimir falsos positivos del
    detector. Persiste en curation.json — no destructivo.
    """
    return _sync_rpc("analyzer_disable_event",
                     {"time_sec": time_sec, "kind": kind,
                      "tolerance_ms": tolerance_ms})


@mcp.tool()
def analyzer_set_event_threshold(kind: str, value: float) -> dict:
    """
    Override del umbral de detección de una banda/tipo (kick/snare/hat...).
    Persiste en curation.json para que futuras re-detecciones lo apliquen.
    """
    return _sync_rpc("analyzer_set_event_threshold",
                     {"kind": kind, "value": value})


# ───────────────────────────────────────────────────────────────
# Resource: estado completo del show (para que Claude lea sin tool call)
# ───────────────────────────────────────────────────────────────

@mcp.resource("show://state")
def show_state_resource() -> str:
    """Snapshot del estado del show en JSON."""
    state = _sync_rpc("get_state")
    return json.dumps(state, indent=2, ensure_ascii=False)


# ───────────────────────────────────────────────────────────────
# Main: stdio MCP server
# ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
