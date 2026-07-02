"""
handlers/projects.py — Menú de gestión de proyectos (ADR-005): galería,
componentes intercambiables (canción/rig/secuencia/presets/auto-VJ),
crear/copiar/editar proyectos.
"""
from __future__ import annotations

# ── Menú de gestión de proyectos: galería + componentes + crear/copiar ───────
# Un proyecto = paquete de archivos intercambiables (canción/rig/secuencia/
# presets/auto-VJ). Estos handlers exponen ese paquete para verlo, cargar piezas
# sueltas sobre el proyecto activo, y componer/copiar proyectos nuevos.
import json as _json  # noqa: E402
import re as _re  # noqa: E402
import shutil as _shutil  # noqa: E402
from pathlib import Path

from src.log import get_logger
from src.mcp import mcp_bridge as bridge

_log = get_logger(__name__)


def _pm_of(session):
    return getattr(session, "pm", None) or getattr(session, "_pm", None)


def _read_json_safe(path):
    try:
        with open(path, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None


def _song_meta(analysis_slug):
    """{title, bpm, duration_s} de un análisis. Lazy: AnalysisService.summary solo
    lee analysis.json (no el .npz), así que es barato para listar varias canciones."""
    out = {"analysis_slug": analysis_slug, "title": analysis_slug or "—",
           "bpm": None, "duration_s": None}
    if not analysis_slug:
        return out
    try:
        from src.analysis.analyzer_service import ANALIZADAS_DIR, AnalysisService
        d = ANALIZADAS_DIR / analysis_slug
        if not d.is_dir():
            return out
        s = AnalysisService(d).summary or {}
        out["bpm"] = s.get("bpm")
        out["duration_s"] = s.get("duration_s")
        f = s.get("file")
        if f:
            out["title"] = str(f).rsplit(".", 1)[0]
    except Exception:
        pass
    return out


def _safe_project_slug(raw, projects_dir):
    """Slug seguro (sin path traversal) + sin colisiones. Mismo criterio que el
    import de bundles en server/show_bundle.py."""
    base = _re.sub(r"[^a-z0-9_-]", "_", str(raw or "").strip().lower())
    base = _re.sub(r"_+", "_", base).strip("_") or "proyecto"
    slug, suffix = base, 1
    while (projects_dir / slug).exists():
        slug = f"{base}_{suffix}"
        suffix += 1
    return slug


def _h_list_projects_detailed(session, params):
    """list_projects_detailed() → galería: cada proyecto con su canción, rig y
    secuencia resumidos. Lecturas JSON ligeras; NO sustituye a list_projects."""
    pm = _pm_of(session)
    if pm is None:
        return {"ok": True, "projects": [], "current": None}
    current_slug = session.project.slug if getattr(session, "project", None) else None
    out = []
    for p in pm.list_projects():
        rig = _read_json_safe(p.rig_file) or {}
        show = _read_json_safe(p.show_file) or {}
        song = _song_meta(p.analysis_slug)
        out.append({
            "slug": p.slug,
            "name": p.name,
            "is_current": p.slug == current_slug,
            "notes": p.notes,
            "created": p.created,
            "song": {"title": song["title"], "bpm": song["bpm"],
                     "duration_s": song["duration_s"],
                     "analysis_slug": p.analysis_slug, "audio_path": str(p.audio_path)},
            "rig": {"fixture_count": len(rig.get("fixtures") or [])},
            "sequence": {"clip_count": len(show.get("clips") or [])},
            "has_presets": (p.folder / "presets.json").is_file(),
            "has_autovj": (p.folder / "autovj.json").is_file(),
        })
    return {"ok": True, "projects": out, "current": current_slug}


def _h_list_components(session, params):
    """list_components() → {rigs, songs, sequences, presets, autovj} agregados de
    todos los proyectos (+ canciones de analizadas/ aún sin usar)."""
    pm = _pm_of(session)
    empty = {"ok": True, "current": None, "rigs": [], "songs": [],
             "sequences": [], "presets": [], "autovj": []}
    if pm is None:
        return empty
    current_slug = session.project.slug if getattr(session, "project", None) else None
    rigs, sequences, presets, autovj = [], [], [], []
    song_used = {}    # analysis_slug -> [project slugs]
    song_audio = {}   # analysis_slug -> audio_path (de algún proyecto que la use)
    for p in pm.list_projects():
        rig = _read_json_safe(p.rig_file) or {}
        show = _read_json_safe(p.show_file) or {}
        rigs.append({"source_slug": p.slug, "source_name": p.name,
                     "fixture_count": len(rig.get("fixtures") or []),
                     "is_current": p.slug == current_slug})
        sequences.append({"source_slug": p.slug, "source_name": p.name,
                          "clip_count": len(show.get("clips") or []),
                          "pattern_count": len(show.get("patterns") or []),
                          "duration_ms": show.get("duration_ms"),
                          "is_current": p.slug == current_slug})
        pf = p.folder / "presets.json"
        if pf.is_file():
            presets.append({"source_slug": p.slug, "source_name": p.name,
                            "count": len(_read_json_safe(pf) or []),
                            "is_current": p.slug == current_slug})
        af = p.folder / "autovj.json"
        if af.is_file():
            data = _read_json_safe(af) or {}
            rules = data.get("rules") if isinstance(data, dict) else None
            autovj.append({"source_slug": p.slug, "source_name": p.name,
                           "rule_count": len(rules) if rules else 0,
                           "is_current": p.slug == current_slug})
        if p.analysis_slug:
            song_used.setdefault(p.analysis_slug, []).append(p.slug)
            song_audio.setdefault(p.analysis_slug, str(p.audio_path))
    songs = []
    try:
        from src.analysis.analyzer_service import ANALIZADAS_DIR
        if ANALIZADAS_DIR.is_dir():
            for d in sorted(ANALIZADAS_DIR.iterdir()):
                if not d.is_dir() or not (d / "analysis.json").is_file():
                    continue
                meta = _song_meta(d.name)
                # Si no hay audio_path de un proyecto que use esta canción,
                # intenta leerlo desde analysis.json
                audio_path = song_audio.get(d.name, "")
                if not audio_path:
                    analysis_data = _read_json_safe(d / "analysis.json") or {}
                    # Si analysis.json tiene el campo "file", úsalo como audio_path
                    if "file" in analysis_data:
                        audio_path = str(analysis_data["file"])
                songs.append({"analysis_slug": d.name, "title": meta["title"],
                              "bpm": meta["bpm"], "duration_s": meta["duration_s"],
                              "audio_path": audio_path,
                              "used_by": song_used.get(d.name, [])})
    except Exception:
        pass
    return {"ok": True, "current": current_slug, "rigs": rigs, "songs": songs,
            "sequences": sequences, "presets": presets, "autovj": autovj}


def _h_apply_rig(session, params):
    """apply_rig(from_slug) → carga el rig de otro proyecto en el activo y lo
    persiste en su rig.json. Mutador de rig (regenera rig_layout para el visor 3D)."""
    pm = _pm_of(session)
    from_slug = str(params.get("from_slug", "") or "")
    src = pm.get_project(from_slug) if pm else None
    if src is None or not src.rig_file.is_file():
        return {"ok": False, "error": f"rig no encontrado: {from_slug!r}"}
    try:
        n = session.load_rig(src.rig_file)
    except Exception as e:
        return {"ok": False, "error": f"no se pudo cargar el rig: {e}"}
    try:
        session.fixture_rig.save(session.project.rig_file)
    except Exception as e:
        _log.warning(f"[apply_rig] no se pudo persistir rig.json: {e}")
    session.notify_changed("rig")
    return {"ok": True, "from_slug": from_slug, "fixtures": n}


def _h_load_sequence(session, params):
    """load_sequence(from_slug) → intercambia la secuencia (clips/grupos/cues) por
    la de otro proyecto. En memoria (undo lo cubre); se persiste al guardar/autosave,
    como cualquier edición del timeline. Reutiliza _h_load_show del bridge."""
    pm = _pm_of(session)
    from_slug = str(params.get("from_slug", "") or "")
    src = pm.get_project(from_slug) if pm else None
    if src is None or not src.show_file.is_file():
        return {"ok": False, "error": f"secuencia no encontrada: {from_slug!r}"}
    res = bridge._h_load_show(session, {"path": str(src.show_file)})
    if res.get("ok"):
        session.notify_changed("model")
        res["from_slug"] = from_slug
    return res


def _h_apply_presets(session, params):
    """apply_presets(from_slug) → copia el banco de presets de otro proyecto al
    presets.json del activo y recrea el PresetBank."""
    pm = _pm_of(session)
    from_slug = str(params.get("from_slug", "") or "")
    src = pm.get_project(from_slug) if pm else None
    if src is None:
        return {"ok": False, "error": f"proyecto no encontrado: {from_slug!r}"}
    src_file = src.folder / "presets.json"
    if not src_file.is_file():
        return {"ok": False, "error": f"{from_slug!r} no tiene presets"}
    dst_file = session.project.folder / "presets.json"
    try:
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(src_file, dst_file)
        from server.presets import PresetBank
        session.presets = PresetBank(session.library, session.channel_lib,
                                     project_file=dst_file)
        n = len(session.presets.list())
    except Exception as e:
        return {"ok": False, "error": str(e)}
    session.notify_changed("model")
    return {"ok": True, "from_slug": from_slug, "presets": n}


def _h_apply_autovj(session, params):
    """apply_autovj(from_slug) → copia las reglas Auto-VJ de otro proyecto al
    autovj.json del activo y las carga en el motor."""
    pm = _pm_of(session)
    from_slug = str(params.get("from_slug", "") or "")
    src = pm.get_project(from_slug) if pm else None
    if src is None:
        return {"ok": False, "error": f"proyecto no encontrado: {from_slug!r}"}
    src_file = src.folder / "autovj.json"
    if not src_file.is_file():
        return {"ok": False, "error": f"{from_slug!r} no tiene auto-VJ"}
    dst_file = session.project.folder / "autovj.json"
    try:
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(src_file, dst_file)
        session.autovj_engine.load(dst_file)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    session.notify_changed("model")
    return {"ok": True, "from_slug": from_slug}


def _h_apply_song(session, params):
    """apply_song(analysis_slug, audio_path) → cambia la canción del proyecto activo
    (actualiza project.json + recarga análisis/audio + reajusta duración).
    AVISO: re-temporiza el show (los beats/duración de la nueva canción difieren)."""
    from src._paths import ANALIZADAS_DIR

    analysis_slug = str(params.get("analysis_slug", "") or "")
    audio_path = str(params.get("audio_path", "") or "")
    if not analysis_slug and not audio_path:
        return {"ok": False, "error": "analysis_slug o audio_path requerido"}
    proj = getattr(session, "project", None)
    if proj is None:
        return {"ok": False, "error": "sin proyecto activo"}

    # Si audio_path es solo un nombre de archivo (sin rutas), intenta buscarlo en ANALIZADAS_DIR
    if audio_path and "/" not in audio_path and "\\" not in audio_path:
        candidate = ANALIZADAS_DIR / analysis_slug / audio_path if analysis_slug else None
        if candidate and candidate.is_file():
            audio_path = str(candidate)

    try:
        if analysis_slug:
            proj.analysis_slug = analysis_slug
        if audio_path:
            proj.audio_path = audio_path
        proj.save_meta()
    except Exception as e:
        return {"ok": False, "error": f"no se pudo actualizar project.json: {e}"}
    dur_ms = session.load_song(proj.audio_path, proj.analysis_slug)
    try:
        session.timeline.duration_ms = dur_ms
    except Exception:
        pass
    session.notify_changed("model")
    return {"ok": True, "analysis_slug": proj.analysis_slug,
            "audio_path": str(proj.audio_path), "duration_ms": dur_ms}


def _h_update_project(session, params):
    """update_project(slug, name?, notes?, analysis_slug?) → actualiza metadatos de un
    proyecto (incluso si no es activo). Solo campos no-vacíos se actualizan."""
    pm = _pm_of(session)
    if pm is None:
        return {"ok": False, "error": "sin project manager"}
    slug = str(params.get("slug", "") or "").strip()
    if not slug:
        return {"ok": False, "error": "slug requerido"}
    proj = pm.get_project(slug)
    if proj is None:
        return {"ok": False, "error": f"proyecto {slug} no existe"}

    # Actualizar campos si están presentes
    name = params.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            return {"ok": False, "error": "nombre no puede estar vacío"}
        proj.name = name

    notes = params.get("notes")
    if notes is not None:
        proj.notes = str(notes).strip()

    analysis_slug = params.get("analysis_slug")
    if analysis_slug is not None:
        analysis_slug = str(analysis_slug).strip()
        # Validar que existe en analizadas/ si no es vacío
        if analysis_slug:
            from pathlib import Path

            from src._paths import ANALIZADAS_DIR
            analysis_file = Path(ANALIZADAS_DIR) / analysis_slug / "analysis.json"
            if not analysis_file.exists():
                return {"ok": False, "error": f"análisis {analysis_slug} no encontrado en analizadas/"}
        proj.analysis_slug = analysis_slug

    # Persistir
    try:
        proj.save_meta()
    except Exception as e:
        return {"ok": False, "error": f"error al guardar project.json: {e}"}

    # Notificar si es proyecto activo
    current = getattr(session, "project", None)
    if current and current.slug == slug:
        session.notify_changed("model")

    return {
        "ok": True,
        "slug": proj.slug,
        "name": proj.name,
        "notes": proj.notes,
        "audio_path": str(proj.audio_path),
        "analysis_slug": proj.analysis_slug,
    }


def _h_list_available_analyses(session, params):
    """list_available_analyses() → enumera todos los análisis disponibles en analizadas/."""
    import json

    from src._paths import ANALIZADAS_DIR

    analyses = []
    analizadas_path = Path(ANALIZADAS_DIR)

    if analizadas_path.exists():
        for analysis_dir in sorted(analizadas_path.iterdir()):
            if not analysis_dir.is_dir():
                continue
            analysis_file = analysis_dir / "analysis.json"
            if not analysis_file.exists():
                continue
            try:
                with open(analysis_file, encoding="utf-8") as f:
                    data = json.load(f)
                    title = data.get("file", analysis_dir.name)
                    bpm = data.get("global", {}).get("bpm_librosa") or data.get("global", {}).get("bpm_madmom")
                    duration_s = data.get("duration_s")
                    analyses.append({
                        "analysis_slug": analysis_dir.name,
                        "title": title,
                        "bpm": bpm,
                        "duration_s": duration_s,
                    })
            except Exception:
                # ignorar análisis corruptos
                pass

    return {"ok": True, "analyses": analyses}


# Componentes copiables y sus archivos (para crear/duplicar)
_COMPONENT_FILES = {
    "rig": ["rig.json", "rig_layout.json"],
    "sequence": ["show.json"],
    "presets": ["presets.json"],
    "autovj": ["autovj.json"],
    # "song" no es un archivo: vive en project.json (audio_path + analysis_slug)
}


def _h_create_project_from_components(session, params):
    """create_project_from_components(name, slug?, song_from?, rig_from?,
    sequence_from?, presets_from?, autovj_from?) → crea un proyecto nuevo copiando
    cada componente elegido del proyecto origen indicado. NO carga el proyecto
    (el frontend puede llamar a switch_project después si el usuario lo pide)."""
    pm = _pm_of(session)
    if pm is None:
        return {"ok": False, "error": "sin project manager"}
    name = str(params.get("name", "") or "").strip()
    if not name:
        return {"ok": False, "error": "name requerido"}
    from src.io.project_manager import PROJECTS_DIR
    slug = _safe_project_slug(params.get("slug") or name, PROJECTS_DIR)

    # Canción: del proyecto origen (audio_path + analysis_slug)
    audio_path, analysis_slug = "", ""
    song_from = str(params.get("song_from", "") or "")
    if song_from:
        sp = pm.get_project(song_from)
        if sp is not None:
            audio_path, analysis_slug = str(sp.audio_path), sp.analysis_slug

    try:
        proj = pm.create_project(slug=slug, name=name, audio_path=audio_path,
                                 analysis_slug=analysis_slug,
                                 notes=str(params.get("notes", "") or ""))
    except Exception as e:
        return {"ok": False, "error": f"no se pudo crear: {e}"}
    # create_project pone pm._current = proj; restaurar el proyecto realmente activo
    try:
        pm._current = session.project
    except Exception:
        pass

    def _copy_component(comp_from, files):
        if not comp_from:
            return
        sp = pm.get_project(comp_from)
        if sp is None:
            return
        for fname in files:
            srcf = sp.folder / fname
            if srcf.is_file():
                _shutil.copy2(srcf, proj.folder / fname)

    _copy_component(str(params.get("rig_from", "") or ""), _COMPONENT_FILES["rig"])
    _copy_component(str(params.get("sequence_from", "") or ""), _COMPONENT_FILES["sequence"])
    _copy_component(str(params.get("presets_from", "") or ""), _COMPONENT_FILES["presets"])
    _copy_component(str(params.get("autovj_from", "") or ""), _COMPONENT_FILES["autovj"])
    return {"ok": True, "slug": slug, "name": name}


def _h_duplicate_project(session, params):
    """duplicate_project(from_slug, new_name?, new_slug?, swap?) → copia un proyecto
    a un slug nuevo (solo archivos de contenido) y, opcionalmente, sustituye UN
    componente por el de otro proyecto. swap = {component, source_slug}."""
    pm = _pm_of(session)
    if pm is None:
        return {"ok": False, "error": "sin project manager"}
    from_slug = str(params.get("from_slug", "") or "")
    src = pm.get_project(from_slug) if from_slug else None
    if src is None:
        return {"ok": False, "error": f"proyecto no encontrado: {from_slug!r}"}
    from src.io.project_manager import PROJECTS_DIR, Project
    new_name = str(params.get("new_name", "") or "").strip() or f"{src.name} (copia)"
    slug = _safe_project_slug(params.get("new_slug") or new_name, PROJECTS_DIR)
    dst = PROJECTS_DIR / slug
    # Copia limpia: solo contenido (sin autosave/render/exports)
    ignore = _shutil.ignore_patterns("autosave", "render.npz", "render_meta.json",
                                     "preview.gif", "preview.mp4", "patch.pdf",
                                     "dmx_export.csv", "feedback.json")
    try:
        _shutil.copytree(src.folder, dst, ignore=ignore)
    except Exception as e:
        return {"ok": False, "error": f"no se pudo copiar: {e}"}

    def _set_meta(name, audio=None, analysis=None):
        p = Project.from_folder(dst)
        if p is None:
            return
        p.slug, p.name = slug, name
        if audio is not None:
            p.audio_path = audio
        if analysis is not None:
            p.analysis_slug = analysis
        p.save_meta()

    _set_meta(new_name)

    swap = params.get("swap") or {}
    comp = str(swap.get("component", "") or "")
    source_slug = str(swap.get("source_slug", "") or "")
    if comp and source_slug:
        sp = pm.get_project(source_slug)
        if sp is not None:
            if comp == "song":
                _set_meta(new_name, audio=str(sp.audio_path), analysis=sp.analysis_slug)
            else:
                for fname in _COMPONENT_FILES.get(comp, []):
                    srcf = sp.folder / fname
                    if srcf.is_file():
                        _shutil.copy2(srcf, dst / fname)
    return {"ok": True, "slug": slug, "name": new_name}


HANDLERS = {
    "list_projects_detailed": _h_list_projects_detailed,
    "list_components": _h_list_components,
    "apply_rig": _h_apply_rig,
    "load_sequence": _h_load_sequence,
    "apply_presets": _h_apply_presets,
    "apply_autovj": _h_apply_autovj,
    "apply_song": _h_apply_song,
    "update_project": _h_update_project,
    "list_available_analyses": _h_list_available_analyses,
    "create_project_from_components": _h_create_project_from_components,
    "duplicate_project": _h_duplicate_project,
}
# La declaración de mutador vive junto al handler (ADR-005):
TIMELINE_MUTATORS = {"load_sequence"}
RIG_MUTATORS = {"apply_rig"}
