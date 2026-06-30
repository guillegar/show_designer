@echo off
title Luces Red Sun - lanzador
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   LUCES - Oscar Mulero: Red Sun (techno minimal)
echo ============================================
echo.

REM --- 1) Cerrar cualquier instancia previa (puertos 8000 web + 9876 MCP + 5173) ---
echo Cerrando instancias anteriores...
powershell -NoProfile -Command ^
  "foreach ($p in 8000,9876,5173) { try { Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } } catch {} }"

timeout /t 1 /nobreak >nul

REM --- 2) Proyecto de arranque = red_sun ---
set LUCES_PROJECT=red_sun

REM --- 3) Arrancar el backend headless en su propia ventana ---
echo Arrancando backend web (proyecto: %LUCES_PROJECT%)...
start "Luces backend (Red Sun)" "%cd%\venv311\Scripts\python.exe" -m server.main

REM --- 4) Esperar a que el servidor escuche en el puerto 8000 ---
echo Esperando a que el servidor este listo...
set /a tries=0
:wait
timeout /t 1 /nobreak >nul
set /a tries+=1
powershell -NoProfile -Command "try { (New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',8000); exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  if %tries% geq 30 (
    echo.
    echo [ERROR] El servidor no arranco en 30s. Revisa la ventana "Luces backend (Red Sun)".
    pause
    exit /b 1
  )
  goto wait
)

REM --- 5) Abrir el navegador ---
echo Servidor listo. Abriendo el navegador...
start "" http://localhost:8000

echo.
echo La app esta corriendo en http://localhost:8000 con Red Sun (Oscar Mulero).
echo Para detenerla: cierra la ventana "Luces backend (Red Sun)" o usa "Cerrar Luces.bat".
timeout /t 4 /nobreak >nul
