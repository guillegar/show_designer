"""
server/ — Backend web headless de Luces (v1.10 "Web Migration").

Sustituye la capa de UI PyQt5 (src/ui/) por un servidor web sin Qt:

  ShowSession   (session.py)        dueño del modelo+motor+audio (reloj maestro)
  Dispatcher    (dispatcher.py)     port Qt-free de los 52 handlers JSON-RPC
  tick          (tick.py)           loop asyncio 30 FPS: compute → Art-Net → broadcast
  web           (web.py)            FastAPI: estáticos + /ws/control + /ws/stream
  main          (main.py)           entry point: python -m server.main

Reutiliza SIN CAMBIOS: src/core/*, src/analysis/*, src/io/*, src/outputs/*.
"""
