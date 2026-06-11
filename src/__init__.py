"""
Show Designer Pro - Software de iluminación escénica profesional.

v1.10 - Backend headless (server/) + frontend web (web/). La UI PyQt5 se retiró
en la Fase 8 de la auditoría (ver ANALYSIS.md): el motor (este `src/`) lo consume
el servidor web en `server/`.

Módulos:
  - core: Núcleo (show_engine, timeline_model, fixtures, effects, undo)
  - analysis: Análisis de audio (librosa + madmom)
  - io: I/O (loaders GDTF, exporters, output routing, project_manager)
  - mcp: MCP bridge para Claude Code (JSON-RPC :9876)
  - plugins: Sistema de plugins de efectos
  - legacy_show: render_stub/BARS legacy de El Taser (fuera del core)
"""

__version__ = "1.10.0"
__author__ = "Usuario"
__license__ = "Prosperity Public License 3.0.0"

# Para imports relativos desde cualquier punto:
# from src.core import show_engine
# from src.mcp import mcp_bridge
# etc.
