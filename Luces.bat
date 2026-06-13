@echo off
title Luces - lanzador
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   LUCES - reinicio limpio
echo ============================================
echo.

REM --- 1) Cerrar cualquier instancia previa (puertos 8000 web + 9876 MCP) ---
echo Cerrando instancias anteriores...
powershell -NoProfile -Command ^
  "foreach ($p in 8000,9876,5173) { try { Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } } catch {} }"

REM Pequena espera para que el SO libere los puertos
timeout /t 1 /nobreak >nul

REM --- 2) Detectar modo de ejecucion: instalador PyInstaller o venv de desarrollo ---
REM   - Instalador: ShowDesigner.exe existe en el mismo directorio (sys.frozen=True)
REM   - Desarrollo: usar venv311/Scripts/python.exe
if exist "%~dp0ShowDesigner.exe" (
    echo Modo: instalador PyInstaller
    set "PYTHON_CMD=%~dp0ShowDesigner.exe"
    set "PYTHON_ARGS="
) else if exist "%~dp0venv311\Scripts\python.exe" (
    echo Modo: entorno virtual de desarrollo
    set "PYTHON_CMD=%~dp0venv311\Scripts\python.exe"
    set "PYTHON_ARGS=-m server.main"
) else (
    echo Modo: python del sistema ^(sin venv311^)
    set "PYTHON_CMD=python"
    set "PYTHON_ARGS=-m server.main"
)

REM --- 3) Arrancar el backend headless en su propia ventana ---
echo Arrancando backend...
if defined PYTHON_ARGS (
    start "Luces backend" "%PYTHON_CMD%" %PYTHON_ARGS%
) else (
    start "Luces backend" "%PYTHON_CMD%"
)

REM --- 4) Esperar a que el servidor escuche en el puerto 8000 (carga ~5-8s) ---
echo Esperando a que el servidor este listo...
set /a tries=0
:wait
timeout /t 1 /nobreak >nul
set /a tries+=1
powershell -NoProfile -Command "try { (New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',8000); exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  if %tries% geq 30 (
    echo.
    echo [ERROR] El servidor no arranco en 30s. Revisa la ventana "Luces backend".
    pause
    exit /b 1
  )
  goto wait
)

REM --- 5) Abrir el navegador ---
echo Servidor listo. Abriendo el navegador...
start "" http://localhost:8000

echo.
echo La app esta corriendo en http://localhost:8000
echo Para detenerla: cierra la ventana "Luces backend" o usa "Cerrar Luces.bat".
timeout /t 4 /nobreak >nul
