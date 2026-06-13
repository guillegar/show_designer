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


def validate_params_against_schema(params: dict, schema: dict) -> None:
    """Valida params contra PARAM_SCHEMA. Lanza ValidationError si algo es inválido.
    Schema vacío → pasa sin error (backwards-compat para efectos legacy).

    Tipos soportados:
      int/float  → valida min/max si están presentes
      enum       → valida que el valor esté en options
      bool       → acepta cualquier valor truthy/falsy
      color      → no aplica (los canales r/g/b se validan como int)
    """
    if not schema:
        return
    for key, spec in schema.items():
        if key not in params:
            continue
        typ = spec.get("type")
        val = params[key]
        if typ == "int":
            try:
                v = int(val)
            except (ValueError, TypeError):
                raise ValidationError(f"'{key}' debe ser un entero")
            min_v = spec.get("min")
            max_v = spec.get("max")
            if min_v is not None and v < min_v:
                raise ValidationError(f"'{key}' fuera de rango (mín {min_v})")
            if max_v is not None and v > max_v:
                raise ValidationError(f"'{key}' fuera de rango (máx {max_v})")
        elif typ == "float":
            try:
                v = float(val)
            except (ValueError, TypeError):
                raise ValidationError(f"'{key}' debe ser un número")
            min_v = spec.get("min")
            max_v = spec.get("max")
            if min_v is not None and v < min_v:
                raise ValidationError(f"'{key}' fuera de rango (mín {min_v})")
            if max_v is not None and v > max_v:
                raise ValidationError(f"'{key}' fuera de rango (máx {max_v})")
        elif typ == "enum":
            options = spec.get("options", [])
            if val not in options:
                raise ValidationError(
                    f"'{key}' valor '{val}' no es válido (opciones: {options})"
                )
        # bool: cualquier valor es válido (truthy/falsy)


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
