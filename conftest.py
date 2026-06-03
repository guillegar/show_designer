import sys
from pathlib import Path

# Setup MINIMAL de sys.path ANTES de importar src._setup_paths
# (necesario porque src._setup_paths es lo que configura sys.path correctamente)
_root = Path(__file__).resolve().parent  # conftest.py → show-designer/
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Setup centralizado de sys.path (única fuente de verdad)
from src._setup_paths import *
