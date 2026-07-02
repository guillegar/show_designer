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
    """Importa los módulos de dominio y mergea sus registros. Idempotente."""
    global _LOADED
    if _LOADED:
        return
    from server.handlers import (
        autosave,
        autovj,
        cues,
        live,
        markers,
        mixer,
        movers,
        osc,
        patch,
        projects,
        render_export,
        switch,
        tempo,
        waveform,
    )
    for mod in (waveform, projects, patch, live, markers, autovj, cues,
                mixer, render_export, autosave, osc, movers, switch, tempo):
        LOCAL.update(getattr(mod, "HANDLERS", {}))
        TIMELINE_MUTATORS.update(getattr(mod, "TIMELINE_MUTATORS", set()))
        RIG_MUTATORS.update(getattr(mod, "RIG_MUTATORS", set()))
    _LOADED = True
