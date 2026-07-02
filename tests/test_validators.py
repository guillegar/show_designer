"""
test_validators.py — cobertura de server/validators.py (B5).

Eran funciones puras sin tests; aquí se cubren los caminos felices y de error.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.validators import (  # noqa: E402
    ValidationError,
    require_int,
    require_key,
    require_order,
)


# ── require_int ──────────────────────────────────────────────────────────────
def test_require_int_ok():
    assert require_int({"x": 5}, "x") == 5
    assert require_int({"x": "7"}, "x") == 7   # castea strings numéricos


def test_require_int_missing():
    with pytest.raises(ValidationError) as e:
        require_int({}, "x")
    assert "falta" in str(e.value)


def test_require_int_not_a_number():
    with pytest.raises(ValidationError) as e:
        require_int({"x": "abc"}, "x")
    assert "entero" in str(e.value)


def test_require_int_min_val():
    assert require_int({"x": 0}, "x", min_val=0) == 0
    with pytest.raises(ValidationError) as e:
        require_int({"x": -1}, "x", min_val=0)
    assert ">= 0" in str(e.value)


# ── require_order ────────────────────────────────────────────────────────────
def test_require_order_ok():
    require_order(0, 10)  # no lanza


def test_require_order_equal_or_inverted():
    with pytest.raises(ValidationError):
        require_order(10, 10)
    with pytest.raises(ValidationError):
        require_order(10, 5, "start_ms", "end_ms")


# ── require_key ──────────────────────────────────────────────────────────────
def test_require_key_present():
    assert require_key({"k": "v"}, "k") == "v"


def test_require_key_missing():
    with pytest.raises(ValidationError):
        require_key({}, "k")


def test_require_key_cast():
    assert require_key({"k": "3"}, "k", int) == 3
    with pytest.raises(ValidationError):
        require_key({"k": "no"}, "k", int)
