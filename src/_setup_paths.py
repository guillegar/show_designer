"""Centralizado setup de sys.path para el proyecto.

Este módulo es el ÚNICO lugar que manipula sys.path.
Importar al inicio de conftest.py, dual_app.py, server/main.py, etc.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = str(_ROOT / "src")
_ROOT_STR = str(_ROOT)

if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if _ROOT_STR not in sys.path:
    sys.path.insert(0, _ROOT_STR)
