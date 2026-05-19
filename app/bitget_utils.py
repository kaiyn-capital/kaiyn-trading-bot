def format_symbol(symbol: str) -> str:
    return symbol.upper().replace("/", "").replace("-", "")


def validate_order_params(symbol: str, side: str, order_type: str, quantity: float, price: float = None) -> bool:
    if not symbol or not side or not order_type:
        return False

    if side not in ["buy", "sell"]:
        return False

    if order_type not in ["market", "limit"]:
        return False

    if quantity <= 0:
        return False

    if order_type == "limit" and (price is None or price <= 0):
        return False

    return True


def calculate_order_value(quantity: float, price: float) -> float:
    return quantity * price


def format_price(price: float, precision: int = 8) -> str:
    return f"{price:.{precision}f}".rstrip("0").rstrip(".")


def format_quantity(quantity: float, precision: int = 8) -> str:
    return f"{quantity:.{precision}f}".rstrip("0").rstrip(".")
