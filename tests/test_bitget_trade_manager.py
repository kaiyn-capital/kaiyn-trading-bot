import asyncio
import logging
from types import SimpleNamespace

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


def test_invalidate_user_client_closes_and_removes_cached_client():
    manager = BitgetTradeManager(SimpleNamespace())
    client = FakeCachedClient()
    manager._clients[123] = client

    result = asyncio.run(manager.invalidate_user_client(123))

    assert result is True
    assert client.closed is True
    assert 123 not in manager._clients


def test_invalidate_user_client_returns_false_when_no_cached_client():
    manager = BitgetTradeManager(SimpleNamespace())

    result = asyncio.run(manager.invalidate_user_client(123))

    assert result is False
    assert manager._clients == {}


def test_invalidate_user_client_removes_cache_when_close_fails(caplog):
    manager = BitgetTradeManager(SimpleNamespace())
    client = FakeCachedClient(fail_close=True)
    manager._clients[123] = client

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(manager.invalidate_user_client(123))

    assert result is True
    assert client.closed is True
    assert 123 not in manager._clients
    assert "Failed to close cached Bitget client" in caplog.text


def test_market_price_delegates_to_public_market_instance():
    manager = BitgetTradeManager(SimpleNamespace())
    public_market = FakePublicMarket()
    manager.public_market = public_market

    result = asyncio.run(manager.get_market_price("BTCUSDT"))

    assert result == 123.45
    assert public_market.calls == [("get_market_price", "BTCUSDT")]


def test_trading_pairs_delegates_to_public_market_instance():
    manager = BitgetTradeManager(SimpleNamespace())
    public_market = FakePublicMarket()
    manager.public_market = public_market

    result = asyncio.run(manager.get_trading_pairs("USDT-FUTURES", force_refresh=True))

    assert result == [{"symbol": "BTCUSDT"}]
    assert public_market.calls == [("get_trading_pairs", "USDT-FUTURES", True)]


def test_contract_rules_delegates_to_public_market_instance():
    manager = BitgetTradeManager(SimpleNamespace())
    public_market = FakePublicMarket()
    manager.public_market = public_market

    result = asyncio.run(manager.get_contract_rules("BTCUSDT", "USDT-FUTURES"))

    assert result == {"symbol": "BTCUSDT", "productType": "USDT-FUTURES"}
    assert public_market.calls == [("get_contract_rules", "BTCUSDT", "USDT-FUTURES")]
