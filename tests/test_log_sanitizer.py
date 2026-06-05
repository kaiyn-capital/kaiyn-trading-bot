from app.log_sanitizer import (
    mask_value,
    sanitize_log_text,
    summarize_balance_response,
    summarize_http_error,
    summarize_order_payload,
    summarize_order_response,
    summarize_telegram_update,
)


def test_mask_value_keeps_only_tail():
    assert mask_value("abc123456789") == "***6789"
    assert mask_value("") is None
    assert mask_value(None) is None


def test_sanitize_log_text_masks_secret_assignments_and_bearer_tokens():
    text = (
        'invalid signature apiKey=plain-api secret:"plain-secret" '
        "passphrase:plain-pass Authorization: Bearer auth-token Bearer loose-token"
    )

    sanitized = sanitize_log_text(text)

    assert "plain-api" not in sanitized
    assert "plain-secret" not in sanitized
    assert "plain-pass" not in sanitized
    assert "auth-token" not in sanitized
    assert "loose-token" not in sanitized
    assert "apiKey=***" in sanitized
    assert 'secret:"***"' in sanitized
    assert "passphrase:***" in sanitized


def test_summarize_balance_response_excludes_amounts():
    response = {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "marginCoin": "USDT",
                "available": "1234.5678",
                "equity": "9999.0000",
            }
        ],
    }

    summary = summarize_balance_response(response)
    summary_text = str(summary)

    assert summary == {
        "code": "00000",
        "msg": "success",
        "asset_count": 1,
        "has_usdt": True,
    }
    assert "1234.5678" not in summary_text
    assert "9999.0000" not in summary_text


def test_summarize_order_payload_masks_client_oid_and_hides_sl_tp_values():
    payload = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "orderType": "limit",
        "tradeSide": "open",
        "size": "0.01",
        "price": "81000",
        "force": "gtc",
        "presetStopLossPrice": "79000",
        "presetStopSurplusPrice": "83000",
        "clientOid": "kaiyn-order-abcdef123456",
    }

    summary = summarize_order_payload(payload)
    summary_text = str(summary)

    assert summary["clientOid"] == "***3456"
    assert summary["has_price"] is True
    assert summary["has_stop_loss"] is True
    assert summary["has_take_profit"] is True
    assert "kaiyn-order-abcdef123456" not in summary_text
    assert "79000" not in summary_text
    assert "83000" not in summary_text


def test_summarize_order_response_masks_ids():
    response = {
        "code": "00000",
        "msg": "success",
        "data": {
            "orderId": "12345678901234567890",
            "clientOid": "client-order-0987654321",
        },
    }

    summary = summarize_order_response(response)
    summary_text = str(summary)

    assert summary["orderId"] == "***7890"
    assert summary["clientOid"] == "***4321"
    assert "12345678901234567890" not in summary_text
    assert "client-order-0987654321" not in summary_text


def test_summarize_http_error_excludes_response_body():
    body = '{"secret":"do-not-log-this","detail":"full exchange response"}'
    summary = summarize_http_error(500, body)
    summary_text = str(summary)

    assert summary == {"http_status": 500, "response_length": len(body)}
    assert "do-not-log-this" not in summary_text
    assert "full exchange response" not in summary_text


class FakeObject:
    def __init__(self, **values):
        self.__dict__.update(values)


def test_summarize_telegram_update_excludes_message_text():
    update = FakeObject(
        update_id=123,
        effective_chat=FakeObject(id=-100123, type="supergroup"),
        effective_user=FakeObject(id=456),
        effective_message=FakeObject(
            message_id=789,
            text="api-key-secret-passphrase-should-not-appear",
        ),
        callback_query=None,
    )

    summary = summarize_telegram_update(update)
    summary_text = str(summary)

    assert summary == {
        "update_id": 123,
        "chat_id": -100123,
        "chat_type": "supergroup",
        "telegram_id": 456,
        "message_id": 789,
        "has_text": True,
        "has_callback_query": False,
    }
    assert "api-key-secret-passphrase-should-not-appear" not in summary_text
