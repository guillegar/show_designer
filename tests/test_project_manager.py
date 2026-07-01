"""
tests/test_project_manager.py — Tests del ProjectManager (v1.8 F3)
"""
import json
import shutil
import datetime
from pathlib import Path
import pytest

from src.io.project_manager import Project, ProjectManager, get_manager, PROJECTS_DIR


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pm(tmp_path) -> ProjectManager:
    """ProjectManager aislado que usa tmp_path como PROJECTS_DIR."""
    from src.io import project_manager as pm_module
    original = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path / 'projects'
    (tmp_path / 'projects').mkdir(parents=True, exist_ok=True)
    pm = ProjectManager.__new__(ProjectManager)
    pm._current = None
    # Parchear el PROJECTS_DIR de la instancia
    import importlib
    # Usar la clase directamente para que use la variable del módulo
    return pm, pm_module, original


# ── 1. Project dataclass ──────────────────────────────────────────────────────

def test_project_paths(tmp_path):
    """Project genera los paths derivados correctamente."""
    from src.io import project_manager as pm_module
    # Temporarily override PROJECTS_DIR
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        p = Project(slug='test', name='Test', audio_path='/audio/test.mp3',
                    analysis_slug='test_slug')
        assert p.folder == tmp_path / 'test'
        assert p.show_file == tmp_path / 'test' / 'show.json'
        assert p.rig_file  == tmp_path / 'test' / 'rig.json'
        assert p.project_file == tmp_path / 'test' / 'project.json'
        assert p.audio == Path('/audio/test.mp3')
    finally:
        pm_module.PROJECTS_DIR = old


def test_project_save_meta(tmp_path):
    """Project.save_meta() crea project.json con los datos correctos."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        p = Project(slug='myshow', name='Mi Show', audio_path='/audio/a.mp3',
                    analysis_slug='a_slug', notes='Notas de prueba')
        p.save_meta()
        pf = tmp_path / 'myshow' / 'project.json'
        assert pf.is_file()
        data = json.loads(pf.read_text(encoding='utf-8'))
        assert data['slug'] == 'myshow'
        assert data['name'] == 'Mi Show'
        assert data['audio_path'] == '/audio/a.mp3'
        assert data['analysis_slug'] == 'a_slug'
        assert data['notes'] == 'Notas de prueba'
    finally:
        pm_module.PROJECTS_DIR = old


def test_project_from_folder(tmp_path):
    """Project.from_folder() carga correctamente desde project.json."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        # Crear proyecto y guardarlo
        p = Project(slug='loaded', name='Cargado', audio_path='/x.mp3',
                    analysis_slug='x_slug')
        p.save_meta()
        # Cargar desde carpeta
        p2 = Project.from_folder(tmp_path / 'loaded')
        assert p2 is not None
        assert p2.slug == 'loaded'
        assert p2.name == 'Cargado'
        assert p2.analysis_slug == 'x_slug'
    finally:
        pm_module.PROJECTS_DIR = old


def test_project_from_folder_missing(tmp_path):
    """Project.from_folder() devuelve None si no existe project.json."""
    result = Project.from_folder(tmp_path / 'nonexistent')
    assert result is None


# ── 2. ProjectManager — CRUD ──────────────────────────────────────────────────

def test_create_project(tmp_path):
    """create_project() crea la carpeta y el project.json."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        pm = ProjectManager()
        p = pm.create_project('show1', 'Show 1', '/audio/s1.mp3', 'slug_s1')
        assert p.slug == 'show1'
        assert (tmp_path / 'show1' / 'project.json').is_file()
        assert pm.current is not None
        assert pm.current.slug == 'show1'
    finally:
        pm_module.PROJECTS_DIR = old


def test_list_projects_empty(tmp_path):
    """list_projects() devuelve lista vacía si no hay proyectos."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path / 'proj'
    (tmp_path / 'proj').mkdir()
    try:
        pm = ProjectManager()
        assert pm.list_projects() == []
    finally:
        pm_module.PROJECTS_DIR = old


def test_list_projects_multiple(tmp_path):
    """list_projects() devuelve todos los proyectos creados."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        pm = ProjectManager()
        pm.create_project('aaa', 'AAA', '/a.mp3')
        pm.create_project('bbb', 'BBB', '/b.mp3')
        pm.create_project('ccc', 'CCC', '/c.mp3')
        projects = pm.list_projects()
        assert len(projects) == 3
        slugs = [p.slug for p in projects]
        assert 'aaa' in slugs and 'bbb' in slugs and 'ccc' in slugs
    finally:
        pm_module.PROJECTS_DIR = old


def test_open_project(tmp_path):
    """open_project() devuelve el proyecto y lo establece como current."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        pm = ProjectManager()
        pm.create_project('x', 'X', '/x.mp3')
        pm._current = None  # limpiar
        proj = pm.open_project('x')
        assert proj is not None
        assert proj.slug == 'x'
        assert pm.current.slug == 'x'
    finally:
        pm_module.PROJECTS_DIR = old


def test_open_project_nonexistent(tmp_path):
    """open_project() devuelve None si el proyecto no existe."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        pm = ProjectManager()
        result = pm.open_project('noexiste')
        assert result is None
    finally:
        pm_module.PROJECTS_DIR = old


def test_create_project_duplicate(tmp_path):
    """Crear un proyecto con slug existente devuelve el existente."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        pm = ProjectManager()
        p1 = pm.create_project('dup', 'Duplicado', '/d.mp3')
        p2 = pm.create_project('dup', 'Otro nombre', '/d2.mp3')
        # Debe devolver el existente (nombre original)
        assert p2.slug == 'dup'
        # Solo un project.json
        assert (tmp_path / 'dup' / 'project.json').is_file()
    finally:
        pm_module.PROJECTS_DIR = old


def test_rename_project(tmp_path):
    """rename_project() actualiza el nombre en el project.json."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        pm = ProjectManager()
        pm.create_project('r', 'Nombre Original', '/r.mp3')
        pm.rename_project('r', 'Nombre Nuevo')
        # Releer desde disco
        p = Project.from_folder(tmp_path / 'r')
        assert p.name == 'Nombre Nuevo'
    finally:
        pm_module.PROJECTS_DIR = old


# ── 3. ensure_migrated ────────────────────────────────────────────────────────

def test_ensure_migrated_returns_first_when_existing(tmp_path):
    """Si ya hay proyectos, ensure_migrated devuelve el primero."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        pm = ProjectManager()
        pm.create_project('primero', 'Primero', '/a.mp3')
        pm.create_project('segundo', 'Segundo', '/b.mp3')
        pm._current = None
        proj = pm.ensure_migrated()
        assert proj is not None
        assert proj.slug in ('primero', 'segundo')
    finally:
        pm_module.PROJECTS_DIR = old


def test_ensure_migrated_creates_default_if_empty(tmp_path):
    """Sin proyectos, ensure_migrated crea un proyecto por defecto.

    (La migración legacy desde show_timeline.json/fixtures.json se retiró.)
    """
    from src.io import project_manager as pm_module
    old_pdir = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path / 'projects'
    (tmp_path / 'projects').mkdir()
    try:
        pm = ProjectManager()
        proj = pm.ensure_migrated()
        assert proj is not None
        assert (pm_module.PROJECTS_DIR / proj.slug / 'project.json').is_file()
        assert (pm_module.PROJECTS_DIR / proj.slug / 'show.json').is_file()
        assert (pm_module.PROJECTS_DIR / proj.slug / 'rig.json').is_file()
    finally:
        pm_module.PROJECTS_DIR = old_pdir


# ── 4. save_show / save_rig ───────────────────────────────────────────────────

def test_save_show_uses_project_path(tmp_path):
    """save_show() guarda en project.show_file."""
    from src.io import project_manager as pm_module
    from src.core.timeline_model import Timeline, Clip
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        pm = ProjectManager()
        proj = pm.create_project('s', 'S', '/s.mp3')
        tl = Timeline(duration_ms=60000)
        tl.clips = [Clip(track=0, start_ms=0, end_ms=1000, effect_id=1)]
        pm.save_show(tl)
        assert proj.show_file.is_file()
        # Verificar que se guardó correctamente
        from core.timeline_model import Timeline as TL2
        loaded = TL2.load(proj.show_file)
        assert len(loaded.clips) == 1
    finally:
        pm_module.PROJECTS_DIR = old


def test_save_rig_uses_project_path(tmp_path):
    """save_rig() guarda en project.rig_file."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        pm = ProjectManager()
        pm.create_project('r', 'R', '/r.mp3')
        from core.fixtures import FixtureRig
        rig = FixtureRig(fixtures=[])
        pm.save_rig(rig)
        assert pm.current.rig_file.is_file()
    finally:
        pm_module.PROJECTS_DIR = old


def test_save_show_no_project_raises(tmp_path):
    """save_show() lanza RuntimeError si no hay proyecto activo."""
    from src.io import project_manager as pm_module
    old = pm_module.PROJECTS_DIR
    pm_module.PROJECTS_DIR = tmp_path
    try:
        pm = ProjectManager()
        pm._current = None
        from core.timeline_model import Timeline
        with pytest.raises(RuntimeError):
            pm.save_show(Timeline())
    finally:
        pm_module.PROJECTS_DIR = old


# ── 5. get_manager singleton ──────────────────────────────────────────────────

def test_get_manager_returns_singleton():
    """get_manager() devuelve siempre el mismo objeto."""
    from src.io import project_manager as pm_module
    pm_module._MANAGER = None  # reset
    m1 = get_manager()
    m2 = get_manager()
    assert m1 is m2
    pm_module._MANAGER = None  # cleanup
