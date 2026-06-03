"""
main.py — Entry point del backend web headless.

Uso:
    python -m server.main            # arranca en http://localhost:8000
    python -m server.main --port 8000 --host 0.0.0.0

Sustituye a `python src/ui/dual_app.py` (PyQt5). Sirve el frontend web, el
control JSON-RPC, el stream de frames y el compat MCP (:9876) para Claude.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Setup MINIMAL de sys.path ANTES de importar src._setup_paths
# (necesario porque src._setup_paths es lo que configura sys.path correctamente)
_root = Path(__file__).resolve().parent.parent  # server/main.py → show-designer/
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Setup centralizado de sys.path (única fuente de verdad)
from src._setup_paths import *

# Windows console = cp1252 → forzar UTF-8 evita crashes con emojis/flechas
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser(description="Luces — backend web headless")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    import uvicorn
    from server.web import create_app

    app = create_app()
    print(f"[main] Luces web → http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
