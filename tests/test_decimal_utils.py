from decimal import Decimal

import pytest

from app.decimal_utils import decimal_json, decimal_text, to_decimal, to_decimal_or_none


def test_to_decimal_preserves_string_precision():
    assert to_decimal("0.001790000000000001") == Decimal("0.001790000000000001")


def test_to_decimal_rejects_missing_or_invalid_values():
    with pytest.raises(ValueError):
        to_decimal(None)

    with pytest.raises(ValueError):
        to_decimal("not-a-number")

    with pytest.raises(ValueError):
        to_decimal("NaN")


def test_to_decimal_or_none_keeps_optional_boundary_explicit():
    assert to_decimal_or_none(None) is None
    assert to_decimal_or_none("") is None
    assert to_decimal_or_none("12.34") == Decimal("12.34")


def test_decimal_text_trims_noise_and_can_floor_to_places():
    assert decimal_text(Decimal("0.0017900")) == "0.00179"
    assert decimal_text(Decimal("79999.999"), places=1) == "79999.9"


def test_decimal_json_returns_string_or_none():
    assert decimal_json(Decimal("1000.5000")) == "1000.5"
    assert decimal_json(None) is None
