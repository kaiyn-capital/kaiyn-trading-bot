import asyncio
import re
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import app.order_flow as order_flow_module
from app.order_flow import build_client_order_id, execute_order
from app.order_interaction_service import ConfirmedOrderRequest, TelegramOrderFlowService

CLIENT_ORDER_ID_PATTERN = re.compile(r"^[0-9A-Za-z_:#\-\+\s]{1,32}$")


class FakeTradeRecord:
    id = 77


class RecordingTradeRepo:
    def __init__(self):
        self.created_trade = None
        self.created_trade_with_daily_limit = None
        self.updated_results = []

    async def create_trade(self, **kwargs):
        self.created_trade = kwargs
        return FakeTradeRecord()

    async def create_trade_with_daily_limit(self, **kwargs):
        self.created_trade_with_daily_limit = kwargs
        trade_kwargs = {
            key: value for key, value in kwargs.items() if key not in {"daily_trade_limit", "day_start_utc"}
        }
        return await self.create_trade(**trade_kwargs)

    async def update_trade_result(self, trade_id, **kwargs):
        self.updated_results.append({"trade_id": trade_id, **kwargs})

    async def count_daily_non_failed_trades(self, user_id, day_start_utc):
        return 0


class RecordingTradeManager:
    def __init__(self):
        self.market_orders = []
        self.limit_orders = []

    async def place_market_order(self, *args, **kwargs):
        self.market_orders.append({"args": args, "kwargs": kwargs})
        return {"code": "00000", "data": {"orderId": "bitget-market-order"}}

    async def place_limit_order(self, *args, **kwargs):
        self.limit_orders.append({"args": args, "kwargs": kwargs})
        return {"code": "00000", "data": {"orderId": "bitget-limit-order"}}


class ServiceTradeManager(RecordingTradeManager):
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
            daily_trade_limit=10,
            max_position_size=1000,
        )


class RecordingPendingOrderRepo:
    def __init__(self):
        self.executed = []
        self.failed = []

    async def mark_executed(self, token, trade_id):
        self.executed.append({"token": token, "trade_id": trade_id})
        return True

    async def mark_failed(self, token, error_message):
        self.failed.append({"token": token, "error_message": error_message})
        return True


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class FakeQuery:
    def __init__(self):
        self.answers = []

    async def answer(self, text=None):
        self.answers.append(text)


class FakeAuditOwner:
    def __init__(self):
        self.audit_events = []

    async def _audit_action(self, user, action, details=None):
        self.audit_events.append({"action": action, "details": details or {}})


def test_build_client_order_id_uses_pending_token_directly_when_valid():
    client_order_id = build_client_order_id("tok_ready")

    assert client_order_id == "KTB_tok_ready"
    assert CLIENT_ORDER_ID_PATTERN.fullmatch(client_order_id)
    assert len(client_order_id) <= 32


def test_build_client_order_id_hashes_invalid_or_too_long_pending_token():
    invalid_token = "bad/token?with*invalid" * 4

    first = build_client_order_id(invalid_token)
    second = build_client_order_id(invalid_token)

    assert first == second
    assert first.startswith("KTB_")
    assert first != f"KTB_{invalid_token}"
    assert CLIENT_ORDER_ID_PATTERN.fullmatch(first)
    assert len(first) <= 32


def test_build_client_order_id_creates_distinct_ids_for_distinct_pending_tokens():
    first = build_client_order_id("tok_same_second_a")
    second = build_client_order_id("tok_same_second_b")

    assert first != second
    assert CLIENT_ORDER_ID_PATTERN.fullmatch(first)
    assert CLIENT_ORDER_ID_PATTERN.fullmatch(second)


def test_build_client_order_id_fallback_is_legal_and_unique(monkeypatch):
    generated = iter(["fallback_token_a", "fallback_token_b"])
    monkeypatch.setattr(order_flow_module.secrets, "token_urlsafe", lambda size: next(generated))

    first = build_client_order_id()
    second = build_client_order_id()

    assert first == "KTB_fallback_token_a"
    assert second == "KTB_fallback_token_b"
    assert first != second
    assert CLIENT_ORDER_ID_PATTERN.fullmatch(first)
    assert CLIENT_ORDER_ID_PATTERN.fullmatch(second)


def test_market_execute_order_uses_same_client_order_id_for_trade_record_and_bitget():
    trade_repo = RecordingTradeRepo()
    trade_manager = RecordingTradeManager()
    client_order_id = build_client_order_id("tok_market")

    asyncio.run(
        execute_order(
            user_data=SimpleNamespace(id=7),
            trade_repo=trade_repo,
            trade_manager=trade_manager,
            credentials=("api", "secret", "passphrase"),
            telegram_id=123,
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
            client_order_id=client_order_id,
        )
    )

    assert trade_repo.created_trade["client_order_id"] == client_order_id
    assert trade_repo.created_trade["quantity"] == Decimal("0.01")
    assert trade_repo.created_trade["price"] is None
    assert trade_manager.market_orders[-1]["args"][4] == "0.01"
    assert trade_manager.market_orders[-1]["args"][5] == client_order_id


def test_limit_execute_order_uses_same_client_order_id_for_trade_record_and_bitget():
    trade_repo = RecordingTradeRepo()
    trade_manager = RecordingTradeManager()
    client_order_id = build_client_order_id("tok_limit")

    asyncio.run(
        execute_order(
            user_data=SimpleNamespace(id=7),
            trade_repo=trade_repo,
            trade_manager=trade_manager,
            credentials=("api", "secret", "passphrase"),
            telegram_id=123,
            symbol="BTCUSDT",
            direction="short",
            quantity=0.02,
            stop_loss=81700,
            position_value=1604,
            order_mode="limit",
            limit_price=80200,
            quantity_text="0.02",
            limit_price_text="80200",
            client_order_id=client_order_id,
        )
    )

    assert trade_repo.created_trade["client_order_id"] == client_order_id
    assert trade_repo.created_trade["quantity"] == Decimal("0.02")
    assert trade_repo.created_trade["price"] == Decimal("80200")
    assert trade_manager.limit_orders[-1]["args"][4] == "0.02"
    assert trade_manager.limit_orders[-1]["args"][5] == "80200"
    assert trade_manager.limit_orders[-1]["args"][6] == client_order_id


def test_execute_order_without_client_order_id_uses_legal_fallback(monkeypatch):
    monkeypatch.setattr(order_flow_module.secrets, "token_urlsafe", lambda size: "fallback_token")
    trade_repo = RecordingTradeRepo()
    trade_manager = RecordingTradeManager()

    asyncio.run(
        execute_order(
            user_data=SimpleNamespace(id=7),
            trade_repo=trade_repo,
            trade_manager=trade_manager,
            credentials=("api", "secret", "passphrase"),
            telegram_id=123,
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
        )
    )

    client_order_id = trade_repo.created_trade["client_order_id"]
    assert client_order_id == "KTB_fallback_token"
    assert trade_manager.market_orders[-1]["args"][5] == client_order_id
    assert CLIENT_ORDER_ID_PATTERN.fullmatch(client_order_id)


def test_execute_order_uses_authoritative_daily_limit_create_path():
    trade_repo = RecordingTradeRepo()
    trade_manager = RecordingTradeManager()
    day_start = datetime(2026, 5, 21, 16, 0, 0)

    asyncio.run(
        execute_order(
            user_data=SimpleNamespace(id=7),
            trade_repo=trade_repo,
            trade_manager=trade_manager,
            credentials=("api", "secret", "passphrase"),
            telegram_id=123,
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
            client_order_id="KTB_daily_limit",
            daily_trade_limit=3,
            daily_limit_day_start_utc=day_start,
        )
    )

    assert trade_repo.created_trade_with_daily_limit["daily_trade_limit"] == 3
    assert trade_repo.created_trade_with_daily_limit["day_start_utc"] == day_start
    assert trade_repo.created_trade["client_order_id"] == "KTB_daily_limit"


def test_order_flow_service_builds_client_order_id_from_pending_token():
    trade_repo = RecordingTradeRepo()
    trade_manager = ServiceTradeManager()
    pending_order_repo = RecordingPendingOrderRepo()
    service = TelegramOrderFlowService(
        bot=FakeBot(),
        user_repo=FakeUserRepo(),
        pending_order_repo=pending_order_repo,
        trade_repo=trade_repo,
        trade_manager=trade_manager,
        system_log_repo=SimpleNamespace(),
        audit_owner=FakeAuditOwner(),
        failure_alert_handler=None,
    )

    result = asyncio.run(
        service.execute_order(
            ConfirmedOrderRequest(
                query=FakeQuery(),
                user=SimpleNamespace(telegram_id=123),
                symbol="BTCUSDT",
                direction="long",
                quantity=0.01,
                stop_loss=79000,
                position_value=800,
                current_price=80000,
                order_mode="market",
                pending_order_token="tok_service",
            )
        )
    )

    assert result is True
    assert trade_repo.created_trade["client_order_id"] == "KTB_tok_service"
    assert trade_manager.market_orders[-1]["args"][5] == "KTB_tok_service"
    assert pending_order_repo.executed == [{"token": "tok_service", "trade_id": 77}]
