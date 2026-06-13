"""
test_build.py — Tests de infraestructura de build (H2).

No ejecuta PyInstaller (demasiado pesado para CI normal). Verifica que
los artefactos de build existan y tengan la forma correcta.

Para correr el build real: .\scripts\build_installer.ps1
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_pyinstaller_spec_is_valid_python():
    """showdesigner.spec tiene sintaxis Python válida (parseable por ast)."""
    spec_path = ROOT / "showdesigner.spec"
    assert spec_path.is_file(), "showdesigner.spec no encontrado"
    source = spec_path.read_text(encoding="utf-8")
    try:
        ast.parse(source)
    except SyntaxError as e:
        raise AssertionError(f"showdesigner.spec tiene error de sintaxis: {e}") from e


def test_build_script_exists():
    """scripts/build_installer.ps1 existe."""
    ps1 = ROOT / "scripts" / "build_installer.ps1"
    assert ps1.is_file(), "scripts/build_installer.ps1 no encontrado"


def test_inno_setup_script_exists():
    """ShowDesigner.iss existe para Inno Setup."""
    iss = ROOT / "ShowDesigner.iss"
    assert iss.is_file(), "ShowDesigner.iss no encontrado"


def test_luces_bat_detects_frozen():
    """Luces.bat contiene la lógica de detección PyInstaller (ShowDesigner.exe)."""
    bat = ROOT / "Luces.bat"
    assert bat.is_file(), "Luces.bat no encontrado"
    content = bat.read_text(encoding="utf-8")
    assert "ShowDesigner.exe" in content, "Luces.bat no detecta modo instalador (ShowDesigner.exe)"
    assert "venv311" in content, "Luces.bat no tiene fallback a venv311"


def test_spec_includes_web_dist():
    """showdesigner.spec incluye web/dist como dato empaquetado."""
    spec = (ROOT / "showdesigner.spec").read_text(encoding="utf-8")
    assert "web/dist" in spec, "spec no incluye web/dist en datas"


def test_spec_includes_plugins():
    """showdesigner.spec incluye plugins/ como dato empaquetado."""
    spec = (ROOT / "showdesigner.spec").read_text(encoding="utf-8")
    assert "plugins" in spec, "spec no incluye plugins/ en datas"
