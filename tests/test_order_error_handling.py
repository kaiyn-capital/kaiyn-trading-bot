import asyncio
from types import SimpleNamespace

import pytest

from app.bot_order_handlers import OrderHandlersMixin
from app.order_flow import execute_order


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

    async def update_trade_result(self, trade_id, **kwargs):
        self.updated_results.append({"trade_id": trade_id, **kwargs})


class RejectingTradeManager:
    async def place_market_order(self, *args, **kwargs):
        raise FakeBitgetAPIError("43012", "insufficient balance")

    async def place_limit_order(self, *args, **kwargs):
        raise FakeBitgetAPIError("43012", "insufficient balance")


def test_execute_order_marks_trade_failed_with_classified_error():
    trade_repo = FakeTradeRepo()

    with pytest.raises(FakeBitgetAPIError):
        asyncio.run(
            execute_order(
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
        )

    failed_update = trade_repo.updated_results[-1]
    assert failed_update["trade_id"] == 77
    assert failed_update["status"] == "failed"
    assert "category=exchange_rejected" in failed_update["error_message"]
    assert "code=43012" in failed_update["error_message"]
    assert "insufficient balance" in failed_update["error_message"]


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


class FakeQuery:
    def __init__(self):
        self.answers = []

    async def answer(self, text=None):
        self.answers.append(text)


class FakeOrderHandler(OrderHandlersMixin):
    def __init__(self):
        self.user_repo = FakeUserRepo()
        self.trade_repo = FakeTradeRepo()
        self.trade_manager = FakeOrderTradeManager()
        self.pending_order_repo = FakePendingOrderRepo()
        self.system_log_repo = FakeSystemLogRepo()
        self.private_messages = []

    async def _send_private_message(self, query, user, text, reply_markup=None):
        self.private_messages.append(text)


def test_execute_order_handler_marks_pending_failed_and_sends_user_message():
    handler = FakeOrderHandler()
    query = FakeQuery()
    user = SimpleNamespace(telegram_id=123)

    result = asyncio.run(
        handler._execute_order(
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
    assert handler.pending_order_repo.failed[-1]["token"] == "tok_123"
    assert (
        "category=exchange_rejected"
        in handler.pending_order_repo.failed[-1]["error_message"]
    )
    assert "交易所拒绝下单" in handler.private_messages[-1]
    logged_error = handler.system_log_repo.logs[-1]["extra_data"]["classified_error"]
    assert logged_error["category"] == "exchange_rejected"
    assert logged_error["raw_code"] == "43012"
