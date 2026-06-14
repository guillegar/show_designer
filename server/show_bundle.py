"""
show_bundle.py — Backup y restauración completa de show (N2).

Exporta/importa un ZIP portátil con todo lo necesario para reproducir el show
en otra máquina: show.json, autovj.json, output_targets.json (sin credenciales),
plugins custom y (opcionalmente) el audio.
"""
from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

_SD_VERSION = "2.0"
_MANIFEST_FILE = "MANIFEST.json"
_BUNDLE_VERSION = "1"
_MAX_AUDIO_BYTES = 500 * 1024 * 1024  # 500 MB

# Plugins built-in (incluidos con el repo); se excluyen del bundle
_BUILTIN_PLUGINS = frozenset({
    "breathing.py", "example_plugin.py", "fire.py", "gradient_sweep.py",
    "pixel_chase.py", "pixel_map.py", "plugin_template.py", "rainbow_wave.py",
    "scanner.py", "solid_color.py", "spanish_flag.py", "strobe_color.py",
    "theater_chase.py", "twinkle.py", "vu_meter.py", "waving_flag.py",
})


def _sanitize_output_targets(data: dict) -> dict:
    """Reemplaza credenciales por placeholders en output_targets.json."""
    import copy
    sanitized = copy.deepcopy(data)
    if "api_key" in sanitized:
        sanitized["api_key"] = "<PLACEHOLDER_API_KEY>"
    for entry in sanitized.get("tokens", []):
        if "token" in entry:
            entry["token"] = "<PLACEHOLDER_TOKEN>"
    if "webhooks" in sanitized:
        for wh in sanitized["webhooks"]:
            if "secret" in wh:
                wh["secret"] = "<PLACEHOLDER_SECRET>"
    return sanitized


def export_show_bundle(session, include_audio: bool = False) -> str:
    """Genera projects/<slug>/show_bundle.zip y devuelve la ruta absoluta."""
    slug = session.project.slug
    project_dir = Path("projects") / slug
    out_path = project_dir / "show_bundle.zip"
    tmp_path = project_dir / "show_bundle.zip.tmp"

    project_dir.mkdir(parents=True, exist_ok=True)

    custom_plugins: List[str] = []
    plugins_dir = Path("plugins/effects")
    if plugins_dir.exists():
        custom_plugins = [
            f.name for f in sorted(plugins_dir.glob("*.py"))
            if f.name not in _BUILTIN_PLUGINS and not f.name.startswith("_")
        ]

    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # show.json
        show_json_path = project_dir / "show.json"
        if show_json_path.exists():
            zf.write(show_json_path, "show.json")

        # autovj.json (opcional)
        autovj_path = project_dir / "autovj.json"
        if autovj_path.exists():
            zf.write(autovj_path, "autovj.json")

        # output_targets.json (sanitizado)
        ot_path = Path("output_targets.json")
        if ot_path.exists():
            raw = json.loads(ot_path.read_text("utf-8"))
            sanitized = _sanitize_output_targets(raw)
            zf.writestr("output_targets.json", json.dumps(sanitized, indent=2))

        # plugins custom
        for fname in custom_plugins:
            src = plugins_dir / fname
            zf.write(src, f"plugins/effects/{fname}")

        # audio (opcional, < 500 MB)
        audio_path: Optional[Path] = None
        try:
            audio_path = Path(session.project.audio_file)
        except Exception:
            pass
        if include_audio and audio_path and audio_path.exists():
            size = audio_path.stat().st_size
            if size < _MAX_AUDIO_BYTES:
                zf.write(audio_path, f"audio/{audio_path.name}")

        # MANIFEST
        manifest = {
            "version": _BUNDLE_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "show_slug": slug,
            "sd_version": _SD_VERSION,
            "plugins": custom_plugins,
        }
        zf.writestr(_MANIFEST_FILE, json.dumps(manifest, indent=2))

    os.replace(tmp_path, out_path)
    return str(out_path.resolve())


def import_show_bundle(zip_path: str, projects_dir: Path) -> Tuple[str, List[str]]:
    """Extrae un bundle ZIP y registra como nuevo proyecto.
    Devuelve (slug, warnings)."""
    warnings: List[str] = []

    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile:
        raise ValueError(f"ZIP corrupto o inválido: {zip_path}")

    with zf:
        names = zf.namelist()

        if _MANIFEST_FILE not in names:
            raise ValueError("ZIP no contiene MANIFEST.json — no es un bundle válido")

        manifest = json.loads(zf.read(_MANIFEST_FILE).decode("utf-8"))
        original_slug = manifest.get("show_slug", "imported_show")
        plugins_in_bundle: List[str] = manifest.get("plugins", [])

        # Slug seguro (sin path traversal)
        slug = re.sub(r"[^a-z0-9_-]", "_", original_slug.lower())
        if not slug:
            slug = "imported_show"

        # Evitar colisiones
        target_dir = projects_dir / slug
        suffix = 1
        while target_dir.exists():
            target_dir = projects_dir / f"{slug}_{suffix}"
            slug = f"{slug}_{suffix}"
            suffix += 1

        target_dir.mkdir(parents=True, exist_ok=True)
        plugins_dir = Path("plugins/effects")
        plugins_dir.mkdir(parents=True, exist_ok=True)

        # Extraer show.json
        if "show.json" in names:
            raw = json.loads(zf.read("show.json").decode("utf-8"))
            (target_dir / "show.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        else:
            warnings.append("show.json no incluido en el bundle")

        # autovj.json
        if "autovj.json" in names:
            raw_avj = zf.read("autovj.json").decode("utf-8")
            (target_dir / "autovj.json").write_text(raw_avj, encoding="utf-8")

        # output_targets.json (contiene placeholders — informar al usuario)
        if "output_targets.json" in names:
            (target_dir / "output_targets.json").write_text(
                zf.read("output_targets.json").decode("utf-8"), encoding="utf-8"
            )
            warnings.append(
                "output_targets.json importado con placeholders — "
                "configura API key y tokens antes de usar"
            )

        # plugins custom
        for fname in plugins_in_bundle:
            entry = f"plugins/effects/{fname}"
            if entry in names:
                dest = plugins_dir / fname
                if dest.exists():
                    warnings.append(f"Plugin '{fname}' ya existe — no sobreescrito")
                else:
                    dest.write_bytes(zf.read(entry))
            else:
                warnings.append(f"Plugin '{fname}' declarado en MANIFEST pero no encontrado en el ZIP")

        # audio
        audio_entries = [n for n in names if n.startswith("audio/")]
        if not audio_entries:
            warnings.append("Audio no incluido en el bundle — vincula el archivo manualmente")
        else:
            audio_dir = target_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            for entry in audio_entries:
                audio_name = entry.split("/", 1)[-1]
                if audio_name:
                    (audio_dir / audio_name).write_bytes(zf.read(entry))

    return slug, warnings
