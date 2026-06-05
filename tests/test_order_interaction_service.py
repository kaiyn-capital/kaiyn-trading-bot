from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from settings_factory import make_settings

from app.order_interaction_service import TelegramOrderFlowService
from app.repository_types import SignalRecordSnapshot


def make_signal_record(public_id: str, **overrides):
    data = {
        "id": 1,
        "public_id": public_id,
        "user_id": 7,
        "sender_telegram_id": 123456,
        "sender_username": "admin",
        "symbol": "BTCUSDT",
        "direction": "long",
        "entry_lower": 80200,
        "entry_upper": 81000,
        "stop_loss": 79000,
        "take_profit_levels": [83000],
        "remark": "",
        "signal_text": "signal text",
        "granularity": "1H",
        "status": "sent",
        "chart_status": "generated",
        "chart_error": None,
        "created_at": datetime(2026, 5, 18, 12, 0, 0),
        "updated_at": datetime(2026, 5, 18, 12, 0, 0),
        "confirmed_at": datetime(2026, 5, 18, 12, 0, 0),
    }
    data.update(overrides)
    return SignalRecordSnapshot(**data)


class FakeQuery:
    def __init__(self):
        self.answers = []

    async def answer(self, text=None):
        self.answers.append(text)


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class FakeAuditOwner:
    def __init__(self):
        self.audit_events = []

    async def _audit_action(self, user, action, details=None):
        self.audit_events.append({"action": action, "details": details or {}})


class FakeConfirmPendingOrderRepo:
    def __init__(self, claim_result=None, cancel_status="missing"):
        self.claim_result = claim_result or (None, "missing")
        self.cancel_status = cancel_status
        self.claims = []
        self.cancellations = []
        self.failed = []

    async def claim_pending_order(self, token, telegram_id):
        self.claims.append({"token": token, "telegram_id": telegram_id})
        return self.claim_result

    async def cancel_pending_order(self, token, telegram_id):
        self.cancellations.append({"token": token, "telegram_id": telegram_id})
        return self.cancel_status

    async def mark_failed(self, token, error_message):
        self.failed.append({"token": token, "error_message": error_message})
        return True

    async def create_pending_order(self, **kwargs):
        raise AssertionError("pending order should not be created")


class FakeSignalRecordRepo:
    def __init__(self, records=None):
        self.records = records or {}

    async def get_by_public_id(self, public_id: str) -> SignalRecordSnapshot | None:
        record = self.records.get(public_id.lower())
        if isinstance(record, SignalRecordSnapshot):
            return record
        if isinstance(record, dict):
            return make_signal_record(public_id.lower(), **record)
        return None


class RecordingOrderFlowService(TelegramOrderFlowService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.executions = []

    async def execute_order(self, request):
        self.executions.append(request)
        return True


class FakeUserRepo:
    def __init__(self, **overrides):
        self.overrides = overrides

    async def get_user_by_telegram_id(self, telegram_id):
        user_data = {
            "id": 7,
            "telegram_id": telegram_id,
            "is_api_connected": True,
            "encrypted_api_key": "api",
            "encrypted_secret_key": "secret",
            "encrypted_passphrase": "passphrase",
            "fixed_risk_amount": 10,
            "daily_trade_limit": 10,
            "max_position_size": None,
        }
        user_data.update(self.overrides)
        return SimpleNamespace(**user_data)


class RejectingRulesTradeManager:
    def __init__(self):
        self.contract_rule_calls = []
        self.market_price_calls = []
        self.market_order_calls = []
        self.limit_order_calls = []

    async def get_contract_rules(self, symbol):
        self.contract_rule_calls.append(symbol)
        return {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "symbolStatus": "normal",
            "minTradeNum": "1",
            "minTradeUSDT": "5",
            "sizeMultiplier": "0.001",
            "volumePlace": "3",
            "pricePlace": "1",
            "priceEndStep": "1",
            "maxMarketOrderQty": "100",
            "maxOrderQty": "100",
        }

    async def get_market_price(self, symbol):
        self.market_price_calls.append(symbol)
        return 80000

    async def place_market_order(self, *args, **kwargs):
        self.market_order_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("market order should not be placed")

    async def place_limit_order(self, *args, **kwargs):
        self.limit_order_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("limit order should not be placed")


class UnusedTradeRepo:
    async def create_trade(self, **kwargs):
        raise AssertionError("trade should not be created")

    async def create_trade_with_daily_limit(self, **kwargs):
        raise AssertionError("trade should not be created")

    async def count_daily_non_failed_trades(self, user_id, day_start_utc):
        return 0


class RecordingPendingOrderRepo(FakeConfirmPendingOrderRepo):
    def __init__(self):
        super().__init__()
        self.created = []

    async def create_pending_order(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=55, token="tok_created", **kwargs)


class CountingTradeRepo(UnusedTradeRepo):
    def __init__(self, daily_count=0):
        self.daily_count = daily_count

    async def count_daily_non_failed_trades(self, user_id, day_start_utc):
        return self.daily_count


class RecordingRulesTradeManager(RejectingRulesTradeManager):
    async def place_market_order(self, *args, **kwargs):
        self.market_order_calls.append({"args": args, "kwargs": kwargs})
        return {"code": "00000", "data": {"orderId": "market-order"}}

    async def place_limit_order(self, *args, **kwargs):
        self.limit_order_calls.append({"args": args, "kwargs": kwargs})
        return {"code": "00000", "data": {"orderId": "limit-order"}}


class NoBitgetTradeManager:
    def __init__(self):
        self.contract_rule_calls = []
        self.market_price_calls = []

    async def get_contract_rules(self, symbol):
        self.contract_rule_calls.append(symbol)
        raise AssertionError("Bitget rules should not be fetched")

    async def get_market_price(self, symbol):
        self.market_price_calls.append(symbol)
        raise AssertionError("Bitget price should not be fetched")


class UnexpectedRulesTradeManager(NoBitgetTradeManager):
    async def get_contract_rules(self, symbol):
        self.contract_rule_calls.append(symbol)
        raise RuntimeError("local cache corrupted")


class PermissiveRulesTradeManager(RejectingRulesTradeManager):
    async def get_contract_rules(self, symbol):
        self.contract_rule_calls.append(symbol)
        return {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "symbolStatus": "normal",
            "minTradeNum": "0.001",
            "minTradeUSDT": "5",
            "sizeMultiplier": "0.001",
            "volumePlace": "3",
            "pricePlace": "1",
            "priceEndStep": "1",
            "maxMarketOrderQty": "100",
            "maxOrderQty": "100",
        }


class RecordingSystemLogRepo:
    def __init__(self):
        self.logs = []

    async def log(self, **kwargs):
        self.logs.append(kwargs)


class RecordingFailureAlert:
    def __init__(self):
        self.calls = []

    async def __call__(self, classified_error, source, details=None):
        self.calls.append({"classified_error": classified_error, "source": source, "details": details})


class SuccessfulTradeRepo(CountingTradeRepo):
    def __init__(self, daily_count=0):
        super().__init__(daily_count=daily_count)
        self.created_with_daily_limit = []
        self.updated = []

    async def create_trade_with_daily_limit(self, **kwargs):
        self.created_with_daily_limit.append(kwargs)
        return SimpleNamespace(id=77)

    async def update_trade_result(self, trade_id, **kwargs):
        self.updated.append({"trade_id": trade_id, **kwargs})


class FakeSystemLogRepo:
    async def log(self, **kwargs):
        raise AssertionError("system log should not be written for validation failure")


def make_user():
    return SimpleNamespace(telegram_id=123456)


def make_pending_order(**overrides):
    pending_order = {
        "symbol": "BTCUSDT",
        "direction": "short",
        "quantity": 0.02,
        "stop_loss": 81700,
        "position_value": 1604,
        "current_price": 80500,
        "order_mode": "limit",
        "limit_price": 80200,
    }
    pending_order.update(overrides)
    return SimpleNamespace(**pending_order)


def make_service(
    *,
    pending_order_repo=None,
    service_class=TelegramOrderFlowService,
    user_repo=None,
    trade_repo=None,
    trade_manager=None,
    system_log_repo=None,
    failure_alert_handler=None,
    signal_record_repo=None,
    settings=None,
):
    bot = FakeBot()
    audit_owner = FakeAuditOwner()
    service = service_class(
        bot=bot,
        user_repo=user_repo or SimpleNamespace(),
        pending_order_repo=pending_order_repo or FakeConfirmPendingOrderRepo(),
        trade_repo=trade_repo or SimpleNamespace(),
        trade_manager=trade_manager or SimpleNamespace(),
        system_log_repo=system_log_repo or SimpleNamespace(),
        audit_owner=audit_owner,
        failure_alert_handler=failure_alert_handler,
        signal_record_repo=signal_record_repo,
        settings=settings or make_settings(),
    )
    return service, bot, audit_owner


@pytest.mark.asyncio
async def test_confirm_pending_order_missing_token():
    repo = FakeConfirmPendingOrderRepo(claim_result=(None, "missing"))
    service, bot, audit_owner = make_service(pending_order_repo=repo, service_class=RecordingOrderFlowService)

    await service.handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_missing")

    assert repo.claims == [{"token": "tok_missing", "telegram_id": 123456}]
    assert not service.executions
    assert "找不到这笔待确认订单" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "pending_order_confirm"
    assert audit_owner.audit_events[-1]["details"]["status"] == "missing"
    assert audit_owner.audit_events[-1]["details"]["pending_order_token"] == "***sing"


@pytest.mark.asyncio
async def test_confirm_pending_order_expired_token():
    repo = FakeConfirmPendingOrderRepo(claim_result=(make_pending_order(), "expired"))
    service, bot, audit_owner = make_service(pending_order_repo=repo, service_class=RecordingOrderFlowService)

    await service.handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_expired")

    assert not service.executions
    assert "已过期" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["details"]["status"] == "expired"


@pytest.mark.parametrize("status", ["processing_by_other", "executed", "failed"])
@pytest.mark.asyncio
async def test_confirm_pending_order_non_processing_status_does_not_execute(status):
    repo = FakeConfirmPendingOrderRepo(claim_result=(make_pending_order(), status))
    service, bot, audit_owner = make_service(pending_order_repo=repo, service_class=RecordingOrderFlowService)

    await service.handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_status")

    assert not service.executions
    assert f"状态为 {status}" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["details"]["status"] == status


@pytest.mark.asyncio
async def test_confirm_pending_order_processing_executes_with_full_pending_data():
    repo = FakeConfirmPendingOrderRepo(claim_result=(make_pending_order(), "processing"))
    service, _bot, audit_owner = make_service(pending_order_repo=repo, service_class=RecordingOrderFlowService)

    await service.handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_ready")

    assert len(service.executions) == 1
    request = service.executions[0]
    assert request.symbol == "BTCUSDT"
    assert request.direction == "short"
    assert request.quantity == Decimal("0.02")
    assert request.stop_loss == Decimal("81700")
    assert request.position_value == Decimal("1604")
    assert request.current_price == Decimal("80500")
    assert request.order_mode == "limit"
    assert request.limit_price == Decimal("80200")
    assert request.pending_order_token == "tok_ready"
    assert audit_owner.audit_events[-1]["action"] == "pending_order_confirm"
    assert audit_owner.audit_events[-1]["details"]["status"] == "processing"
    assert audit_owner.audit_events[-1]["details"]["pending_order_token"] == "***eady"


@pytest.mark.asyncio
async def test_cancel_pending_order_cancelled_status():
    repo = FakeConfirmPendingOrderRepo(cancel_status="cancelled")
    service, bot, audit_owner = make_service(pending_order_repo=repo)
    query = FakeQuery()

    await service.handle_cancel_pending_order_callback(query, make_user(), "cancel_order_tok_cancel")

    assert repo.cancellations == [{"token": "tok_cancel", "telegram_id": 123456}]
    assert query.answers == ["已取消下单"]
    assert "已取消下单" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "pending_order_cancel"
    assert audit_owner.audit_events[-1]["details"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_pending_order_missing_status():
    repo = FakeConfirmPendingOrderRepo(cancel_status="missing")
    service, bot, audit_owner = make_service(pending_order_repo=repo)

    await service.handle_cancel_pending_order_callback(FakeQuery(), make_user(), "cancel_order_tok_missing")

    assert "找不到这笔待确认订单" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["details"]["status"] == "missing"


@pytest.mark.asyncio
async def test_cancel_pending_order_non_pending_status():
    repo = FakeConfirmPendingOrderRepo(cancel_status="processing")
    service, bot, audit_owner = make_service(pending_order_repo=repo)

    await service.handle_cancel_pending_order_callback(FakeQuery(), make_user(), "cancel_order_tok_processing")

    assert "状态为 processing，无法取消" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["details"]["status"] == "processing"


@pytest.mark.asyncio
async def test_place_order_blocks_when_daily_trade_limit_reached():
    trade_manager = NoBitgetTradeManager()
    system_log_repo = RecordingSystemLogRepo()
    failure_alert = RecordingFailureAlert()
    signal_record = {
        "symbol": "BTCUSDT",
        "direction": "long",
        "entry_lower": 80200,
        "entry_upper": 81000,
        "stop_loss": 79000,
        "status": "sent",
    }
    signal_repo = FakeSignalRecordRepo({"tok_daily": signal_record})
    service, bot, audit_owner = make_service(
        pending_order_repo=FakeConfirmPendingOrderRepo(),
        user_repo=FakeUserRepo(daily_trade_limit=3),
        trade_repo=CountingTradeRepo(daily_count=3),
        trade_manager=trade_manager,
        system_log_repo=system_log_repo,
        failure_alert_handler=failure_alert,
        signal_record_repo=signal_repo,
    )

    await service.handle_place_order_callback(
        FakeQuery(),
        make_user(),
        "place_order_market_tok_daily",
    )

    assert "今日下单次数已达上限" in bot.messages[-1]["text"]
    assert trade_manager.contract_rule_calls == []
    assert failure_alert.calls == []
    assert audit_owner.audit_events[-1]["details"]["reason"] == "daily_trade_limit_exceeded"
    assert audit_owner.audit_events[-1]["details"]["daily_trade_count"] == 3
    assert system_log_repo.logs[-1]["extra_data"]["reason"] == "daily_trade_limit_exceeded"


@pytest.mark.asyncio
async def test_place_order_blocks_when_preview_position_exceeds_cap():
    pending_order_repo = FakeConfirmPendingOrderRepo()
    system_log_repo = RecordingSystemLogRepo()
    failure_alert = RecordingFailureAlert()
    signal_record = {
        "symbol": "BTCUSDT",
        "direction": "long",
        "entry_lower": 80200,
        "entry_upper": 81000,
        "stop_loss": 79000,
        "status": "sent",
    }
    signal_repo = FakeSignalRecordRepo({"tok_position": signal_record})
    service, bot, audit_owner = make_service(
        pending_order_repo=pending_order_repo,
        user_repo=FakeUserRepo(fixed_risk_amount=1000, max_position_size=500),
        trade_repo=CountingTradeRepo(daily_count=0),
        trade_manager=PermissiveRulesTradeManager(),
        system_log_repo=system_log_repo,
        failure_alert_handler=failure_alert,
        signal_record_repo=signal_repo,
        settings=make_settings(max_position_size=Decimal("1000")),
    )

    await service.handle_place_order_callback(
        FakeQuery(),
        make_user(),
        "place_order_market_tok_position",
    )

    assert "仓位超过风险上限" in bot.messages[-1]["text"]
    assert pending_order_repo.failed == []
    assert failure_alert.calls == []
    assert audit_owner.audit_events[-1]["details"]["reason"] == "position_size_limit_exceeded"
    assert audit_owner.audit_events[-1]["details"]["position_limit"] == "500"
    assert system_log_repo.logs[-1]["extra_data"]["position_limit"] == "500"


@pytest.mark.asyncio
async def test_place_order_unexpected_error_is_not_reported_as_bitget_failure():
    failure_alert = RecordingFailureAlert()
    signal_repo = FakeSignalRecordRepo(
        {
            "tok_unexpected": {
                "symbol": "BTCUSDT",
                "direction": "long",
                "entry_lower": 80200,
                "entry_upper": 81000,
                "stop_loss": 79000,
                "status": "sent",
            }
        }
    )
    service, bot, audit_owner = make_service(
        user_repo=FakeUserRepo(),
        trade_repo=CountingTradeRepo(daily_count=0),
        trade_manager=UnexpectedRulesTradeManager(),
        system_log_repo=RecordingSystemLogRepo(),
        failure_alert_handler=failure_alert,
        signal_record_repo=signal_repo,
    )

    await service.handle_place_order_callback(
        FakeQuery(),
        make_user(),
        "place_order_market_tok_unexpected",
    )

    assert failure_alert.calls == []
    assert "发生未知错误" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "pending_order_create_failed"
    assert audit_owner.audit_events[-1]["details"]["error_category"] == "unexpected"


@pytest.mark.asyncio
async def test_place_order_blocks_when_signal_cancelled_expired_or_not_found():
    # 1. Signal not found
    signal_repo = FakeSignalRecordRepo({})
    service, bot, audit_owner = make_service(
        user_repo=FakeUserRepo(),
        signal_record_repo=signal_repo,
    )
    await service.handle_place_order_callback(
        FakeQuery(),
        make_user(),
        "place_order_market_tok_missing",
    )
    assert "该交易信号不存在或已过期" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "order_place_blocked"
    assert audit_owner.audit_events[-1]["details"]["reason"] == "signal_not_found"

    # 2. Signal cancelled
    signal_repo = FakeSignalRecordRepo(
        {
            "tok_cancelled": {
                "symbol": "BTCUSDT",
                "direction": "long",
                "entry_lower": 80200,
                "entry_upper": 81000,
                "stop_loss": 79000,
                "status": "cancelled",
            }
        }
    )
    service, bot, audit_owner = make_service(
        user_repo=FakeUserRepo(),
        signal_record_repo=signal_repo,
    )
    await service.handle_place_order_callback(
        FakeQuery(),
        make_user(),
        "place_order_market_tok_cancelled",
    )
    assert "该交易信号不存在或已过期" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "order_place_blocked"
    assert audit_owner.audit_events[-1]["details"]["reason"] == "signal_cancelled"

    # 3. Signal expired
    signal_repo = FakeSignalRecordRepo(
        {
            "tok_expired": {
                "symbol": "BTCUSDT",
                "direction": "long",
                "entry_lower": 80200,
                "entry_upper": 81000,
                "stop_loss": 79000,
                "status": "expired",
            }
        }
    )
    service, bot, audit_owner = make_service(
        user_repo=FakeUserRepo(),
        signal_record_repo=signal_repo,
    )
    await service.handle_place_order_callback(
        FakeQuery(),
        make_user(),
        "place_order_market_tok_expired",
    )
    assert "该交易信号不存在或已过期" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "order_place_blocked"
    assert audit_owner.audit_events[-1]["details"]["reason"] == "signal_expired"

    # 4. Signal preview pending
    signal_repo = FakeSignalRecordRepo(
        {
            "tok_preview": {
                "symbol": "BTCUSDT",
                "direction": "long",
                "entry_lower": 80200,
                "entry_upper": 81000,
                "stop_loss": 79000,
                "status": "preview_pending",
            }
        }
    )
    service, bot, audit_owner = make_service(
        user_repo=FakeUserRepo(),
        signal_record_repo=signal_repo,
    )
    await service.handle_place_order_callback(
        FakeQuery(),
        make_user(),
        "place_order_market_tok_preview",
    )
    assert "该交易信号不存在或已过期" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "order_place_blocked"
    assert audit_owner.audit_events[-1]["details"]["reason"] == "signal_preview_pending"


@pytest.mark.asyncio
async def test_execute_order_blocks_when_daily_trade_limit_reached_before_bitget():
    pending_order_repo = FakeConfirmPendingOrderRepo()
    trade_manager = NoBitgetTradeManager()
    system_log_repo = RecordingSystemLogRepo()
    failure_alert = RecordingFailureAlert()
    service, bot, audit_owner = make_service(
        pending_order_repo=pending_order_repo,
        user_repo=FakeUserRepo(daily_trade_limit=2),
        trade_repo=CountingTradeRepo(daily_count=2),
        trade_manager=trade_manager,
        system_log_repo=system_log_repo,
        failure_alert_handler=failure_alert,
    )

    result = await service.execute_order(
        SimpleNamespace(
            query=FakeQuery(),
            user=make_user(),
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
            current_price=80000,
            order_mode="market",
            limit_price=None,
            pending_order_token="tok_daily",
        )
    )

    assert result is False
    assert pending_order_repo.failed[-1]["token"] == "tok_daily"
    assert "今日下单次数已达上限" in pending_order_repo.failed[-1]["error_message"]
    assert "今日下单次数已达上限" in bot.messages[-1]["text"]
    assert trade_manager.contract_rule_calls == []
    assert failure_alert.calls == []
    assert audit_owner.audit_events[-1]["action"] == "order_risk_limit_failed"


@pytest.mark.asyncio
async def test_execute_order_blocks_when_confirmed_position_exceeds_cap():
    pending_order_repo = FakeConfirmPendingOrderRepo()
    trade_manager = PermissiveRulesTradeManager()
    system_log_repo = RecordingSystemLogRepo()
    failure_alert = RecordingFailureAlert()
    service, bot, audit_owner = make_service(
        pending_order_repo=pending_order_repo,
        user_repo=FakeUserRepo(max_position_size=500),
        trade_repo=UnusedTradeRepo(),
        trade_manager=trade_manager,
        system_log_repo=system_log_repo,
        failure_alert_handler=failure_alert,
        settings=make_settings(max_position_size=Decimal("1000")),
    )

    result = await service.execute_order(
        SimpleNamespace(
            query=FakeQuery(),
            user=make_user(),
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
            current_price=80000,
            order_mode="market",
            limit_price=None,
            pending_order_token="tok_position",
        )
    )

    assert result is False
    assert pending_order_repo.failed[-1]["token"] == "tok_position"
    assert "仓位超过风险上限" in pending_order_repo.failed[-1]["error_message"]
    assert "仓位超过风险上限" in bot.messages[-1]["text"]
    assert trade_manager.market_order_calls == []
    assert failure_alert.calls == []
    assert audit_owner.audit_events[-1]["details"]["reason"] == "position_size_limit_exceeded"


@pytest.mark.asyncio
async def test_execute_order_marks_pending_failed_when_second_validation_fails():
    pending_order_repo = FakeConfirmPendingOrderRepo()
    service, bot, audit_owner = make_service(
        pending_order_repo=pending_order_repo,
        user_repo=FakeUserRepo(),
        trade_repo=UnusedTradeRepo(),
        trade_manager=RejectingRulesTradeManager(),
        system_log_repo=FakeSystemLogRepo(),
    )
    query = FakeQuery()

    result = await service.execute_order(
        SimpleNamespace(
            query=query,
            user=make_user(),
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
            current_price=80000,
            order_mode="market",
            limit_price=None,
            pending_order_token="tok_validation",
        )
    )

    assert result is False
    assert pending_order_repo.failed[-1]["token"] == "tok_validation"
    assert "下单数量低于交易所最小值" in (pending_order_repo.failed[-1]["error_message"])
    assert "订单已不符合交易所规则" in bot.messages[-1]["text"]
    assert "下单数量低于交易所最小值" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "order_validation_failed"
    assert audit_owner.audit_events[-1]["details"]["pending_order_token"] == "***tion"


@pytest.mark.asyncio
async def test_execute_order_keeps_repository_calls_outside_bitget_calls():
    events = []
    active_repo_call = {"name": None}

    def begin_repo_call(name):
        assert active_repo_call["name"] is None
        active_repo_call["name"] = name
        events.append(f"repo:{name}:start")

    def end_repo_call(name):
        assert active_repo_call["name"] == name
        active_repo_call["name"] = None
        events.append(f"repo:{name}:end")

    def record_bitget_call(name):
        assert active_repo_call["name"] is None
        events.append(f"bitget:{name}")

    class SequencedUserRepo:
        async def get_user_by_telegram_id(self, telegram_id):
            begin_repo_call("user.get")
            end_repo_call("user.get")
            return SimpleNamespace(
                id=7,
                telegram_id=telegram_id,
                is_api_connected=True,
                encrypted_api_key="api",
                encrypted_secret_key="secret",
                encrypted_passphrase="passphrase",
                fixed_risk_amount=10,
                daily_trade_limit=10,
                max_position_size=None,
            )

    class SequencedTradeRepo:
        async def count_daily_non_failed_trades(self, user_id, day_start_utc):
            begin_repo_call("trade.count_daily_non_failed")
            end_repo_call("trade.count_daily_non_failed")
            return 0

        async def create_trade(self, **kwargs):
            raise AssertionError("daily limit path should create the trade")

        async def create_trade_with_daily_limit(self, **kwargs):
            begin_repo_call("trade.create_with_daily_limit")
            end_repo_call("trade.create_with_daily_limit")
            return SimpleNamespace(id=77)

        async def update_trade_result(self, trade_id, **kwargs):
            begin_repo_call("trade.update_result")
            end_repo_call("trade.update_result")

    class SequencedPendingOrderRepo(FakeConfirmPendingOrderRepo):
        async def mark_executed(self, token, trade_id):
            begin_repo_call("pending.mark_executed")
            end_repo_call("pending.mark_executed")
            return True

    class SequencedTradeManager(PermissiveRulesTradeManager):
        async def get_contract_rules(self, symbol):
            record_bitget_call("get_contract_rules")
            return await super().get_contract_rules(symbol)

        async def get_market_price(self, symbol):
            record_bitget_call("get_market_price")
            return await super().get_market_price(symbol)

        async def place_market_order(self, *args, **kwargs):
            record_bitget_call("place_market_order")
            return {"code": "00000", "data": {"orderId": "market-order"}}

        async def place_limit_order(self, *args, **kwargs):
            record_bitget_call("place_limit_order")
            raise AssertionError("limit order should not be placed")

    service, _bot, _audit_owner = make_service(
        pending_order_repo=SequencedPendingOrderRepo(),
        user_repo=SequencedUserRepo(),
        trade_repo=SequencedTradeRepo(),
        trade_manager=SequencedTradeManager(),
        system_log_repo=RecordingSystemLogRepo(),
    )

    result = await service.execute_order(
        SimpleNamespace(
            query=FakeQuery(),
            user=make_user(),
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
            current_price=80000,
            order_mode="market",
            limit_price=None,
            pending_order_token="tok_session",
        )
    )

    assert result is True
    assert active_repo_call["name"] is None
    assert events == [
        "repo:user.get:start",
        "repo:user.get:end",
        "repo:trade.count_daily_non_failed:start",
        "repo:trade.count_daily_non_failed:end",
        "bitget:get_contract_rules",
        "bitget:get_market_price",
        "repo:trade.create_with_daily_limit:start",
        "repo:trade.create_with_daily_limit:end",
        "bitget:place_market_order",
        "repo:trade.update_result:start",
        "repo:trade.update_result:end",
        "repo:pending.mark_executed:start",
        "repo:pending.mark_executed:end",
    ]
