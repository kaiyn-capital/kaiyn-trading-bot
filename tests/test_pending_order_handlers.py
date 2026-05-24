from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.bot_order_handlers import OrderHandlersMixin
from app.order_interaction_service import ConfirmedOrderRequest


class FakeOrderFlowService:
    def __init__(self):
        self.calls = []

    async def handle_place_order_callback(self, query, user, data):
        self.calls.append(("place", query, user, data))
        return "placed"

    async def handle_confirm_pending_order_callback(self, query, user, data):
        self.calls.append(("confirm", query, user, data))
        return "confirmed"

    async def handle_cancel_pending_order_callback(self, query, user, data):
        self.calls.append(("cancel", query, user, data))
        return "cancelled"

    async def send_private_message(self, query, user, text, reply_markup=None):
        self.calls.append(("private", query, user, text, reply_markup))
        return "sent"

    async def execute_order(self, request):
        self.calls.append(("execute", request))
        return "executed"


class FakeOrderHandler(OrderHandlersMixin):
    def __init__(self):
        self.service = FakeOrderFlowService()
        self.factory_calls = 0

    def _order_flow_service(self):
        self.factory_calls += 1
        return self.service


@pytest.mark.asyncio
async def test_place_order_callback_delegates_to_order_flow_service():
    handler = FakeOrderHandler()
    query = SimpleNamespace()
    user = SimpleNamespace(telegram_id=123)

    result = await handler._handle_place_order_callback(query, user, "place_order_market_BTCUSDT_long_1_2_0.9")

    assert result == "placed"
    assert handler.factory_calls == 1
    assert handler.service.calls == [("place", query, user, "place_order_market_BTCUSDT_long_1_2_0.9")]


@pytest.mark.asyncio
async def test_confirm_pending_order_callback_delegates_to_order_flow_service():
    handler = FakeOrderHandler()
    query = SimpleNamespace()
    user = SimpleNamespace(telegram_id=123)

    result = await handler._handle_confirm_pending_order_callback(query, user, "confirm_order_tok_ready")

    assert result == "confirmed"
    assert handler.factory_calls == 1
    assert handler.service.calls == [("confirm", query, user, "confirm_order_tok_ready")]


@pytest.mark.asyncio
async def test_cancel_pending_order_callback_delegates_to_order_flow_service():
    handler = FakeOrderHandler()
    query = SimpleNamespace()
    user = SimpleNamespace(telegram_id=123)

    result = await handler._handle_cancel_pending_order_callback(query, user, "cancel_order_tok_ready")

    assert result == "cancelled"
    assert handler.factory_calls == 1
    assert handler.service.calls == [("cancel", query, user, "cancel_order_tok_ready")]


@pytest.mark.asyncio
async def test_send_private_message_delegates_to_order_flow_service():
    handler = FakeOrderHandler()
    query = SimpleNamespace()
    user = SimpleNamespace(telegram_id=123)
    reply_markup = SimpleNamespace()

    result = await handler._send_private_message(query, user, "hello", reply_markup)

    assert result == "sent"
    assert handler.factory_calls == 1
    assert handler.service.calls == [("private", query, user, "hello", reply_markup)]


@pytest.mark.asyncio
async def test_execute_order_delegates_confirmed_request_to_order_flow_service():
    handler = FakeOrderHandler()
    query = SimpleNamespace()
    user = SimpleNamespace(telegram_id=123)

    result = await handler._execute_order(
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

    assert result == "executed"
    assert handler.factory_calls == 1
    call_name, request = handler.service.calls[0]
    assert call_name == "execute"
    assert isinstance(request, ConfirmedOrderRequest)
    assert request.query is query
    assert request.user is user
    assert request.symbol == "BTCUSDT"
    assert request.direction == "long"
    assert request.quantity == Decimal("0.01")
    assert request.stop_loss == Decimal("79000")
    assert request.position_value == Decimal("800")
    assert request.current_price == Decimal("80000")
    assert request.order_mode == "market"
    assert request.limit_price is None
    assert request.pending_order_token == "tok_123"
