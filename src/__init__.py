"""
Show Designer Pro - Software de iluminación escénica profesional.

v1.9 F2 - Drag-create de channel clips + estabilización anti-crash.

Módulos:
  - core: Núcleo (show_engine, timeline_model, fixtures, effects)
  - ui: Interfaz gráfica PyQt5
  - analysis: Análisis de audio (librosa + madmom)
  - io: I/O (loaders GDTF, exporters, output routing)
  - mcp: MCP bridge para Claude Code
  - viewer3d: Visualizador 3D (Three.js + WebSocket)
  - plugins: Sistema de plugins
  - utils: Utilidades
"""

__version__ = "1.9.2"
__author__ = "Usuario"
__license__ = "GPL-3.0"

# Para imports relativos desde cualquier punto:
# from src.core import show_engine
# from src.ui import dual_app
# etc.
