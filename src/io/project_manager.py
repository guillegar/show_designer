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

En el primer arranque tras esta versión el manager auto-migra:
  show_timeline.json -> projects/el_taser/show.json
  fixtures.json      -> projects/el_taser/rig.json
y crea el project.json con los paths actuales.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

from src._paths import PROJECT_DIR
PROJECTS_DIR  = PROJECT_DIR / 'projects'
LEGACY_SHOW   = PROJECT_DIR / 'show_timeline.json'
LEGACY_RIG    = PROJECT_DIR / 'fixtures.json'

# Slug del proyecto migrado desde el legacy
LEGACY_SLUG   = 'el_taser'
LEGACY_AUDIO  = PROJECT_DIR / 'El Taser de Mama Remix.mp3'
LEGACY_ANALYSIS_SLUG = 'el_taser_de_mama_remix'


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
    def from_folder(cls, folder: Path) -> Optional['Project']:
        """Carga un Project desde su carpeta. None si no existe project.json."""
        pf = folder / 'project.json'
        if not pf.is_file():
            return None
        try:
            with open(pf, 'r', encoding='utf-8') as f:
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
        self._current: Optional[Project] = None

    # ── Consulta ─────────────────────────────────────────────────────────────

    @property
    def current(self) -> Optional[Project]:
        return self._current

    def list_projects(self) -> List[Project]:
        """Lista todos los proyectos disponibles, ordenados por nombre."""
        result = []
        if PROJECTS_DIR.is_dir():
            for folder in sorted(PROJECTS_DIR.iterdir()):
                if folder.is_dir():
                    p = Project.from_folder(folder)
                    if p is not None:
                        result.append(p)
        return result

    def get_project(self, slug: str) -> Optional[Project]:
        folder = PROJECTS_DIR / slug
        return Project.from_folder(folder)

    # ── Apertura / creación ──────────────────────────────────────────────────

    def open_project(self, slug: str) -> Optional[Project]:
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

    # ── Migración desde legacy ────────────────────────────────────────────────

    def ensure_migrated(self) -> Project:
        """
        Si no existe ningún proyecto, crea 'el_taser' migrando los archivos legacy.
        Siempre devuelve el proyecto a cargar por defecto.

        Estrategia:
          1. Si hay proyectos -> devuelve el primero (o el último usado).
          2. Si no hay proyectos -> migra y devuelve 'el_taser'.
        """
        projects = self.list_projects()
        if projects:
            # Ya hay proyectos; devolvemos el primero.
            # En el futuro aquí leeríamos el "último proyecto abierto" de un
            # archivo de preferencias.
            self._current = projects[0]
            return projects[0]

        # ── Primera vez: migrar legacy ────────────────────────────────────────
        print("[project] Primera vez — migrando archivos legacy a projects/el_taser/")

        dest = PROJECTS_DIR / LEGACY_SLUG
        dest.mkdir(parents=True, exist_ok=True)

        # Copiar show_timeline.json -> show.json
        if LEGACY_SHOW.is_file():
            shutil.copy2(LEGACY_SHOW, dest / 'show.json')
            print(f"[project] {LEGACY_SHOW.name} -> projects/{LEGACY_SLUG}/show.json")
        else:
            # Crear show vacío mínimo
            (dest / 'show.json').write_text(
                '{"version":2,"duration_ms":273000,"clips":[],"groups":[],"cue_points":[]}',
                encoding='utf-8')

        # Copiar fixtures.json -> rig.json
        if LEGACY_RIG.is_file():
            shutil.copy2(LEGACY_RIG, dest / 'rig.json')
            print(f"[project] {LEGACY_RIG.name} -> projects/{LEGACY_SLUG}/rig.json")
        else:
            (dest / 'rig.json').write_text('{"fixtures":[]}', encoding='utf-8')

        # Crear project.json
        p = self.create_project(
            slug           = LEGACY_SLUG,
            name           = 'El Taser de Mamá Remix',
            audio_path     = str(LEGACY_AUDIO),
            analysis_slug  = LEGACY_ANALYSIS_SLUG,
            notes          = 'Migrado automáticamente desde archivos legacy v1.7',
        )
        return p

    # ── Persistencia del show y rig activos ──────────────────────────────────

    def save_show(self, timeline, project: Optional[Project] = None):
        """Guarda el timeline en show.json del proyecto activo."""
        p = project or self._current
        if p is None:
            raise RuntimeError("No hay proyecto activo")
        p.folder.mkdir(parents=True, exist_ok=True)
        timeline.save(p.show_file)
        print(f"[project] Show guardado: {p.show_file}")

    def save_rig(self, rig, project: Optional[Project] = None):
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

_MANAGER: Optional[ProjectManager] = None


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
    print(f"\nProyectos disponibles:")
    for p in pm.list_projects():
        print(f"  [{p.slug}] {p.name}")
