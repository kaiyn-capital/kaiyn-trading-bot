from types import SimpleNamespace

import pytest

from app.bitget_errors import BitgetAPIError
from app.order_flow import OrderExecutionUnknownResult, execute_order
from app.order_interaction_service import ConfirmedOrderRequest, TelegramOrderFlowService


class FakeBitgetAPIError(Exception):
    def __init__(self, code, message, http_status=None, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data or {}


class FakeTradeRecord:
    id = 77


class FakeTradeRepo:
    def __init__(self):
        self.updated_results = []

    async def create_trade(self, **kwargs):
        self.created_trade = kwargs
        return FakeTradeRecord()

    async def create_trade_with_daily_limit(self, **kwargs):
        trade_kwargs = {
            key: value for key, value in kwargs.items() if key not in {"daily_trade_limit", "day_start_utc"}
        }
        return await self.create_trade(**trade_kwargs)

    async def count_daily_non_failed_trades(self, user_id, day_start_utc):
        return 0

    async def update_trade_result(self, trade_id, **kwargs):
        self.updated_results.append({"trade_id": trade_id, **kwargs})


class RejectingTradeManager:
    async def place_market_order(self, *args, **kwargs):
        raise FakeBitgetAPIError("43012", "insufficient balance")

    async def place_limit_order(self, *args, **kwargs):
        raise FakeBitgetAPIError("43012", "insufficient balance")


class TimeoutTradeManager:
    async def place_market_order(self, *args, **kwargs):
        raise BitgetAPIError("timeout", "Bitget request timeout")

    async def place_limit_order(self, *args, **kwargs):
        raise BitgetAPIError("timeout", "Bitget request timeout")


@pytest.mark.asyncio
async def test_execute_order_marks_trade_failed_with_classified_error():
    trade_repo = FakeTradeRepo()

    with pytest.raises(FakeBitgetAPIError):
        await execute_order(
            user_data=SimpleNamespace(id=7),
            trade_repo=trade_repo,
            trade_manager=RejectingTradeManager(),
            credentials=("api", "secret", "passphrase"),
            telegram_id=123,
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
        )

    failed_update = trade_repo.updated_results[-1]
    assert failed_update["trade_id"] == 77
    assert failed_update["status"] == "failed"
    assert "category=exchange_rejected" in failed_update["error_message"]
    assert "code=43012" in failed_update["error_message"]
    assert "insufficient balance" in failed_update["error_message"]


@pytest.mark.asyncio
async def test_execute_order_keeps_trade_pending_when_submission_result_unknown():
    trade_repo = FakeTradeRepo()

    with pytest.raises(OrderExecutionUnknownResult) as exc_info:
        await execute_order(
            user_data=SimpleNamespace(id=7),
            trade_repo=trade_repo,
            trade_manager=TimeoutTradeManager(),
            credentials=("api", "secret", "passphrase"),
            telegram_id=123,
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
            client_order_id="KTB_tok_timeout",
        )

    assert exc_info.value.trade_id == 77
    assert exc_info.value.client_order_id == "KTB_tok_timeout"
    assert exc_info.value.classified_error.is_retryable is True
    assert trade_repo.updated_results == []


class FakeUserRepo:
    async def get_user_by_telegram_id(self, telegram_id):
        return SimpleNamespace(
            id=7,
            telegram_id=telegram_id,
            is_api_connected=True,
            encrypted_api_key="api",
            encrypted_secret_key="secret",
            encrypted_passphrase="passphrase",
            fixed_risk_amount=10,
        )


class FakePendingOrderRepo:
    def __init__(self):
        self.failed = []

    async def mark_failed(self, token, error_message):
        self.failed.append({"token": token, "error_message": error_message})
        return True


class FakeSystemLogRepo:
    def __init__(self):
        self.logs = []

    async def log(self, **kwargs):
        self.logs.append(kwargs)


class FakeOrderTradeManager(RejectingTradeManager):
    async def get_contract_rules(self, symbol):
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

    async def get_market_price(self, symbol):
        return 80000


class TimeoutOrderTradeManager(FakeOrderTradeManager):
    async def place_market_order(self, *args, **kwargs):
        raise BitgetAPIError("timeout", "Bitget request timeout")

    async def place_limit_order(self, *args, **kwargs):
        raise BitgetAPIError("timeout", "Bitget request timeout")


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


class RecordingFailureAlert:
    def __init__(self):
        self.calls = []

    async def __call__(self, classified_error, source, details=None):
        self.calls.append(
            {
                "classified_error": classified_error,
                "source": source,
                "details": details or {},
            }
        )


@pytest.mark.asyncio
async def test_order_flow_service_marks_pending_failed_and_sends_user_message():
    bot = FakeBot()
    pending_order_repo = FakePendingOrderRepo()
    system_log_repo = FakeSystemLogRepo()
    audit_owner = FakeAuditOwner()
    service = TelegramOrderFlowService(
        bot=bot,
        user_repo=FakeUserRepo(),
        pending_order_repo=pending_order_repo,
        trade_repo=FakeTradeRepo(),
        trade_manager=FakeOrderTradeManager(),
        system_log_repo=system_log_repo,
        audit_owner=audit_owner,
        failure_alert_handler=None,
    )
    query = FakeQuery()
    user = SimpleNamespace(telegram_id=123)

    result = await service.execute_order(
        ConfirmedOrderRequest(
            query=query,
            user=user,
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
            current_price=80000,
            order_mode="market",
            pending_order_token="tok_123",
        )
    )

    assert result is False
    assert pending_order_repo.failed[-1]["token"] == "tok_123"
    assert "category=exchange_rejected" in pending_order_repo.failed[-1]["error_message"]
    assert "交易所拒绝下单" in bot.messages[-1]["text"]
    logged_error = system_log_repo.logs[-1]["extra_data"]["classified_error"]
    assert logged_error["category"] == "exchange_rejected"
    assert logged_error["raw_code"] == "43012"
    assert audit_owner.audit_events[-1]["action"] == "order_failed"
    assert audit_owner.audit_events[-1]["details"]["error_category"] == "exchange_rejected"
    assert audit_owner.audit_events[-1]["details"]["pending_order_token"] == "***_123"


@pytest.mark.asyncio
async def test_order_flow_service_keeps_pending_processing_when_submission_result_unknown():
    bot = FakeBot()
    pending_order_repo = FakePendingOrderRepo()
    system_log_repo = FakeSystemLogRepo()
    audit_owner = FakeAuditOwner()
    trade_repo = FakeTradeRepo()
    failure_alert = RecordingFailureAlert()
    service = TelegramOrderFlowService(
        bot=bot,
        user_repo=FakeUserRepo(),
        pending_order_repo=pending_order_repo,
        trade_repo=trade_repo,
        trade_manager=TimeoutOrderTradeManager(),
        system_log_repo=system_log_repo,
        audit_owner=audit_owner,
        failure_alert_handler=failure_alert,
    )
    query = FakeQuery()
    user = SimpleNamespace(telegram_id=123)

    result = await service.execute_order(
        ConfirmedOrderRequest(
            query=query,
            user=user,
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
            current_price=80000,
            order_mode="market",
            pending_order_token="tok_timeout",
        )
    )

    assert result is False
    assert pending_order_repo.failed == []
    assert trade_repo.updated_results == []
    assert "订单状态待确认" in bot.messages[-1]["text"]
    assert system_log_repo.logs[-1]["message"] == "Bitget order execution result unknown"
    assert system_log_repo.logs[-1]["extra_data"]["classified_error"]["is_retryable"] is True
    assert failure_alert.calls[-1]["source"] == "_execute_order_unknown_result"
    assert audit_owner.audit_events[-1]["action"] == "order_execution_deferred"
    assert audit_owner.audit_events[-1]["details"]["status"] == "processing"
    assert audit_owner.audit_events[-1]["details"]["reason"] == "bitget_submission_result_unknown"
