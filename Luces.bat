@echo off
title Luces - lanzador
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   LUCES - arrancando backend web...
echo ============================================
echo.

REM Lanza el backend headless en su propia ventana (cierrala para parar la app)
start "Luces backend" "%cd%\venv311\Scripts\python.exe" -m server.main

REM Espera a que el servidor este escuchando en el puerto 8000 (carga ~5-8s)
echo Esperando a que el servidor este listo...
:wait
timeout /t 1 /nobreak >nul
powershell -NoProfile -Command "try { (New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',8000); exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 goto wait

echo Servidor listo. Abriendo el navegador...
start "" http://localhost:8000

echo.
echo La app esta corriendo en http://localhost:8000
echo Para detenerla, cierra la ventana "Luces backend".
timeout /t 4 /nobreak >nul
