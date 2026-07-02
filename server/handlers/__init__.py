"""
server/handlers — handlers web-only del dispatcher, por dominio (ADR-005).

`dispatcher.py` creció hasta ~4.5k líneas con 145 handlers. Este paquete lo
despieza por dominios cohesivos SIN cambiar la API JSON-RPC:

  * Cada módulo define sus funciones `_h_*` + helpers privados y termina con
    un dict `HANDLERS = {nombre: fn}` (mismo patrón que `_LOCAL`).
  * Si un handler muta el timeline o el rig, lo declara en los sets
    `TIMELINE_MUTATORS` / `RIG_MUTATORS` del módulo (viven junto al handler,
    no en una lista central).
  * `dispatcher.py` llama a `load_all()` y mergea `LOCAL` en su `_LOCAL`
    (los nombres movidos se re-exportan allí por compat: tests y web
    importan `_h_*` desde `server.dispatcher`).

Para handlers NUEVOS se puede usar el decorador `@handler("nombre")` en vez
del dict. Regla: los módulos de este paquete NO importan `server.dispatcher`
(el dispatcher importa el paquete, nunca al revés).
"""
from __future__ import annotations

from collections.abc import Callable

LOCAL: dict[str, Callable] = {}
TIMELINE_MUTATORS: set[str] = set()
RIG_MUTATORS: set[str] = set()

_LOADED = False


def handler(name: str, *, timeline_mutator: bool = False, rig_mutator: bool = False):
    """Decorador de registro para handlers nuevos."""
    def deco(fn: Callable) -> Callable:
        LOCAL[name] = fn
        if timeline_mutator:
            TIMELINE_MUTATORS.add(name)
        if rig_mutator:
            RIG_MUTATORS.add(name)
        return fn
    return deco


def load_all() -> None:
    """Importa TODOS los módulos de dominio del paquete y mergea sus registros.

    Autodescubrimiento vía pkgutil: añadir un dominio nuevo = crear el .py con
    su dict HANDLERS — sin listas que mantener (una lista hardcodeada se quedó
    obsoleta en silencio durante la tanda 4 y costó 14 tests). Idempotente.
    """
    global _LOADED
    if _LOADED:
        return
    import importlib
    import pkgutil
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        LOCAL.update(getattr(mod, "HANDLERS", {}))
        TIMELINE_MUTATORS.update(getattr(mod, "TIMELINE_MUTATORS", set()))
        RIG_MUTATORS.update(getattr(mod, "RIG_MUTATORS", set()))
    _LOADED = True
