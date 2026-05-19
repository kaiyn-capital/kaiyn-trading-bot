import asyncio
from types import SimpleNamespace

import pytest

from app.order_interaction_service import TelegramOrderFlowService


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


class RecordingOrderFlowService(TelegramOrderFlowService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.executions = []

    async def execute_order(self, request):
        self.executions.append(request)
        return True


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
        failure_alert_handler=None,
    )
    return service, bot, audit_owner


def test_confirm_pending_order_missing_token():
    repo = FakeConfirmPendingOrderRepo(claim_result=(None, "missing"))
    service, bot, audit_owner = make_service(pending_order_repo=repo, service_class=RecordingOrderFlowService)

    asyncio.run(service.handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_missing"))

    assert repo.claims == [{"token": "tok_missing", "telegram_id": 123456}]
    assert not service.executions
    assert "找不到这笔待确认订单" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "pending_order_confirm"
    assert audit_owner.audit_events[-1]["details"]["status"] == "missing"
    assert audit_owner.audit_events[-1]["details"]["pending_order_token"] == "***sing"


def test_confirm_pending_order_expired_token():
    repo = FakeConfirmPendingOrderRepo(claim_result=(make_pending_order(), "expired"))
    service, bot, audit_owner = make_service(pending_order_repo=repo, service_class=RecordingOrderFlowService)

    asyncio.run(service.handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_expired"))

    assert not service.executions
    assert "已过期" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["details"]["status"] == "expired"


@pytest.mark.parametrize("status", ["processing_by_other", "executed", "failed"])
def test_confirm_pending_order_non_processing_status_does_not_execute(status):
    repo = FakeConfirmPendingOrderRepo(claim_result=(make_pending_order(), status))
    service, bot, audit_owner = make_service(pending_order_repo=repo, service_class=RecordingOrderFlowService)

    asyncio.run(service.handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_status"))

    assert not service.executions
    assert f"状态为 {status}" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["details"]["status"] == status


def test_confirm_pending_order_processing_executes_with_full_pending_data():
    repo = FakeConfirmPendingOrderRepo(claim_result=(make_pending_order(), "processing"))
    service, _bot, audit_owner = make_service(pending_order_repo=repo, service_class=RecordingOrderFlowService)

    asyncio.run(service.handle_confirm_pending_order_callback(FakeQuery(), make_user(), "confirm_order_tok_ready"))

    assert len(service.executions) == 1
    request = service.executions[0]
    assert request.symbol == "BTCUSDT"
    assert request.direction == "short"
    assert request.quantity == 0.02
    assert request.stop_loss == 81700
    assert request.position_value == 1604
    assert request.current_price == 80500
    assert request.order_mode == "limit"
    assert request.limit_price == 80200
    assert request.pending_order_token == "tok_ready"
    assert audit_owner.audit_events[-1]["action"] == "pending_order_confirm"
    assert audit_owner.audit_events[-1]["details"]["status"] == "processing"
    assert audit_owner.audit_events[-1]["details"]["pending_order_token"] == "***eady"


def test_cancel_pending_order_cancelled_status():
    repo = FakeConfirmPendingOrderRepo(cancel_status="cancelled")
    service, bot, audit_owner = make_service(pending_order_repo=repo)
    query = FakeQuery()

    asyncio.run(service.handle_cancel_pending_order_callback(query, make_user(), "cancel_order_tok_cancel"))

    assert repo.cancellations == [{"token": "tok_cancel", "telegram_id": 123456}]
    assert query.answers == ["已取消下单"]
    assert "已取消下单" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "pending_order_cancel"
    assert audit_owner.audit_events[-1]["details"]["status"] == "cancelled"


def test_cancel_pending_order_missing_status():
    repo = FakeConfirmPendingOrderRepo(cancel_status="missing")
    service, bot, audit_owner = make_service(pending_order_repo=repo)

    asyncio.run(service.handle_cancel_pending_order_callback(FakeQuery(), make_user(), "cancel_order_tok_missing"))

    assert "找不到这笔待确认订单" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["details"]["status"] == "missing"


def test_cancel_pending_order_non_pending_status():
    repo = FakeConfirmPendingOrderRepo(cancel_status="processing")
    service, bot, audit_owner = make_service(pending_order_repo=repo)

    asyncio.run(service.handle_cancel_pending_order_callback(FakeQuery(), make_user(), "cancel_order_tok_processing"))

    assert "状态为 processing，无法取消" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["details"]["status"] == "processing"


def test_execute_order_marks_pending_failed_when_second_validation_fails():
    pending_order_repo = FakeConfirmPendingOrderRepo()
    service, bot, audit_owner = make_service(
        pending_order_repo=pending_order_repo,
        user_repo=FakeUserRepo(),
        trade_repo=UnusedTradeRepo(),
        trade_manager=RejectingRulesTradeManager(),
        system_log_repo=FakeSystemLogRepo(),
    )
    query = FakeQuery()

    result = asyncio.run(
        service.execute_order(
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
    )

    assert result is False
    assert pending_order_repo.failed[-1]["token"] == "tok_validation"
    assert "下单数量低于交易所最小值" in (pending_order_repo.failed[-1]["error_message"])
    assert "订单已不符合交易所规则" in bot.messages[-1]["text"]
    assert "下单数量低于交易所最小值" in bot.messages[-1]["text"]
    assert audit_owner.audit_events[-1]["action"] == "order_validation_failed"
    assert audit_owner.audit_events[-1]["details"]["pending_order_token"] == "***tion"
