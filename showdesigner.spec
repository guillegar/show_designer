# showdesigner.spec — PyInstaller spec para Show Designer Pro
# Uso: pyinstaller showdesigner.spec
# Resultado: dist/ShowDesigner/ (directorio autocontenido con .exe + DLLs)
#
# Para empaquetar en instalador .exe, ejecutar después:
#   iscc ShowDesigner.iss   (requiere Inno Setup instalado)

from pathlib import Path
ROOT = Path(SPEC).parent  # noqa: F821 (definido por PyInstaller)

a = Analysis(
    ['server/main.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Frontend compilado (npm run build en web/)
        ('web/dist', 'web/dist'),
        # Plugins de efectos Python
        ('plugins', 'plugins'),
        # Proyectos de ejemplo (opcional — pueden omitirse si son muy grandes)
        ('projects', 'projects'),
        # Perfiles GDTF
        ('gdtf_profiles', 'gdtf_profiles'),
    ],
    hiddenimports=[
        # librosa usa estos de forma dinámica
        'librosa', 'soundfile', 'scipy', 'scipy.signal',
        'numpy', 'numpy.core', 'numpy.core._multiarray_umath',
        # Plugins opcionales — si no están instalados, el server los ignora
        'sacn', 'mido', 'pylinkbpm', 'serial', 'serial.tools', 'serial.tools.list_ports',
    ],
    excludes=[
        # Solo desarrollo — no necesarios en producción
        'pytest', 'pytest_cov', 'coverage',
        # Qt (removido en F8)
        'PyQt5', 'PySide2', 'tkinter',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ShowDesigner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # consola visible para ver logs; cambiar a False para producción silenciosa
    icon=None,      # añadir 'assets/icon.ico' si existe
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ShowDesigner',
)
