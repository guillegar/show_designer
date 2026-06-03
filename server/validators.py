"""
validators.py — Centralizar validación de parámetros JSON-RPC.

Elimina casting ad-hoc en handlers (dispatcher.py) y proporciona errores
consistentes (ValidationError → JSON-RPC error).
"""
from __future__ import annotations


class ValidationError(Exception):
    """
    Parámetro inválido — los handlers la atrapan y devuelven JSON-RPC error.

    Ejemplo:
        try:
            track = require_int(params, "track")
        except ValidationError as e:
            return {"ok": False, "error": str(e)}
    """

    pass


def require_int(params: dict, key: str, min_val: int | None = None) -> int:
    """
    Extrae y valida un int de params.

    Args:
        params: dict de parámetros JSON-RPC
        key: clave del parámetro
        min_val: validación adicional (ej. min_val=0 para no-negativos)

    Returns:
        valor entero validado

    Raises:
        ValidationError si falta, no es int, o falla min_val
    """
    try:
        val = int(params[key])
    except KeyError:
        raise ValidationError(f"falta parámetro '{key}'")
    except (ValueError, TypeError):
        raise ValidationError(f"'{key}' no es un entero válido")

    if min_val is not None and val < min_val:
        raise ValidationError(f"'{key}' debe ser >= {min_val}")

    return val


def require_order(start: int, end: int, start_label: str = "start", end_label: str = "end"):
    """
    Valida que end > start.

    Args:
        start: valor inicial
        end: valor final
        start_label: nombre del parámetro start (para mensajes)
        end_label: nombre del parámetro end (para mensajes)

    Raises:
        ValidationError si end <= start
    """
    if end <= start:
        raise ValidationError(f"'{end_label}' debe ser mayor que '{start_label}'")


def require_key(params: dict, key: str, expected_type: type | None = None):
    """
    Requiere la presencia de una clave; opcionalmente castea tipo.

    Args:
        params: dict de parámetros
        key: clave requerida
        expected_type: tipo esperado (int, str, bool, etc.) — castea si no coincide

    Returns:
        valor de params[key], opcionalmente casteado

    Raises:
        ValidationError si falta la clave o el casteo falla
    """
    try:
        val = params[key]
    except KeyError:
        raise ValidationError(f"falta parámetro '{key}'")

    if expected_type and not isinstance(val, expected_type):
        try:
            val = expected_type(val)
        except (ValueError, TypeError):
            raise ValidationError(
                f"'{key}' no puede ser casteado a {expected_type.__name__}"
            )

    return val
