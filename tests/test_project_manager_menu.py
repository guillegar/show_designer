"""
test_project_manager_menu.py — Menú de gestión de proyectos.

Cubre los handlers nuevos del dispatcher:
  - list_projects_detailed (galería con canción/rig/secuencia resumidos)
  - list_components (rigs/canciones/secuencias/presets/autovj agregados)
  - apply_rig / load_sequence / apply_presets / apply_autovj (intercambio de
    componentes sobre el proyecto activo)
  - create_project_from_components / duplicate_project (componer / copiar)

Aísla PROJECTS_DIR en un tmp con mock.patch.object para no tocar proyectos reales,
y neutraliza sync_rig_layout (que escribiría rig_layout.json del repo).
"""
import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── Helpers de construcción ─────────────────────────────────────────────────

def _clip(i):
    return {
        "uid": f"clip_{i}", "track": 0, "bar": 0, "layer": 0,
        "start_ms": i * 1000, "end_ms": i * 1000 + 500, "duration_ms": 500,
        "effect_id": "1", "params": {}, "color": "#ff0000",
        "channel_effect_id": None, "channel_effect_params": {},
        "channel_effects": [], "events": [], "automation_lanes": [],
        "param_links": [],
    }


def _write_project(projects_dir, slug, *, clips, fixtures, presets=0,
                   autovj=False, name=None, analysis_slug=""):
    from src.core.fixtures import FixtureRig, build_default_wled_rig
    folder = projects_dir / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project.json").write_text(json.dumps({
        "slug": slug, "name": name or slug.title(),
        "audio_path": "", "analysis_slug": analysis_slug,
        "created": "", "notes": f"notas {slug}",
    }), encoding="utf-8")
    (folder / "show.json").write_text(json.dumps({
        "version": 2, "duration_ms": 10000,
        "clips": [_clip(i) for i in range(clips)],
        "groups": [], "patterns": [], "cue_points": [],
    }), encoding="utf-8")
    FixtureRig(build_default_wled_rig().fixtures[:fixtures]).save(folder / "rig.json")
    if presets:
        (folder / "presets.json").write_text(json.dumps([
            {"preset_id": f"{slug}_p{i}", "name": f"Preset {i}"} for i in range(presets)
        ]), encoding="utf-8")
    if autovj:
        (folder / "autovj.json").write_text(json.dumps({
            "uid": f"{slug}_rs", "name": "RS", "rules": [], "enabled": True,
        }), encoding="utf-8")
    return folder


def _make_session(pm, active):
    from server.session import ShowSession
    from src.core.autovj import AutoVJEngine
    from src.core.effects_engine import EffectLibrary
    from src.core.fixtures import FixtureRig
    from src.core.timeline_model import Timeline, make_default_groups

    s = object.__new__(ShowSession)
    s.pm = pm
    s._pm = pm
    s.project = active
    s._project = active
    s.on_change = None
    s._rev = 0
    s.library = EffectLibrary()
    s.channel_lib = None
    s.presets = mock.MagicMock()
    s.autovj_engine = AutoVJEngine()
    s.fixture_rig = FixtureRig.load(active.rig_file)
    s.show_engine = mock.MagicMock()
    s.show_engine.rig = s.fixture_rig
    s.timeline = Timeline.load(active.show_file)
    if not getattr(s.timeline, "groups", None):
        s.timeline.groups = make_default_groups()
    s.props = mock.MagicMock()
    s._qt_call_impl = lambda fn, *a, **k: fn(*a, **k)
    s._clip_bucket_index = {}
    s._clip_bucket_index_n = -1
    s._pattern_rev = 0
    s._pattern_expanded = []
    s._pattern_expanded_rev = -1
    s.baked_frames = None
    s.baked_hash = None
    # Neutralizar el escritor de rig_layout.json (tocaría ficheros del repo)
    s.sync_rig_layout = lambda: None
    return s


@contextmanager
def _env(tmp_path, active="alpha"):
    import src._paths as pathsmod
    import src.io.project_manager as pmmod
    projects_dir = tmp_path / "projects"
    analizadas_dir = tmp_path / "analizadas"
    projects_dir.mkdir(parents=True, exist_ok=True)
    analizadas_dir.mkdir(parents=True, exist_ok=True)
    with mock.patch.object(pmmod, "PROJECTS_DIR", projects_dir), \
         mock.patch.object(pathsmod, "ANALIZADAS_DIR", analizadas_dir):
        _write_project(projects_dir, "alpha", clips=5, fixtures=10,
                       presets=2, autovj=True, name="Alpha")
        _write_project(projects_dir, "beta", clips=2, fixtures=3, name="Beta")
        pm = pmmod.ProjectManager()
        session = _make_session(pm, pm.open_project(active))
        yield types.SimpleNamespace(pm=pm, session=session, projects_dir=projects_dir, analizadas_dir=analizadas_dir)


# ── Listado ─────────────────────────────────────────────────────────────────

def test_list_projects_detailed_shape(tmp_path):
    from server.dispatcher import _h_list_projects_detailed
    with _env(tmp_path) as ctx:
        r = _h_list_projects_detailed(ctx.session, {})
    assert r["ok"] and r["current"] == "alpha"
    by = {p["slug"]: p for p in r["projects"]}
    assert set(by) == {"alpha", "beta"}
    assert by["alpha"]["rig"]["fixture_count"] == 10
    assert by["alpha"]["sequence"]["clip_count"] == 5
    assert by["alpha"]["has_presets"] is True
    assert by["alpha"]["has_autovj"] is True
    assert by["alpha"]["is_current"] is True
    assert by["beta"]["rig"]["fixture_count"] == 3
    assert by["beta"]["has_presets"] is False


def test_list_components_shape(tmp_path):
    from server.dispatcher import _h_list_components
    with _env(tmp_path) as ctx:
        r = _h_list_components(ctx.session, {})
    assert r["ok"]
    assert {x["source_slug"] for x in r["rigs"]} == {"alpha", "beta"}
    assert {x["source_slug"] for x in r["sequences"]} == {"alpha", "beta"}
    assert {x["source_slug"] for x in r["presets"]} == {"alpha"}
    assert {x["source_slug"] for x in r["autovj"]} == {"alpha"}
    assert isinstance(r["songs"], list)


# ── Intercambio de componentes ──────────────────────────────────────────────

def test_apply_rig_swaps_and_persists(tmp_path):
    from server.dispatcher import _h_apply_rig
    from src.core.fixtures import FixtureRig
    with _env(tmp_path) as ctx:
        assert len(ctx.session.fixture_rig.fixtures) == 10
        r = _h_apply_rig(ctx.session, {"from_slug": "beta"})
        assert r["ok"] and r["fixtures"] == 3
        assert len(ctx.session.fixture_rig.fixtures) == 3
        persisted = FixtureRig.load(ctx.session.project.rig_file)
        assert len(persisted.fixtures) == 3


def test_load_sequence_swaps_clips(tmp_path):
    from server.dispatcher import _h_load_sequence
    with _env(tmp_path) as ctx:
        assert len(ctx.session.timeline.clips) == 5
        r = _h_load_sequence(ctx.session, {"from_slug": "beta"})
        assert r["ok"], r
        assert len(ctx.session.timeline.clips) == 2


def test_apply_presets_copies(tmp_path):
    from server.dispatcher import _h_apply_presets
    with _env(tmp_path, active="beta") as ctx:
        assert not (ctx.session.project.folder / "presets.json").is_file()
        r = _h_apply_presets(ctx.session, {"from_slug": "alpha"})
        assert r["ok"], r
        assert (ctx.session.project.folder / "presets.json").is_file()


def test_apply_autovj_copies_and_loads(tmp_path):
    from server.dispatcher import _h_apply_autovj
    with _env(tmp_path, active="beta") as ctx:
        r = _h_apply_autovj(ctx.session, {"from_slug": "alpha"})
        assert r["ok"], r
        assert (ctx.session.project.folder / "autovj.json").is_file()
        assert ctx.session.autovj_engine.ruleset is not None


def test_apply_rig_missing_source(tmp_path):
    from server.dispatcher import _h_apply_rig
    with _env(tmp_path) as ctx:
        r = _h_apply_rig(ctx.session, {"from_slug": "fantasma"})
    assert r["ok"] is False


# ── Crear / copiar ──────────────────────────────────────────────────────────

def test_create_project_from_components(tmp_path):
    from server.dispatcher import _h_create_project_from_components
    from src.core.fixtures import FixtureRig
    with _env(tmp_path) as ctx:
        r = _h_create_project_from_components(ctx.session, {
            "name": "Mi Mezcla", "rig_from": "beta",
            "sequence_from": "alpha", "presets_from": "alpha",
        })
        assert r["ok"], r
        folder = ctx.projects_dir / r["slug"]
        assert (folder / "project.json").is_file()
        assert len(FixtureRig.load(folder / "rig.json").fixtures) == 3  # de beta
        seq = json.loads((folder / "show.json").read_text(encoding="utf-8"))
        assert len(seq["clips"]) == 5                                   # de alpha
        assert (folder / "presets.json").is_file()
        # el proyecto activo NO cambió
        assert ctx.session.project.slug == "alpha"


def test_create_safe_slug_and_dedup(tmp_path):
    from server.dispatcher import _h_create_project_from_components
    with _env(tmp_path) as ctx:
        r1 = _h_create_project_from_components(ctx.session, {"name": "Show!! Raro"})
        r2 = _h_create_project_from_components(ctx.session, {"name": "Show!! Raro"})
    assert r1["slug"] == "show_raro"
    assert r2["slug"] == "show_raro_1"


def test_duplicate_project_with_swap(tmp_path):
    from server.dispatcher import _h_duplicate_project
    from src.core.fixtures import FixtureRig
    with _env(tmp_path) as ctx:
        r = _h_duplicate_project(ctx.session, {
            "from_slug": "alpha", "new_name": "Alpha Copia",
            "swap": {"component": "rig", "source_slug": "beta"},
        })
        assert r["ok"], r
        folder = ctx.projects_dir / r["slug"]
        assert len(FixtureRig.load(folder / "rig.json").fixtures) == 3  # swap a beta
        seq = json.loads((folder / "show.json").read_text(encoding="utf-8"))
        assert len(seq["clips"]) == 5                                   # de alpha
        meta = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        assert meta["name"] == "Alpha Copia"


# ── Tests FASE 2: Edición de proyectos + Selección de análisis ────────────────

def test_update_project_name(tmp_path):
    from server.dispatcher import _h_update_project
    with _env(tmp_path) as ctx:
        r = _h_update_project(ctx.session, {
            "slug": "alpha",
            "name": "Alpha Renombrado",
        })
        assert r["ok"], r
        assert r["name"] == "Alpha Renombrado"
        # Verificar persistencia
        meta = json.loads((ctx.projects_dir / "alpha" / "project.json").read_text(encoding="utf-8"))
        assert meta["name"] == "Alpha Renombrado"


def test_update_project_notes(tmp_path):
    from server.dispatcher import _h_update_project
    with _env(tmp_path) as ctx:
        r = _h_update_project(ctx.session, {
            "slug": "alpha",
            "notes": "Notas de prueba para alpha",
        })
        assert r["ok"], r
        assert r["notes"] == "Notas de prueba para alpha"
        meta = json.loads((ctx.projects_dir / "alpha" / "project.json").read_text(encoding="utf-8"))
        assert meta["notes"] == "Notas de prueba para alpha"


def test_update_project_analysis_slug(tmp_path):
    from server.dispatcher import _h_update_project
    with _env(tmp_path) as ctx:
        # Creo un análisis fake en el analizadas mocked
        analysis_dir = ctx.analizadas_dir / "test_analysis"
        analysis_dir.mkdir()
        analysis_file = analysis_dir / "analysis.json"
        analysis_file.write_text(json.dumps({
            "file": "test.mp3",
            "duration_s": 100.0,
            "global": {"bpm_librosa": 120.0},
        }), encoding="utf-8")

        r = _h_update_project(ctx.session, {
            "slug": "alpha",
            "analysis_slug": "test_analysis",
        })
        assert r["ok"], r
        assert r["analysis_slug"] == "test_analysis"
        meta = json.loads((ctx.projects_dir / "alpha" / "project.json").read_text(encoding="utf-8"))
        assert meta["analysis_slug"] == "test_analysis"


def test_update_project_invalid_analysis(tmp_path):
    from server.dispatcher import _h_update_project
    with _env(tmp_path) as ctx:
        r = _h_update_project(ctx.session, {
            "slug": "alpha",
            "analysis_slug": "no_existe",
        })
        assert not r["ok"]
        assert "no encontrado" in r["error"].lower()


def test_update_project_name_empty(tmp_path):
    from server.dispatcher import _h_update_project
    with _env(tmp_path) as ctx:
        r = _h_update_project(ctx.session, {
            "slug": "alpha",
            "name": "   ",  # solo espacios
        })
        assert not r["ok"]
        assert "vacío" in r["error"].lower()


def test_list_available_analyses(tmp_path):
    from server.dispatcher import _h_list_available_analyses
    with _env(tmp_path) as ctx:
        # Creo 2 análisis fake en el analizadas mocked
        for i in range(2):
            analysis_dir = ctx.analizadas_dir / f"analysis_{i}"
            analysis_dir.mkdir()
            analysis_file = analysis_dir / "analysis.json"
            analysis_file.write_text(json.dumps({
                "file": f"song_{i}.mp3",
                "duration_s": 200.0 + i * 10,
                "global": {"bpm_librosa": 120.0 + i * 5},
            }), encoding="utf-8")

        r = _h_list_available_analyses(ctx.session, {})
        assert r["ok"], r
        analyses = r["analyses"]
        assert len(analyses) == 2
        # Verificar que tienen los campos requeridos
        for a in analyses:
            assert "analysis_slug" in a
            assert "title" in a
            assert "bpm" in a
            assert "duration_s" in a


def test_apply_song_resolves_audio_path(tmp_path):
    from server.dispatcher import _h_apply_song
    with _env(tmp_path) as ctx:
        # Crear un análisis fake con un archivo de audio
        analysis_dir = ctx.analizadas_dir / "new_song"
        analysis_dir.mkdir()
        audio_file = analysis_dir / "new_song.mp3"
        audio_file.write_text("fake mp3 data", encoding="utf-8")
        analysis_file = analysis_dir / "analysis.json"
        analysis_file.write_text(json.dumps({
            "file": "new_song.mp3",
            "duration_s": 150.0,
            "global": {"bpm_librosa": 130.0},
        }), encoding="utf-8")

        # Aplicar la canción sin pasar la ruta completa del audio (solo el nombre)
        r = _h_apply_song(ctx.session, {
            "analysis_slug": "new_song",
            "audio_path": "new_song.mp3",  # Solo el nombre, no la ruta completa
        })
        assert r["ok"], r
        assert r["analysis_slug"] == "new_song"
        # Verificar que la ruta se resolvió correctamente
        assert str(audio_file) in r["audio_path"] or "new_song.mp3" in r["audio_path"]
