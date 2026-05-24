import logging
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.bitget_api import BitgetTradeManager


class FakeCachedClient:
    def __init__(self, *, fail_close=False):
        self.closed = False
        self.fail_close = fail_close

    async def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError("close failed")


class FakePublicMarket:
    def __init__(self):
        self.calls = []

    async def get_market_price(self, symbol):
        self.calls.append(("get_market_price", symbol))
        return 123.45

    async def get_trading_pairs(self, product_type="USDT-FUTURES", force_refresh=False):
        self.calls.append(("get_trading_pairs", product_type, force_refresh))
        return [{"symbol": "BTCUSDT"}]

    async def get_contract_rules(self, symbol, product_type="USDT-FUTURES"):
        self.calls.append(("get_contract_rules", symbol, product_type))
        return {"symbol": symbol, "productType": product_type}


class FakeOrderClient:
    def __init__(self):
        self.orders = []

    async def place_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"code": "00000", "data": {"orderId": "abc"}}


@pytest.mark.asyncio
async def test_invalidate_user_client_closes_and_removes_cached_client():
    manager = BitgetTradeManager(SimpleNamespace())
    client = FakeCachedClient()
    manager._clients[123] = client

    result = await manager.invalidate_user_client(123)

    assert result is True
    assert client.closed is True
    assert 123 not in manager._clients


@pytest.mark.asyncio
async def test_invalidate_user_client_returns_false_when_no_cached_client():
    manager = BitgetTradeManager(SimpleNamespace())

    result = await manager.invalidate_user_client(123)

    assert result is False
    assert manager._clients == {}


@pytest.mark.asyncio
async def test_invalidate_user_client_removes_cache_when_close_fails(caplog):
    manager = BitgetTradeManager(SimpleNamespace())
    client = FakeCachedClient(fail_close=True)
    manager._clients[123] = client

    with caplog.at_level(logging.WARNING):
        result = await manager.invalidate_user_client(123)

    assert result is True
    assert client.closed is True
    assert 123 not in manager._clients
    assert "Failed to close cached Bitget client" in caplog.text


@pytest.mark.asyncio
async def test_market_price_delegates_to_public_market_instance():
    manager = BitgetTradeManager(SimpleNamespace())
    public_market = FakePublicMarket()
    manager.public_market = public_market

    result = await manager.get_market_price("BTCUSDT")

    assert result == Decimal("123.45")
    assert public_market.calls == [("get_market_price", "BTCUSDT")]


@pytest.mark.asyncio
async def test_trading_pairs_delegates_to_public_market_instance():
    manager = BitgetTradeManager(SimpleNamespace())
    public_market = FakePublicMarket()
    manager.public_market = public_market

    result = await manager.get_trading_pairs("USDT-FUTURES", force_refresh=True)

    assert result == [{"symbol": "BTCUSDT"}]
    assert public_market.calls == [("get_trading_pairs", "USDT-FUTURES", True)]


@pytest.mark.asyncio
async def test_contract_rules_delegates_to_public_market_instance():
    manager = BitgetTradeManager(SimpleNamespace())
    public_market = FakePublicMarket()
    manager.public_market = public_market

    result = await manager.get_contract_rules("BTCUSDT", "USDT-FUTURES")

    assert result == {"symbol": "BTCUSDT", "productType": "USDT-FUTURES"}
    assert public_market.calls == [("get_contract_rules", "BTCUSDT", "USDT-FUTURES")]


@pytest.mark.asyncio
async def test_market_order_formats_decimal_values_before_bitget_client():
    manager = BitgetTradeManager(SimpleNamespace())
    client = FakeOrderClient()

    def get_client(user_id, encrypted_credentials):
        return client

    manager._get_client = get_client

    result = await manager.place_market_order(
        user_id=7,
        encrypted_credentials=("api", "secret", "passphrase"),
        symbol="BTCUSDT",
        side="buy",
        size="0.012",
        client_order_id="KTB_test",
        stop_loss_price=Decimal("79999.9000"),
    )

    assert result["code"] == "00000"
    assert client.orders[-1]["size"] == "0.012"
    assert client.orders[-1]["stop_loss_price"] == "79999.9"


@pytest.mark.asyncio
async def test_limit_order_formats_price_and_stop_loss_before_bitget_client():
    manager = BitgetTradeManager(SimpleNamespace())
    client = FakeOrderClient()

    def get_client(user_id, encrypted_credentials):
        return client

    manager._get_client = get_client

    result = await manager.place_limit_order(
        user_id=7,
        encrypted_credentials=("api", "secret", "passphrase"),
        symbol="BTCUSDT",
        side="sell",
        size="0.02",
        price="80200.1",
        client_order_id="KTB_limit",
        stop_loss_price=Decimal("81700.000"),
    )

    assert result["code"] == "00000"
    assert client.orders[-1]["price"] == "80200.1"
    assert client.orders[-1]["stop_loss_price"] == "81700"
