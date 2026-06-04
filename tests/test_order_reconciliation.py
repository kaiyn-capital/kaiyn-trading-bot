from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from settings_factory import make_settings

from app.audit import summarize_identifier
from app.bitget_client import BitgetAPIClient
from app.bitget_errors import BitgetAPIError
from app.bot import TelegramBot
from app.order_flow import build_client_order_id
from app.order_reconciliation import PendingOrderReconciliationService


def make_pending(**overrides):
    data = {
        "id": 1,
        "token": "tok_reconcile",
        "user_id": 10,
        "telegram_id": 123,
        "symbol": "BTCUSDT",
        "direction": "long",
        "order_mode": "limit",
        "limit_price": 50000.0,
        "quantity": 0.01,
        "updated_at": datetime.utcnow() - timedelta(minutes=20),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_user(**overrides):
    data = {
        "id": 10,
        "telegram_id": 123,
        "is_api_connected": True,
        "encrypted_api_key": "api",
        "encrypted_secret_key": "secret",
        "encrypted_passphrase": "pass",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_order(**overrides):
    data = {
        "symbol": "BTCUSDT",
        "size": "0.01",
        "orderId": "order_1",
        "clientOid": build_client_order_id("tok_reconcile"),
        "baseVolume": "0.01",
        "priceAvg": "50100",
        "fee": "-0.01",
        "price": "50000",
        "state": "filled",
        "side": "buy",
        "orderType": "limit",
        "quoteVolume": "501",
    }
    data.update(overrides)
    return data


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


class FakeUserRepo:
    def __init__(self, user=None):
        self.user = user or make_user()

    async def get_user_by_telegram_id(self, telegram_id):
        return self.user if self.user and self.user.telegram_id == telegram_id else None


class FakePendingOrderRepo:
    def __init__(self, pending_orders=None):
        self.pending_orders = pending_orders or []
        self.executed = []
        self.failed = []
        self.cutoffs = []

    async def get_stale_processing_orders(self, cutoff, limit):
        self.cutoffs.append({"cutoff": cutoff, "limit": limit})
        return self.pending_orders[:limit]

    async def mark_executed(self, token, trade_id):
        self.executed.append({"token": token, "trade_id": trade_id})
        return True

    async def mark_failed(self, token, error_message):
        self.failed.append({"token": token, "error_message": error_message})
        return True


class FakeTradeRepo:
    def __init__(self, trade=None):
        self.trade = trade
        self.created = []
        self.updated = []
        self.next_id = 77

    async def get_by_client_order_id(self, client_order_id):
        if self.trade and self.trade.client_order_id == client_order_id:
            return self.trade
        return None

    async def create_trade(self, **kwargs):
        trade = SimpleNamespace(id=self.next_id, bitget_order_id=None, **kwargs)
        self.next_id += 1
        self.trade = trade
        self.created.append(kwargs)
        return trade

    async def update_trade_result(self, trade_id, bitget_order_id, status, **kwargs):
        self.updated.append(
            {
                "trade_id": trade_id,
                "bitget_order_id": bitget_order_id,
                "status": status,
                **kwargs,
            }
        )
        return True


class FakeTradeManager:
    def __init__(self, *, detail=None, history=None, detail_exc=None, history_exc=None):
        self.detail = detail
        self.history = history
        self.detail_exc = detail_exc
        self.history_exc = history_exc
        self.status_calls = []
        self.history_calls = []

    async def get_order_status(self, *args, **kwargs):
        self.status_calls.append({"args": args, "kwargs": kwargs})
        if self.detail_exc:
            raise self.detail_exc
        return self.detail if self.detail is not None else {"code": "00000", "data": make_order()}

    async def get_order_history(self, *args, **kwargs):
        self.history_calls.append({"args": args, "kwargs": kwargs})
        if self.history_exc:
            raise self.history_exc
        return self.history if self.history is not None else {"code": "00000", "data": {"entrustedList": []}}


class FakeSystemLogRepo:
    def __init__(self):
        self.logs = []

    async def log(self, **kwargs):
        self.logs.append(kwargs)


class FakeAlertManager:
    def __init__(self):
        self.alerts = []
        self.db_failures = []
        self.backup_problems = []
        self.maintenance_problems = []

    async def send_alert(self, text, alert_key=None, cooldown_seconds=None):
        self.alerts.append(
            {
                "text": text,
                "alert_key": alert_key,
                "cooldown_seconds": cooldown_seconds,
            }
        )
        return True

    async def alert_db_failure(self, source, error=None):
        self.db_failures.append({"source": source, "error": error})

    async def alert_backup_problem(self, message):
        self.backup_problems.append(message)

    async def alert_maintenance_problem(self, message):
        self.maintenance_problems.append(message)


def make_service(
    *,
    pending_orders=None,
    user=None,
    trade=None,
    trade_manager=None,
    pending_order_repo=None,
    trade_repo=None,
    bot=None,
    system_log_repo=None,
    alert_manager=None,
):
    pending_order_repo = pending_order_repo or FakePendingOrderRepo(pending_orders)
    trade_repo = trade_repo or FakeTradeRepo(trade)
    bot = bot or FakeBot()
    system_log_repo = system_log_repo or FakeSystemLogRepo()
    alert_manager = alert_manager or FakeAlertManager()
    service = PendingOrderReconciliationService(
        bot=bot,
        user_repo=FakeUserRepo(user),
        pending_order_repo=pending_order_repo,
        trade_repo=trade_repo,
        trade_manager=trade_manager or FakeTradeManager(),
        system_log_repo=system_log_repo,
        alert_manager=alert_manager,
    )
    return (
        service,
        pending_order_repo,
        trade_repo,
        trade_manager or service.trade_manager,
        bot,
        system_log_repo,
        alert_manager,
    )


@pytest.mark.asyncio
async def test_reconcile_no_stale_processing_does_not_call_bitget():
    trade_manager = FakeTradeManager()
    service, _pending_repo, _trade_repo, _manager, _bot, _logs, _alerts = make_service(
        pending_orders=[],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.scanned == 0
    assert trade_manager.status_calls == []
    assert trade_manager.history_calls == []


@pytest.mark.asyncio
async def test_reconcile_uses_pending_token_client_order_id():
    pending = make_pending(token="tok_ready")
    trade_manager = FakeTradeManager(detail={"code": "00000", "data": make_order(clientOid="KTB_tok_ready")})
    service, pending_repo, _trade_repo, _manager, _bot, _logs, _alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.recovered == 1
    assert trade_manager.status_calls[-1]["kwargs"]["client_order_id"] == "KTB_tok_ready"
    assert trade_manager.status_calls[-1]["kwargs"]["product_type"] == "USDT-FUTURES"
    assert pending_repo.executed == [{"token": "tok_ready", "trade_id": 77}]


@pytest.mark.asyncio
async def test_reconcile_live_order_marks_trade_pending_and_pending_executed():
    pending = make_pending()
    existing_trade = SimpleNamespace(id=42, client_order_id=build_client_order_id(pending.token), bitget_order_id=None)
    trade_manager = FakeTradeManager(detail={"code": "00000", "data": make_order(state="live", baseVolume="0")})
    service, pending_repo, trade_repo, _manager, _bot, _logs, _alerts = make_service(
        pending_orders=[pending],
        trade=existing_trade,
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.recovered == 1
    assert trade_repo.updated[-1]["status"] == "pending"
    assert pending_repo.executed == [{"token": pending.token, "trade_id": 42}]


@pytest.mark.asyncio
async def test_reconcile_filled_order_updates_trade_fields():
    pending = make_pending()
    trade_manager = FakeTradeManager(detail={"code": "00000", "data": make_order(state="filled")})
    service, pending_repo, trade_repo, _manager, _bot, _logs, _alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.recovered == 1
    assert trade_repo.created[-1]["client_order_id"] == build_client_order_id(pending.token)
    assert trade_repo.updated[-1]["status"] == "filled"
    assert trade_repo.updated[-1]["filled_quantity"] == Decimal("0.01")
    assert trade_repo.updated[-1]["avg_price"] == Decimal("50100.0")
    assert trade_repo.updated[-1]["total_amount"] == Decimal("501.0")
    assert trade_repo.updated[-1]["fee"] == Decimal("-0.01")
    assert pending_repo.executed == [{"token": pending.token, "trade_id": 77}]


@pytest.mark.asyncio
async def test_reconcile_filled_order_float_values_use_string_decimal_conversion():
    pending = make_pending()
    trade_manager = FakeTradeManager(
        detail={
            "code": "00000",
            "data": make_order(
                state="filled",
                baseVolume=0.1,
                priceAvg=50100.25,
                quoteVolume=5010.5,
                fee=-0.01,
            ),
        }
    )
    service, pending_repo, trade_repo, _manager, _bot, _logs, _alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.recovered == 1
    assert trade_repo.updated[-1]["filled_quantity"] == Decimal("0.1")
    assert trade_repo.updated[-1]["avg_price"] == Decimal("50100.25")
    assert trade_repo.updated[-1]["total_amount"] == Decimal("5010.5")
    assert trade_repo.updated[-1]["fee"] == Decimal("-0.01")
    assert pending_repo.executed == [{"token": pending.token, "trade_id": 77}]


@pytest.mark.asyncio
async def test_reconcile_filled_order_none_values_keep_defaults_and_optional_nones():
    pending = make_pending()
    trade_manager = FakeTradeManager(
        detail={
            "code": "00000",
            "data": make_order(
                state="filled",
                baseVolume=None,
                priceAvg=None,
                quoteVolume=None,
                fee=None,
            ),
        }
    )
    service, pending_repo, trade_repo, _manager, _bot, _logs, _alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.recovered == 1
    assert trade_repo.updated[-1]["filled_quantity"] == Decimal("0")
    assert trade_repo.updated[-1]["avg_price"] is None
    assert trade_repo.updated[-1]["total_amount"] is None
    assert trade_repo.updated[-1]["fee"] == Decimal("0")
    assert pending_repo.executed == [{"token": pending.token, "trade_id": 77}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("baseVolume", ""),
        ("priceAvg", "not-a-number"),
        ("quoteVolume", object()),
        ("fee", []),
    ],
)
async def test_reconcile_invalid_numeric_trade_data_defers_and_alerts_admin(field_name, field_value):
    pending = make_pending()
    order = make_order(state="filled")
    order[field_name] = field_value
    trade_manager = FakeTradeManager(detail={"code": "00000", "data": order})
    service, pending_repo, trade_repo, _manager, bot, logs, alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.deferred == 1
    assert pending_repo.failed == []
    assert pending_repo.executed == []
    assert trade_repo.updated == []
    assert bot.messages == []
    assert alerts.alerts
    assert logs.logs[-1]["extra_data"]["reason"] == "invalid_numeric_trade_data"
    assert logs.logs[-1]["extra_data"]["error"]


@pytest.mark.asyncio
async def test_reconcile_cancelled_order_marks_failed_and_notifies_user():
    pending = make_pending()
    trade_manager = FakeTradeManager(detail={"code": "00000", "data": make_order(state="canceled")})
    service, pending_repo, trade_repo, _manager, bot, _logs, _alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.failed == 1
    assert trade_repo.updated[-1]["status"] == "cancelled"
    assert pending_repo.failed[-1]["token"] == pending.token
    assert "重新按一次" in pending_repo.failed[-1]["error_message"]
    assert "重新按一次" in bot.messages[-1]["text"]


@pytest.mark.asyncio
async def test_reconcile_detail_not_found_uses_history_order():
    pending = make_pending()
    not_found = BitgetAPIError(code="25204", message="Order does not exist")
    trade_manager = FakeTradeManager(
        detail_exc=not_found,
        history={"code": "00000", "data": {"entrustedList": [make_order(status="filled", state=None)]}},
    )
    service, pending_repo, trade_repo, _manager, _bot, _logs, _alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.recovered == 1
    assert trade_manager.history_calls[-1]["kwargs"]["client_order_id"] == build_client_order_id(pending.token)
    assert trade_repo.updated[-1]["status"] == "filled"
    assert pending_repo.executed == [{"token": pending.token, "trade_id": 77}]


@pytest.mark.asyncio
async def test_reconcile_detail_and_history_not_found_marks_failed_without_new_trade():
    pending = make_pending()
    existing_trade = SimpleNamespace(id=42, client_order_id=build_client_order_id(pending.token), bitget_order_id=None)
    not_found = BitgetAPIError(code="25204", message="Order does not exist")
    trade_manager = FakeTradeManager(
        detail_exc=not_found,
        history={"code": "00000", "data": {"entrustedList": []}},
    )
    service, pending_repo, trade_repo, _manager, bot, _logs, _alerts = make_service(
        pending_orders=[pending],
        trade=existing_trade,
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.failed == 1
    assert trade_repo.created == []
    assert trade_repo.updated[-1]["status"] == "failed"
    assert pending_repo.failed[-1]["token"] == pending.token
    assert "重新按一次" in bot.messages[-1]["text"]


@pytest.mark.asyncio
async def test_reconcile_unknown_exchange_status_defers_with_diagnostic_context():
    pending = make_pending()
    existing_trade = SimpleNamespace(id=42, client_order_id=build_client_order_id(pending.token), bitget_order_id=None)
    trade_manager = FakeTradeManager(detail={"code": "00000", "data": make_order(state="mystery_status")})
    service, pending_repo, trade_repo, _manager, bot, logs, alerts = make_service(
        pending_orders=[pending],
        trade=existing_trade,
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.deferred == 1
    assert summary.recovered == 0
    assert summary.failed == 0
    assert pending_repo.executed == []
    assert pending_repo.failed == []
    assert trade_repo.updated == []
    assert trade_repo.created == []
    assert bot.messages == []
    assert alerts.alerts
    assert "unknown order status" in alerts.alerts[-1]["text"]
    assert "Exchange Status：mystery_status" in alerts.alerts[-1]["text"]
    assert "Order Summary：" in alerts.alerts[-1]["text"]
    assert (
        logs.logs[-1]["message"] == "Cannot reconcile processing order because Bitget returned an unknown order status"
    )
    assert logs.logs[-1]["extra_data"]["reason"] == "unknown_exchange_status"
    assert logs.logs[-1]["extra_data"]["exchange_status"] == "mystery_status"
    assert logs.logs[-1]["extra_data"]["order"] == {
        "orderId": summarize_identifier("order_1"),
        "clientOid": summarize_identifier(build_client_order_id(pending.token)),
        "state": "mystery_status",
        "status": None,
        "orderType": "limit",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("history_payload", "expected_types"),
    [
        (
            {"code": "00000", "data": {"entrustedList": {}}},
            {"entrusted_list_type": "dict"},
        ),
        (
            {"code": "00000", "data": {"entrustedList": "bad-shape"}},
            {"entrusted_list_type": "str"},
        ),
        (
            {"code": "00000", "data": "bad-shape"},
            {"data_type": "str"},
        ),
        (
            {"code": "00000", "data": {"entrustedList": ["bad-entry"]}},
            {"order_type": "str"},
        ),
    ],
)
async def test_reconcile_invalid_history_payload_defers_and_alerts_admin(history_payload, expected_types):
    pending = make_pending()
    not_found = BitgetAPIError(code="25204", message="Order does not exist")
    trade_manager = FakeTradeManager(detail_exc=not_found, history=history_payload)
    service, pending_repo, trade_repo, _manager, bot, logs, alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.deferred == 1
    assert pending_repo.failed == []
    assert pending_repo.executed == []
    assert trade_repo.created == []
    assert trade_repo.updated == []
    assert bot.messages == []
    assert alerts.alerts
    assert "history payload is invalid" in alerts.alerts[-1]["text"]
    assert logs.logs[-1]["message"] == "Cannot reconcile processing order because Bitget history payload is invalid"
    assert logs.logs[-1]["extra_data"]["reason"] == "invalid_history_payload"
    for key, value in expected_types.items():
        assert logs.logs[-1]["extra_data"][key] == value


@pytest.mark.asyncio
async def test_reconcile_market_order_ignores_invalid_price_field_when_price_is_unused():
    pending = make_pending(order_mode="market", limit_price=None)
    trade_manager = FakeTradeManager(
        detail={
            "code": "00000",
            "data": make_order(state="filled", orderType="market", price=object()),
        }
    )
    service, pending_repo, trade_repo, _manager, _bot, _logs, _alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.recovered == 1
    assert trade_repo.created[-1]["order_type"] == "market"
    assert trade_repo.created[-1]["price"] is None
    assert pending_repo.executed == [{"token": pending.token, "trade_id": 77}]


@pytest.mark.asyncio
async def test_reconcile_network_error_keeps_processing_and_alerts_admin():
    pending = make_pending()
    network_error = BitgetAPIError(code="network_error", message="Bitget network request error")
    trade_manager = FakeTradeManager(detail_exc=network_error)
    service, pending_repo, trade_repo, _manager, bot, _logs, alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.deferred == 1
    assert pending_repo.failed == []
    assert pending_repo.executed == []
    assert trade_repo.updated == []
    assert bot.messages == []
    assert alerts.alerts


@pytest.mark.asyncio
async def test_reconcile_unexpected_query_error_keeps_processing_and_alerts_admin():
    pending = make_pending()
    trade_manager = FakeTradeManager(detail_exc=RuntimeError("local parser broke"))
    service, pending_repo, trade_repo, _manager, bot, logs, alerts = make_service(
        pending_orders=[pending],
        trade_manager=trade_manager,
    )

    summary = await service.reconcile_stale_processing_orders(stale_after_seconds=900, limit=10)

    assert summary.deferred == 1
    assert pending_repo.failed == []
    assert pending_repo.executed == []
    assert trade_repo.updated == []
    assert bot.messages == []
    assert alerts.alerts
    assert logs.logs[-1]["extra_data"]["exception_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_bitget_get_order_info_includes_product_type(monkeypatch):
    client = BitgetAPIClient("api", "secret", "pass")
    calls = []

    async def fake_make_request(method, endpoint, params=None, data=None):
        calls.append({"method": method, "endpoint": endpoint, "params": params, "data": data})
        return {"code": "00000", "data": {}}

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    await client.get_order_info("BTCUSDT", client_order_id="KTB_tok")

    assert calls[-1]["endpoint"] == "/api/v2/mix/order/detail"
    assert calls[-1]["params"]["productType"] == "USDT-FUTURES"
    assert calls[-1]["params"]["clientOid"] == "KTB_tok"

    await client.close()


@pytest.mark.asyncio
async def test_bitget_get_order_history_supports_client_order_id(monkeypatch):
    client = BitgetAPIClient("api", "secret", "pass")
    calls = []

    async def fake_make_request(method, endpoint, params=None, data=None):
        calls.append({"method": method, "endpoint": endpoint, "params": params, "data": data})
        return {"code": "00000", "data": {"entrustedList": []}}

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    await client.get_order_history(symbol="BTCUSDT", client_order_id="KTB_tok", limit=20)

    assert calls[-1]["endpoint"] == "/api/v2/mix/order/orders-history"
    assert calls[-1]["params"]["productType"] == "USDT-FUTURES"
    assert calls[-1]["params"]["clientOid"] == "KTB_tok"
    assert calls[-1]["params"]["limit"] == "20"

    await client.close()


@pytest.mark.asyncio
async def test_health_monitor_triggers_pending_order_reconciler(monkeypatch):
    class FakeDb:
        async def health_check(self):
            return True

    class FakeMaintenance:
        is_problem = False
        message = "ok"

    class FakeBackup:
        is_problem = False
        message = "ok"

    class FakeReconciler:
        def __init__(self):
            self.calls = []

        async def reconcile_stale_processing_orders(self, **kwargs):
            self.calls.append(kwargs)

    backup_calls = []

    def fake_read_backup_health(**kwargs):
        backup_calls.append(kwargs)
        return FakeBackup()

    monkeypatch.setattr("app.bot.read_backup_health", fake_read_backup_health)

    maintenance_calls = []

    async def fake_read_maintenance_health(system_log_repo, **kwargs):
        maintenance_calls.append({"system_log_repo": system_log_repo, **kwargs})
        return FakeMaintenance()

    monkeypatch.setattr("app.bot.read_maintenance_health", fake_read_maintenance_health)
    reconciler = FakeReconciler()
    bot = SimpleNamespace(
        settings=make_settings(
            backup_stale_hours=48,
            maintenance_stale_hours=48,
            pending_order_reconcile_after_seconds=1234,
            pending_order_reconcile_limit=3,
        ),
        user_repo=SimpleNamespace(db=FakeDb()),
        system_log_repo=SimpleNamespace(),
        alert_manager=FakeAlertManager(),
        pending_order_reconciler=reconciler,
    )

    await TelegramBot._run_health_monitor_once(bot)

    assert backup_calls == [{"stale_hours": 48}]
    assert maintenance_calls == [{"system_log_repo": bot.system_log_repo, "stale_hours": 48}]
    assert reconciler.calls == [{"stale_after_seconds": 1234, "limit": 3}]
