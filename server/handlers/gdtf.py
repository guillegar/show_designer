"""
handlers/gdtf.py — J3: biblioteca GDTF — browser, metadata y alta de fixtures (ADR-005).
"""
from __future__ import annotations

# ── J3 — Biblioteca GDTF: browser y búsqueda ─────────────────────────────────

_gdtf_cache: dict = {}   # path_str → {name, manufacturer, modes, channel_count, path}


def _gdtf_metadata(gdtf_path) -> dict:
    """Extrae metadatos ligeros de un .gdtf sin cargar el profile completo."""
    from pathlib import Path as _Path
    key = str(gdtf_path)
    if key in _gdtf_cache:
        return _gdtf_cache[key]
    try:
        import pygdtf
        ft = pygdtf.FixtureType(path=str(gdtf_path))
        modes = [m.name or "(unnamed)" for m in ft.dmx_modes]
        # Canal count del primer modo
        channel_count = 0
        first_modes = list(ft.dmx_modes)
        if first_modes:
            chs = list(getattr(first_modes[0], "_dmx_channels", None) or
                       getattr(first_modes[0], "dmx_channels", None) or [])
            offsets = []
            for ch in chs:
                offs = getattr(ch, "offset", None) or []
                if offs:
                    offsets.extend(offs)
            channel_count = max(offsets) if offsets else 0
        meta = {
            "name": ft.name or _Path(gdtf_path).stem,
            "manufacturer": getattr(ft, "manufacturer", "") or "",
            "modes": modes,
            "channel_count": channel_count,
            "path": str(gdtf_path),
        }
    except Exception as e:
        meta = {
            "name": _Path(gdtf_path).stem,
            "manufacturer": "",
            "modes": [],
            "channel_count": 0,
            "path": str(gdtf_path),
            "_error": str(e),
        }
    _gdtf_cache[key] = meta
    return meta


def _h_list_gdtf_profiles(session, params):
    """list_gdtf_profiles() → {ok, profiles: [{name, manufacturer, modes, channel_count, path}]}.

    Escanea PROFILES_DIR/*.gdtf y devuelve metadatos de cada perfil.
    Caché en memoria (_gdtf_cache) para llamadas repetidas.
    """
    from src._paths import PROFILES_DIR
    profiles = []
    if PROFILES_DIR.is_dir():
        for p in sorted(PROFILES_DIR.glob("*.gdtf")):
            profiles.append(_gdtf_metadata(p))
    return {"ok": True, "profiles": profiles}


def _h_add_fixture_from_gdtf(session, params):
    """add_fixture_from_gdtf(profile_path, universe, start_channel, name="") → {ok, fixture}.

    Carga el GDTF en profile_path, crea un Fixture en el rig y lo persiste.
    profile_path: ruta al .gdtf (relativa a PROFILES_DIR o absoluta).
    Invariante I3: devuelve el fixture creado.
    """
    from pathlib import Path as _Path

    from src._paths import PROFILES_DIR
    from src.core.fixtures import Fixture
    from src.io.loaders.gdtf_profile import load_gdtf_profile

    profile_path = params.get("profile_path")
    universe = int(params.get("universe", 1))
    start_channel = int(params.get("start_channel", 1))
    name = str(params.get("name", "")).strip()
    mode_name = params.get("mode_name")

    if not profile_path:
        return {"ok": False, "error": "profile_path requerido"}

    p = _Path(profile_path)
    if not p.is_absolute():
        p = PROFILES_DIR / p
    if not p.is_file():
        return {"ok": False, "error": f"Perfil GDTF no encontrado: {profile_path}"}

    rig = getattr(session, "fixture_rig", None)
    if rig is None:
        return {"ok": False, "error": "No hay rig cargado"}

    try:
        profile = load_gdtf_profile(p, mode_name=mode_name)
    except Exception as e:
        return {"ok": False, "error": f"Error cargando GDTF: {e}"}

    # Generar fixture_id único
    base = (name or profile.name or p.stem).lower().replace(" ", "_").replace("/", "_")
    import re as _re
    base = _re.sub(r"[^a-z0-9_]", "", base)[:30] or "fixture"
    existing_ids = {fx.fixture_id for fx in rig.fixtures}
    fixture_id = base
    counter = 1
    while fixture_id in existing_ids:
        fixture_id = f"{base}_{counter}"
        counter += 1

    fx = Fixture(
        fixture_id=fixture_id,
        profile_id=profile.profile_id,
        universe=universe,
        dmx_start=start_channel,
        label=name or profile.name,
    )
    rig.fixtures.append(fx)
    rig.save(session.project.rig_file)

    return {"ok": True, "fixture": fx.to_dict()}


HANDLERS = {
    "list_gdtf_profiles": _h_list_gdtf_profiles,
    "add_fixture_from_gdtf": _h_add_fixture_from_gdtf,
}
