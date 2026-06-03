"""Centralizado cálculo de rutas del proyecto.

Este módulo es la única fuente de verdad para rutas del proyecto.
Importar desde aquí en lugar de recalcular PROJECT_DIR en cada módulo.
"""
from pathlib import Path


def _get_project_root():
    """Calcula raíz del proyecto válido desde cualquier profundidad en src/."""
    return Path(__file__).resolve().parent.parent


PROJECT_DIR = _get_project_root()
ANALIZADAS_DIR = PROJECT_DIR / 'analizadas'
PROFILES_DIR = PROJECT_DIR / 'profiles'
SHOWS_SAVED_DIR = PROJECT_DIR / 'shows_saved'
PLUGINS_DIR = PROJECT_DIR / 'plugins' / 'effects'
VIEWER3D_DIR = PROJECT_DIR / 'src' / 'viewer3d'

__all__ = [
    'PROJECT_DIR',
    'ANALIZADAS_DIR',
    'PROFILES_DIR',
    'SHOWS_SAVED_DIR',
    'PLUGINS_DIR',
    'VIEWER3D_DIR',
]
