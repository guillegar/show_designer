"""
src/log.py — logging centralizado (ANALYSIS hallazgo 17).

Reemplaza el patrón "print y seguir": niveles estándar, consola y archivo
rotativo opcional. Para paths calientes (red, render loop) ofrece
`log_throttled()`, que emite como mucho 1 vez cada `period_s` por clave — así un
error real de red (p. ej. IP mal configurada) SÍ se ve, sin spamear la consola.

Config por entorno:
  LUCES_LOG_LEVEL   nivel raíz (DEBUG/INFO/WARNING/ERROR). Default INFO.
  LUCES_LOG_FILE    ruta de archivo rotativo (o "1" → ./luces.log). Default: sin archivo.

Uso:
    from src.log import get_logger, log_throttled
    log = get_logger(__name__)
    log.info("arrancando"); log.warning("ojo"); log.error("falló X")
    log_throttled(log, logging.ERROR, f"artnet:{ip}", f"send Art-Net a {ip} falló: {e}")

La migración mecánica de los ~251 `print()` restantes a este logger es incremental
(por módulos); aquí se cablean los paths críticos (red) primero.
"""
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

_ROOT_NAME = "luces"
_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger(_ROOT_NAME)
    level = os.environ.get("LUCES_LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level, logging.INFO))
    root.propagate = False

    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%H:%M:%S")
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    logfile = os.environ.get("LUCES_LOG_FILE")
    if logfile:
        path = Path("luces.log") if logfile in ("1", "true", "True") else Path(logfile)
        try:
            fh = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except Exception:
            pass  # si no se puede abrir el archivo, seguimos solo con consola

    _configured = True


def get_logger(name: str = _ROOT_NAME) -> logging.Logger:
    """Devuelve un logger bajo el namespace `luces.<modulo>` (config lazy)."""
    _configure()
    if not name or name in ("__main__", _ROOT_NAME):
        return logging.getLogger(_ROOT_NAME)
    short = name.split(".")[-1]
    return logging.getLogger(f"{_ROOT_NAME}.{short}")


# ── Throttling para paths calientes (red, render loop) ───────────────────────
_last_emit: dict = {}


def log_throttled(logger: logging.Logger, level: int, key: str, msg: str,
                  period_s: float = 1.0) -> None:
    """Emite `msg` como mucho 1 vez cada `period_s` por `key`.

    Pensado para no saturar la consola en bucles a 30 FPS cuando algo falla de
    forma repetida (p. ej. un socket a una IP caída).
    """
    now = time.monotonic()
    if now - _last_emit.get(key, 0.0) >= period_s:
        _last_emit[key] = now
        logger.log(level, msg)
