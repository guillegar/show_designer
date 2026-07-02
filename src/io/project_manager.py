"""
project_manager.py — Sistema multi-proyecto para Show Designer Pro (v1.8 F3).

Estructura de un proyecto:
    projects/
      <nombre>/
        project.json   ← metadata (nombre, audio_path, analysis_slug)
        show.json      ← timeline (clips, grupos, cues, markers)
        rig.json       ← fixtures del rig

El audio queda donde esté (ruta absoluta en project.json).
El análisis sigue en analizadas/<slug>/ (no se mueve).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src._paths import PROJECT_DIR

PROJECTS_DIR  = PROJECT_DIR / 'projects'


# ─────────────────────────────────────────────────────────────────────────────
# Project — descriptor de un proyecto
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Project:
    """Descriptor de un proyecto cargado o disponible."""
    slug: str                          # nombre de carpeta (sin espacios)
    name: str                          # nombre legible para UI
    audio_path: str                    # ruta absoluta al audio
    analysis_slug: str                 # slug en analizadas/
    created: str = ''                  # ISO datetime (info solamente)
    notes: str = ''                    # notas libres

    # ── Paths derivados ──────────────────────────────────────────────────────

    @property
    def folder(self) -> Path:
        return PROJECTS_DIR / self.slug

    @property
    def show_file(self) -> Path:
        return self.folder / 'show.json'

    @property
    def rig_file(self) -> Path:
        return self.folder / 'rig.json'

    @property
    def project_file(self) -> Path:
        return self.folder / 'project.json'

    @property
    def rig_layout_file(self) -> Path:
        """Posiciones 3D explícitas editadas por el usuario (K1)."""
        return self.folder / 'rig_layout.json'

    @property
    def audio(self) -> Path:
        return Path(self.audio_path)

    @property
    def analysis_file(self) -> Path:
        return PROJECT_DIR / 'analizadas' / self.analysis_slug / 'analysis.json'

    # ── Persistencia ─────────────────────────────────────────────────────────

    def save_meta(self):
        """Guarda project.json con los metadatos del proyecto."""
        self.folder.mkdir(parents=True, exist_ok=True)
        data = {
            'slug':            self.slug,
            'name':            self.name,
            'audio_path':      str(self.audio_path),
            'analysis_slug':   self.analysis_slug,
            'created':         self.created,
            'notes':           self.notes,
        }
        with open(self.project_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def from_folder(cls, folder: Path) -> Project | None:
        """Carga un Project desde su carpeta. None si no existe project.json."""
        pf = folder / 'project.json'
        if not pf.is_file():
            return None
        try:
            with open(pf, encoding='utf-8') as f:
                data = json.load(f)
            return cls(
                slug           = data.get('slug', folder.name),
                name           = data.get('name', folder.name),
                audio_path     = data.get('audio_path', ''),
                analysis_slug  = data.get('analysis_slug', ''),
                created        = data.get('created', ''),
                notes          = data.get('notes', ''),
            )
        except Exception as e:
            print(f"[project] Error cargando {pf}: {e}")
            return None


# ─────────────────────────────────────────────────────────────────────────────
# ProjectManager — registro de proyectos + apertura + creación
# ─────────────────────────────────────────────────────────────────────────────

class ProjectManager:
    """
    Gestiona la colección de proyectos en PROJECTS_DIR.

    Uso típico:
        pm = ProjectManager()
        pm.ensure_migrated()          # ← primera vez: migra el legacy
        projects = pm.list_projects()
        proj = pm.open_project(slug)
    """

    def __init__(self):
        PROJECTS_DIR.mkdir(exist_ok=True)
        self._current: Project | None = None

    # ── Consulta ─────────────────────────────────────────────────────────────

    @property
    def current(self) -> Project | None:
        return self._current

    def list_projects(self) -> list[Project]:
        """Lista todos los proyectos disponibles, ordenados por nombre."""
        result = []
        if PROJECTS_DIR.is_dir():
            for folder in sorted(PROJECTS_DIR.iterdir()):
                if folder.is_dir():
                    p = Project.from_folder(folder)
                    if p is not None:
                        result.append(p)
        return result

    def get_project(self, slug: str) -> Project | None:
        folder = PROJECTS_DIR / slug
        return Project.from_folder(folder)

    # ── Apertura / creación ──────────────────────────────────────────────────

    def open_project(self, slug: str) -> Project | None:
        """Abre un proyecto existente. Devuelve None si no existe."""
        p = self.get_project(slug)
        if p is not None:
            self._current = p
        return p

    def create_project(self, slug: str, name: str, audio_path: str,
                       analysis_slug: str = '', notes: str = '') -> Project:
        """
        Crea un nuevo proyecto vacío.
        Si ya existe la carpeta devuelve el proyecto existente.
        """
        import datetime
        folder = PROJECTS_DIR / slug
        folder.mkdir(parents=True, exist_ok=True)
        # Si ya tiene project.json no sobreescribimos
        if (folder / 'project.json').is_file():
            p = Project.from_folder(folder)
            if p:
                self._current = p
                return p
        p = Project(
            slug           = slug,
            name           = name,
            audio_path     = audio_path,
            analysis_slug  = analysis_slug,
            created        = datetime.datetime.now().isoformat(timespec='seconds'),
            notes          = notes,
        )
        p.save_meta()
        self._current = p
        return p

    def rename_project(self, slug: str, new_name: str):
        """Cambia el nombre legible (no el slug/carpeta)."""
        p = self.get_project(slug)
        if p:
            p.name = new_name
            p.save_meta()
            if self._current and self._current.slug == slug:
                self._current = p

    # ── Proyecto por defecto ──────────────────────────────────────────────────

    def ensure_migrated(self) -> Project:
        """Devuelve el proyecto a cargar por defecto.

          1. Si hay proyectos -> devuelve el primero (o el último usado).
          2. Si no hay ninguno -> crea un proyecto vacío por defecto.

        (La migración legacy desde `show_timeline.json`/`fixtures.json` se retiró:
        todos los proyectos viven ya en `projects/<slug>/`.)
        """
        projects = self.list_projects()
        if projects:
            # Ya hay proyectos; devolvemos el primero.
            # En el futuro aquí leeríamos el "último proyecto abierto" de un
            # archivo de preferencias.
            self._current = projects[0]
            return projects[0]

        # Sin proyectos (instalación vacía): crear uno mínimo por defecto.
        dest = PROJECTS_DIR / 'nuevo_proyecto'
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'show.json').write_text(
            '{"version":2,"duration_ms":0,"clips":[],"groups":[],"cue_points":[]}',
            encoding='utf-8')
        (dest / 'rig.json').write_text('{"fixtures":[]}', encoding='utf-8')
        return self.create_project(
            slug          = 'nuevo_proyecto',
            name          = 'Nuevo proyecto',
            audio_path    = '',
            analysis_slug = '',
            notes         = '',
        )

    # ── Persistencia del show y rig activos ──────────────────────────────────

    def save_show(self, timeline, project: Project | None = None):
        """Guarda el timeline en show.json del proyecto activo."""
        p = project or self._current
        if p is None:
            raise RuntimeError("No hay proyecto activo")
        p.folder.mkdir(parents=True, exist_ok=True)
        timeline.save(p.show_file)
        print(f"[project] Show guardado: {p.show_file}")

    def save_rig(self, rig, project: Project | None = None):
        """Guarda el rig en rig.json del proyecto activo."""
        p = project or self._current
        if p is None:
            raise RuntimeError("No hay proyecto activo")
        p.folder.mkdir(parents=True, exist_ok=True)
        rig.save(p.rig_file)
        print(f"[project] Rig guardado: {p.rig_file}")


# ─────────────────────────────────────────────────────────────────────────────
# Singleton conveniente para importar desde el server / handlers MCP
# ─────────────────────────────────────────────────────────────────────────────

_MANAGER: ProjectManager | None = None


def get_manager() -> ProjectManager:
    """Devuelve el ProjectManager singleton (creándolo si es la primera vez)."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = ProjectManager()
    return _MANAGER


# ─────────────────────────────────────────────────────────────────────────────
# Test rápido: python project_manager.py
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    pm = ProjectManager()
    proj = pm.ensure_migrated()
    print(f"\nProyecto activo: {proj.name!r} (slug={proj.slug})")
    print(f"  audio:    {proj.audio}")
    print(f"  show:     {proj.show_file}  (existe={proj.show_file.is_file()})")
    print(f"  rig:      {proj.rig_file}   (existe={proj.rig_file.is_file()})")
    print(f"  analysis: {proj.analysis_file}  (existe={proj.analysis_file.is_file()})")
    print("\nProyectos disponibles:")
    for p in pm.list_projects():
        print(f"  [{p.slug}] {p.name}")
