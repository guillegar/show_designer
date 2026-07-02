"""
loaders/gdtf_profile.py — Importa fixtures GDTF (.gdtf) al modelo interno
de Show Designer Pro.

GDTF (General Device Type Format, https://gdtf-share.com/) es el estándar
de la industria. Cada .gdtf es un ZIP con un description.xml + opcionalmente
modelos 3D (.glb) + imágenes de gobos.

Este loader implementa SOLO el subset que necesitamos:
  - DmxModes      → elegir el modo (por nombre o el primero)
  - DmxChannels   → mapear cada canal a un offset 0-based
  - Attributes    → mapear el atributo GDTF a un nombre canónico nuestro
                    (Pan→pan, Dimmer→dim, ColorAdd_R→r, etc.)
  - Metadata      → max pan/tilt grados si están en el spec del fixture

No soportamos (por ahora):
  - Modelos 3D embebidos (el viewer 3D usa nuestra mesh genérica)
  - PhysicalDescriptions complejas (color profiles, dmx profiles)
  - Macros, Wheels detalladas, Relations

Uso:
    profile = load_gdtf_profile(Path("profiles/robe_pointe.gdtf"))
    profile = load_gdtf_profile(Path("profiles/robe_pointe.gdtf"),
                                mode_name="Mode 1, Standard")
"""
from __future__ import annotations

from pathlib import Path

import pygdtf

from src.core.fixtures import FixtureProfile

# ────────────────────────────────────────────────────────────────
# Mapeo de atributos GDTF (estándar oficial) → nombres canónicos
# ────────────────────────────────────────────────────────────────
#
# GDTF tiene atributos canónicos definidos en el spec; los más comunes son:
#   Pan, Tilt, Dimmer, Shutter1, ColorAdd_{R,G,B,C,M,Y,W}, Color1, Gobo1,
#   Gobo1Pos, Prism1, Prism1Pos, Focus1, Zoom1, Frost1, Function, Control,
#   ColorMacro1, StrobeFrequency, StrobeDuration, AnimationWheel1, etc.

GDTF_ATTR_TO_CANONICAL: dict[str, str] = {
    # Movimiento
    "Pan": "pan",
    "Tilt": "tilt",
    # Intensidad
    "Dimmer": "dim",
    "Shutter1": "shutter",
    # RGB(W)CMY aditivo
    "ColorAdd_R": "r",
    "ColorAdd_G": "g",
    "ColorAdd_B": "b",
    "ColorAdd_W": "w",
    "ColorAdd_C": "c",
    "ColorAdd_M": "m",
    "ColorAdd_Y": "y",
    "ColorAdd_RY": "amber",      # ámbar a veces
    "ColorAdd_UV": "uv",
    # Color wheel (rueda con colores discretos)
    "Color1": "color_wheel",
    "ColorMacro1": "color_macro",
    # Gobos
    "Gobo1": "gobo_wheel",
    "Gobo1Pos": "gobo_rot",
    "Gobo2": "gobo_wheel2",
    "Gobo2Pos": "gobo_rot2",
    # Óptica
    "Prism1": "prism",
    "Prism1Pos": "prism_rot",
    "Focus1": "focus",
    "Zoom1": "zoom",
    "Frost1": "frost",
    "Iris1": "iris",
    # Strobe
    "StrobeFrequency": "strobe_freq",
    "StrobeDuration": "strobe_duration",
    "StrobePulse": "strobe",
    # Control / Misc
    "Function": "macro",
    "Control": "reset",
    "AnimationWheel1": "animation",
    "AnimationWheel1Pos": "animation_pos",
    # Pan/Tilt speed (algunos fixtures lo tienen separado)
    "PanTiltSpeed": "speed",
    "Speed1": "speed",
}


def _canonical_name(gdtf_attr_name: str) -> str:
    """Devuelve el nombre canónico para un atributo GDTF. Si no está en el
    mapa, devuelve el nombre GDTF original en minúsculas para que el
    sistema lo soporte como string libre."""
    if not gdtf_attr_name:
        return ""
    if gdtf_attr_name in GDTF_ATTR_TO_CANONICAL:
        return GDTF_ATTR_TO_CANONICAL[gdtf_attr_name]
    # Fallback: lowercased GDTF attr
    return gdtf_attr_name.lower()


def _guess_kind(channel_map: dict[str, int]) -> str:
    """Adivina el kind del fixture según los canales presentes.

    Reglas simples:
      • pan AND tilt + RGB/W + gobo/prism → 'beam'
      • pan AND tilt + RGB/W (sin gobo)   → 'wash'
      • pan AND tilt (sin RGB) o solo gobo → 'moving_head'
      • solo dim/shutter/strobe_freq      → 'strobe'
      • solo dim                          → 'dimmer'
      • otherwise                         → 'moving_head' como genérico
    """
    has_pt = "pan" in channel_map and "tilt" in channel_map
    has_rgb = all(c in channel_map for c in ("r", "g", "b"))
    has_gobo = "gobo_wheel" in channel_map
    has_prism = "prism" in channel_map
    has_strobe = any(k in channel_map for k in ("strobe", "strobe_freq", "strobe_duration"))
    has_dim = "dim" in channel_map

    if has_pt:
        if has_gobo or has_prism:
            return "beam"
        if has_rgb:
            return "wash"
        return "moving_head"
    if has_strobe and not has_pt:
        return "strobe"
    if has_dim and len(channel_map) <= 2:
        return "dimmer"
    return "moving_head"


def load_gdtf_profile(
    gdtf_path: Path,
    mode_name: str | None = None,
    profile_id: str | None = None,
) -> FixtureProfile:
    """Carga un fixture GDTF y devuelve un FixtureProfile.

    Args:
        gdtf_path: ruta al fichero .gdtf
        mode_name: nombre del modo DMX a usar. Si None, usa el primero
                   definido en el fixture.
        profile_id: id a asignar al profile. Si None, usa el stem del
                    nombre de fichero (sin .gdtf).
    """
    gdtf_path = Path(gdtf_path)
    if not gdtf_path.is_file():
        raise FileNotFoundError(f"No existe {gdtf_path}")

    ft = pygdtf.FixtureType(path=str(gdtf_path))

    # Seleccionar el modo
    modes = list(ft.dmx_modes)
    if not modes:
        raise ValueError(f"GDTF {gdtf_path.name} no tiene DmxModes")

    mode = None
    if mode_name:
        mode = ft.dmx_modes.get_mode_by_name(mode_name)
        if mode is None:
            raise ValueError(
                f"Modo {mode_name!r} no existe en {gdtf_path.name}. "
                f"Disponibles: {[m.name for m in modes]}"
            )
    else:
        mode = modes[0]

    # Iterar canales del modo
    # En pygdtf 1.4.5 los canales viven en _dmx_channels (o dmx_channels tras post-process)
    channels = list(getattr(mode, "_dmx_channels", None) or [])
    if not channels:
        channels = list(getattr(mode, "dmx_channels", None) or [])

    channel_map: dict[str, int] = {}
    max_offset = 0

    for ch in channels:
        # offset es lista [coarse, fine?] 1-based según GDTF spec
        offsets = ch.offset or []
        if not offsets:
            continue   # canal virtual (sin offset DMX real)

        # Determinar nombre del atributo principal
        attr_name = ""
        if ch.attribute is not None:
            # NodeLink hacia Attributes/<name>
            attr_name = str(getattr(ch.attribute, "name", "")) or \
                        str(ch.attribute)
            # NodeLink renderiza como "Attributes.Pan" → quedarnos con "Pan"
            if "." in attr_name:
                attr_name = attr_name.split(".")[-1]

        canon = _canonical_name(attr_name)
        if not canon:
            canon = f"ch_{offsets[0]}"   # fallback si no hay atributo

        # GDTF offsets son 1-based; nuestro channel_map es 0-based (offset DMX
        # relativo al dmx_start del fixture).
        canonical_offset = offsets[0] - 1
        channel_map[canon] = canonical_offset
        max_offset = max(max_offset, offsets[-1])

        # Si hay fine channel, lo registramos también
        if len(offsets) >= 2:
            fine_name = f"{canon}_fine"
            if fine_name not in channel_map:
                channel_map[fine_name] = offsets[1] - 1

    num_channels = max_offset   # ya 1-based en GDTF = igual al num_channels
    kind = _guess_kind(channel_map)

    # Metadata: max pan/tilt si los podemos sacar del fixture
    metadata: dict = {
        "_source": "gdtf",
        "_gdtf_file": gdtf_path.name,
        "_gdtf_mode": mode.name or "(default)",
        "_gdtf_fixture_name": ft.name or "",
        "_gdtf_manufacturer": getattr(ft, "manufacturer", "") or "",
    }
    # Algunos fixtures incluyen PhysicalFrom/To en los ChannelFunctions de
    # Pan y Tilt — eso indica el rango real. Por ahora dejamos defaults
    # razonables si están presentes los canales.
    if "pan" in channel_map:
        metadata["max_pan_deg"] = 540
    if "tilt" in channel_map:
        metadata["max_tilt_deg"] = 270
    if any(c in channel_map for c in ("r", "g", "b")):
        metadata["has_rgb"] = True
    if "w" in channel_map:
        metadata["has_white"] = True
    if "gobo_wheel" in channel_map:
        metadata["has_gobo"] = True
    if "prism" in channel_map:
        metadata["has_prism"] = True
    if "zoom" in channel_map:
        metadata["has_zoom"] = True
    if "focus" in channel_map:
        metadata["has_focus"] = True
    if "frost" in channel_map:
        metadata["has_frost"] = True

    pid = profile_id or gdtf_path.stem

    return FixtureProfile(
        profile_id=pid,
        name=f"{ft.name or pid} ({mode.name or 'mode'})",
        kind=kind,
        num_channels=num_channels,
        channel_map=channel_map,
        led_count=0,
        metadata=metadata,
    )


def list_gdtf_modes(gdtf_path: Path) -> list[str]:
    """Devuelve los nombres de los modos DMX disponibles en el .gdtf.
    Útil para que la UI muestre un selector si hay varios modos."""
    gdtf_path = Path(gdtf_path)
    if not gdtf_path.is_file():
        return []
    ft = pygdtf.FixtureType(path=str(gdtf_path))
    return [m.name or "(unnamed)" for m in ft.dmx_modes]
