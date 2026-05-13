import asyncio
from types import SimpleNamespace

import pytest

from app.bot_order_handlers import OrderHandlersMixin


class FakeQuery:
    def __init__(self):
        self.answers = []

    async def answer(self, text=None):
        self.answers.append(text)


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


class FakeConfirmOrderHandler(OrderHandlersMixin):
    def __init__(self, pending_order_repo):
        self.pending_order_repo = pending_order_repo
        self.private_messages = []
        self.executions = []
        self.audit_events = []

    async def _send_private_message(self, query, user, text, reply_markup=None):
        self.private_messages.append(text)

    async def _audit_action(self, user, action, details=None):
        self.audit_events.append({"action": action, "details": details or {}})

    async def _execute_order(
        self,
        query,
        user,
        symbol,
        direction,
        quantity,
        stop_loss,
        position_value,
        current_price,
        order_mode="market",
        limit_price=None,
        pending_order_token=None,
    ):
        self.executions.append(
            {
                "symbol": symbol,
                "direction": direction,
                "quantity": quantity,
                "stop_loss": stop_loss,
                "position_value": position_value,
                "current_price": current_price,
                "order_mode": order_mode,
                "limit_price": limit_price,
                "pending_order_token": pending_order_token,
            }
        )
        return True


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


def test_confirm_pending_order_missing_token():
    repo = FakeConfirmPendingOrderRepo(claim_result=(None, "missing"))
    handler = FakeConfirmOrderHandler(repo)

    asyncio.run(handler._handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_missing"))

    assert repo.claims == [{"token": "tok_missing", "telegram_id": 123456}]
    assert not handler.executions
    assert "找不到这笔待确认订单" in handler.private_messages[-1]
    assert handler.audit_events[-1]["action"] == "pending_order_confirm"
    assert handler.audit_events[-1]["details"]["status"] == "missing"
    assert handler.audit_events[-1]["details"]["pending_order_token"] == "***sing"


def test_confirm_pending_order_expired_token():
    repo = FakeConfirmPendingOrderRepo(claim_result=(make_pending_order(), "expired"))
    handler = FakeConfirmOrderHandler(repo)

    asyncio.run(handler._handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_expired"))

    assert not handler.executions
    assert "已过期" in handler.private_messages[-1]
    assert handler.audit_events[-1]["details"]["status"] == "expired"


@pytest.mark.parametrize("status", ["processing_by_other", "executed", "failed"])
def test_confirm_pending_order_non_processing_status_does_not_execute(status):
    repo = FakeConfirmPendingOrderRepo(claim_result=(make_pending_order(), status))
    handler = FakeConfirmOrderHandler(repo)

    asyncio.run(handler._handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_status"))

    assert not handler.executions
    assert f"状态为 {status}" in handler.private_messages[-1]
    assert handler.audit_events[-1]["details"]["status"] == status


def test_confirm_pending_order_processing_executes_with_full_pending_data():
    repo = FakeConfirmPendingOrderRepo(claim_result=(make_pending_order(), "processing"))
    handler = FakeConfirmOrderHandler(repo)

    asyncio.run(handler._handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_ready"))

    assert handler.executions == [
        {
            "symbol": "BTCUSDT",
            "direction": "short",
            "quantity": 0.02,
            "stop_loss": 81700,
            "position_value": 1604,
            "current_price": 80500,
            "order_mode": "limit",
            "limit_price": 80200,
            "pending_order_token": "tok_ready",
        }
    ]
    assert handler.audit_events[-1]["action"] == "pending_order_confirm"
    assert handler.audit_events[-1]["details"]["status"] == "processing"
    assert handler.audit_events[-1]["details"]["pending_order_token"] == "***eady"


def test_cancel_pending_order_cancelled_status():
    repo = FakeConfirmPendingOrderRepo(cancel_status="cancelled")
    handler = FakeConfirmOrderHandler(repo)
    query = FakeQuery()

    asyncio.run(handler._handle_cancel_pending_order_callback(query, make_user(), "cancel_order_tok_cancel"))

    assert repo.cancellations == [{"token": "tok_cancel", "telegram_id": 123456}]
    assert query.answers == ["已取消下单"]
    assert "已取消下单" in handler.private_messages[-1]
    assert handler.audit_events[-1]["action"] == "pending_order_cancel"
    assert handler.audit_events[-1]["details"]["status"] == "cancelled"


def test_cancel_pending_order_missing_status():
    repo = FakeConfirmPendingOrderRepo(cancel_status="missing")
    handler = FakeConfirmOrderHandler(repo)

    asyncio.run(handler._handle_cancel_pending_order_callback(FakeQuery(), make_user(), "cancel_order_tok_missing"))

    assert "找不到这笔待确认订单" in handler.private_messages[-1]
    assert handler.audit_events[-1]["details"]["status"] == "missing"


def test_cancel_pending_order_non_pending_status():
    repo = FakeConfirmPendingOrderRepo(cancel_status="processing")
    handler = FakeConfirmOrderHandler(repo)

    asyncio.run(handler._handle_cancel_pending_order_callback(FakeQuery(), make_user(), "cancel_order_tok_processing"))

    assert "状态为 processing，无法取消" in handler.private_messages[-1]
    assert handler.audit_events[-1]["details"]["status"] == "processing"


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


class RejectingRulesTradeManager:
    async def get_contract_rules(self, symbol):
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
        return 80000

    async def place_market_order(self, *args, **kwargs):
        raise AssertionError("market order should not be placed")

    async def place_limit_order(self, *args, **kwargs):
        raise AssertionError("limit order should not be placed")


class UnusedTradeRepo:
    async def create_trade(self, **kwargs):
        raise AssertionError("trade should not be created")


class FakeSystemLogRepo:
    async def log(self, **kwargs):
        raise AssertionError("system log should not be written for validation failure")


class FakeValidationOrderHandler(OrderHandlersMixin):
    def __init__(self):
        self.user_repo = FakeUserRepo()
        self.trade_repo = UnusedTradeRepo()
        self.trade_manager = RejectingRulesTradeManager()
        self.pending_order_repo = FakeConfirmPendingOrderRepo()
        self.system_log_repo = FakeSystemLogRepo()
        self.private_messages = []
        self.audit_events = []

    async def _send_private_message(self, query, user, text, reply_markup=None):
        self.private_messages.append(text)

    async def _audit_action(self, user, action, details=None):
        self.audit_events.append({"action": action, "details": details or {}})


def test_execute_order_marks_pending_failed_when_second_validation_fails():
    handler = FakeValidationOrderHandler()
    query = FakeQuery()

    result = asyncio.run(
        handler._execute_order(
            query=query,
            user=make_user(),
            symbol="BTCUSDT",
            direction="long",
            quantity=0.01,
            stop_loss=79000,
            position_value=800,
            current_price=80000,
            order_mode="market",
            pending_order_token="tok_validation",
        )
    )

    assert result is False
    assert handler.pending_order_repo.failed[-1]["token"] == "tok_validation"
    assert "下单数量低于交易所最小值" in (handler.pending_order_repo.failed[-1]["error_message"])
    assert "订单已不符合交易所规则" in handler.private_messages[-1]
    assert "下单数量低于交易所最小值" in handler.private_messages[-1]
    assert handler.audit_events[-1]["action"] == "order_validation_failed"
    assert handler.audit_events[-1]["details"]["pending_order_token"] == "***tion"
