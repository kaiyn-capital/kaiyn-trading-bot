from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any


def to_decimal(value: Any) -> Decimal:
    """Convert external numeric input into Decimal without going through float math."""
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        raise ValueError("missing decimal value")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid decimal value") from exc
    if not decimal_value.is_finite():
        raise ValueError("invalid decimal value")
    return decimal_value


def to_decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return to_decimal(value)
    except ValueError:
        return None


def _quantize_for_places(value: Decimal, places: int) -> Decimal:
    if places <= 0:
        return value.quantize(Decimal("1"), rounding=ROUND_DOWN)
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def decimal_text(value: Any, places: int | None = None) -> str:
    decimal_value = to_decimal(value)
    if places is not None:
        decimal_value = _quantize_for_places(decimal_value, places)

    text = format(decimal_value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def decimal_json(value: Any) -> str | None:
    if value is None:
        return None
    return decimal_text(value)
