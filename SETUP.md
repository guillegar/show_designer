# 🎨 Show Designer Pro — Setup Guide

**Show Designer Pro** es una aplicación profesional de iluminación escénica con editor de timeline, análisis de audio, viewer 3D, y control DMX de fixtures en tiempo real.

---

## Requisitos previos

- **Python 3.11+** (recomendado 3.11 o 3.12)
- **Windows 10+** o Linux/Mac con Python venv
- ~2 GB de espacio en disco

---

## Instalación paso a paso

### 1. Descargar e ir a la carpeta

```powershell
# En PowerShell o CMD
cd "C:\ruta\a\Show Designer Pro"
```

### 2. Crear un entorno virtual

```powershell
python -m venv venv
```

Si Python no se encuentra, asegúrate de que está en el PATH o usa la ruta completa:
```powershell
C:\Program Files\Python311\python.exe -m venv venv
```

### 3. Activar el entorno virtual

**Windows (PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
venv\Scripts\activate.bat
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

Deberías ver `(venv)` al inicio del prompt.

### 4. Instalar las dependencias

```powershell
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

Esto instalará:
- **PyQt5** — interfaz gráfica
- **NumPy + SciPy** — cálculos numéricos
- **Librosa + Madmom** — análisis de audio (BPM, beats, onsets)
- **pygdtf** — importación de fixtures GDTF
- **mcp** — protocolo MCP para Claude Code
- **websockets** — WebSocket para el servidor 3D
- **pytest + pytest-cov** — testing

### 5. Arrancar la aplicación

```powershell
python dual_app.py
```

La app debería abrirse con la ventana principal. Deberías ver en la consola:

```
[+] OutputRouter cargado: 11 universos enrutados
[+] ShowEngine inicializado vía AnalysisService
[+] MCP bridge arrancado en ws://127.0.0.1:9876
[+] Viewer 3D arrancado: http://localhost:8080/
[dual] ShowEngine compartido entre ambas pestañas
```

---

## Uso básico

### Pestañas principales

1. **🎨 Timeline** — Editor de clips, efectos, cues y markers
2. **📊 Feedback** — Control en tiempo real y análisis visual
3. **🔧 Patch** — Vista 2D top-down del rig de fixtures
4. **🎵 Analyzer** — Análisis musical (secciones, beats, kicks)

### Atajos de teclado

| Atajo | Acción |
|-------|--------|
| `Space` | Play/Pause |
| `Ctrl+S` | Guardar show |
| `Ctrl+O` | Cargar show |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+M` | Ir a tab Analyzer |
| `Ctrl+1..4` | Cambiar tab |

---

## Verificación de la instalación

### Test rápido (smoke test)

```powershell
pytest tests/test_analyzer_service.py -v
```

Deberías ver algo como:

```
test_analyzer_service.py::test_summary PASSED
test_analyzer_service.py::test_list_sections PASSED
...
```

Si ves `PASSED` en varios tests, la instalación es correcta.

### Abrir el viewer 3D

1. Arranca `dual_app.py`
2. El servidor 3D estará en `http://localhost:8080/`
3. Abre esa URL en tu navegador (Chrome/Edge/Firefox)

Deberías ver 10 barras WLED iluminadas (si hay un show cargado).

---

## Troubleshooting

### Puerto 9876/9877 ocupado

```powershell
Get-Process python | Stop-Process -Force
```

Luego relanza `dual_app.py`.

### `ModuleNotFoundError: No module named 'PyQt5'`

Confirma que el venv está activado:
```powershell
(venv) PS> # deberías ver (venv) al inicio
```

Si no, activa de nuevo:
```powershell
.\venv\Scripts\Activate.ps1
```

Luego reinstala:
```powershell
pip install -r requirements.txt
```

### La app se cierra sin error

Mira la consola para tracebacks. Si ves `ConnectionResetError` o `InvalidMessage`, es probable que un healthcheck o test TCP llegue a `127.0.0.1:9876` mientras la app arranca. **Esto ya está manejado en v1.9 F2** — si ocurre, es un bug. Reporta en GitHub.

---

## Estructura del proyecto

```
Show Designer Pro/
├── README.md              ← Guía user-facing
├── CLAUDE.md              ← Documentación profunda (arquitectura)
├── SETUP.md               ← Este archivo
├── requirements.txt       ← Dependencias Python
├── dual_app.py            ← Entry point
├── tests/                 ← Suite de tests (363 tests)
├── profiles/              ← Fixture profiles (JSON + GDTF)
├── projects/              ← Proyectos guardados (El Taser, etc.)
├── viewer3d/              ← Servidor 3D + JS (Three.js)
├── versions/              ← Checkpoints históricos
└── venv/                  ← Entorno virtual (creado al instalar)
```

---

## Próximos pasos

1. **Carga un show:**
   - En la pestaña Timeline, `Ctrl+O` → selecciona `projects/el_taser/show.json`

2. **Experimenta con el analyzer:**
   - Ve a la pestaña 🎵 Analyzer
   - Verás las secciones, beats y eventos detectados

3. **Control en vivo:**
   - Pestaña 📊 Feedback para ver las barras reaccionando
   - Usa los cue points (`C1-C9`) para saltar a momentos clave

4. **Documentación profunda:**
   - Lee `CLAUDE.md` para entender la arquitectura y decisiones de diseño

---

## Más info

- **GitHub Issues / Bugs:** Reporta en el repositorio
- **Licencia:** GPL-3.0
- **Basado en:** ASLS Studio (inspiración), Three.js, PyQt5

---

¡Disfruta creando shows de luz! 💡✨
