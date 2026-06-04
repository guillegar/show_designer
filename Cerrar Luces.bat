@echo off
title Luces - cerrar
chcp 65001 >nul

echo Cerrando Luces (puertos 8000 web + 9876 MCP + 5173 dev)...
powershell -NoProfile -Command ^
  "foreach ($p in 8000,9876,5173) { try { Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } } catch {} }"

echo Listo. La app se ha detenido.
timeout /t 2 /nobreak >nul
