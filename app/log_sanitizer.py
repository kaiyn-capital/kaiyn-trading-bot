from typing import Any


def mask_value(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value)
    if not text:
        return None

    return f"***{text[-4:]}"


def _get_message(response: dict[str, Any]) -> Any:
    return response.get("msg") or response.get("message")


def _asset_count(data: Any) -> int:
    if isinstance(data, (list, tuple, dict)):
        return len(data)
    return 0


def _asset_is_usdt(asset: Any) -> bool:
    if not isinstance(asset, dict):
        return False

    coin = asset.get("coin") or asset.get("marginCoin") or asset.get("currency")
    return str(coin).upper() == "USDT"


def _has_usdt(data: Any) -> bool:
    if isinstance(data, dict):
        if "USDT" in data:
            return True
        return any(_asset_is_usdt(value) for value in data.values())

    if isinstance(data, (list, tuple)):
        return any(_asset_is_usdt(asset) for asset in data)

    return False


def summarize_balance_response(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {
            "code": None,
            "msg": None,
            "asset_count": 0,
            "has_usdt": False,
            "response_type": type(response).__name__,
        }

    data = response.get("data")
    return {
        "code": response.get("code"),
        "msg": _get_message(response),
        "asset_count": _asset_count(data),
        "has_usdt": _has_usdt(data),
    }


def summarize_order_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"payload_type": type(payload).__name__}

    return {
        "symbol": payload.get("symbol"),
        "side": payload.get("side"),
        "orderType": payload.get("orderType"),
        "tradeSide": payload.get("tradeSide"),
        "size": payload.get("size"),
        "has_price": payload.get("price") not in (None, ""),
        "force": payload.get("force"),
        "has_stop_loss": payload.get("presetStopLossPrice") not in (None, ""),
        "has_take_profit": payload.get("presetStopSurplusPrice") not in (None, ""),
        "clientOid": mask_value(payload.get("clientOid")),
    }


def summarize_order_response(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {"response_type": type(response).__name__}

    data = response.get("data")
    if not isinstance(data, dict):
        data = {}

    return {
        "code": response.get("code"),
        "msg": _get_message(response),
        "orderId": mask_value(data.get("orderId") or response.get("orderId")),
        "clientOid": mask_value(
            data.get("clientOid")
            or data.get("clientOrderId")
            or response.get("clientOid")
            or response.get("clientOrderId")
        ),
    }


def summarize_http_error(status: int | None, text: str | None) -> dict[str, Any]:
    return {
        "http_status": status,
        "response_length": len(text or ""),
    }


def summarize_telegram_update(update: Any) -> dict[str, Any]:
    if update is None:
        return {"update_id": None}

    effective_chat = getattr(update, "effective_chat", None)
    effective_user = getattr(update, "effective_user", None)
    effective_message = getattr(update, "effective_message", None)
    callback_query = getattr(update, "callback_query", None)

    return {
        "update_id": getattr(update, "update_id", None),
        "chat_id": getattr(effective_chat, "id", None),
        "chat_type": getattr(effective_chat, "type", None),
        "telegram_id": getattr(effective_user, "id", None),
        "message_id": getattr(effective_message, "message_id", None),
        "has_text": bool(getattr(effective_message, "text", None)),
        "has_callback_query": callback_query is not None,
    }
