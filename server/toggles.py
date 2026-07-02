"""
toggles.py — Lógica de toggle reutilizable para set membership.

Elimina duplicación en _h_set_track_mute y _h_set_track_solo (dispatcher.py).
"""
from __future__ import annotations


def toggle_set_membership(
    container: set,
    item: int,
    on: bool | None = None,
) -> bool:
    """
    Añade/quita un item de un set con lógica de toggle.

    Args:
        container: el set a mutar (ej. muted_tracks, solo_tracks)
        item: entero a toggle (ej. track number)
        on: True=añadir, False=quitar, None=toggle (inverso del estado actual)

    Returns:
        nuevo estado booleano (True si está en el set después, False si no)

    Ejemplo:
        on = toggle_set_membership(session.muted_tracks, 0, None)  # toggle track 0
        on = toggle_set_membership(session.muted_tracks, 0, True)   # fuerza mute
    """
    is_member = item in container
    if on is None:
        on = not is_member
    if on:
        container.add(item)
    else:
        container.discard(item)
    return on
