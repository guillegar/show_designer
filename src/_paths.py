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
# Fuente única del viewer 3D = web/public/v3d (ANALYSIS hallazgo 7). Vite la copia
# a web/dist/v3d en cada build; el server Qt legacy también sirve desde aquí.
VIEWER3D_DIR = PROJECT_DIR / 'web' / 'public' / 'v3d'

__all__ = [
    'PROJECT_DIR',
    'ANALIZADAS_DIR',
    'PROFILES_DIR',
    'SHOWS_SAVED_DIR',
    'PLUGINS_DIR',
    'VIEWER3D_DIR',
]
