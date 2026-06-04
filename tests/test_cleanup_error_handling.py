from types import SimpleNamespace

import httpx
import pytest

from app.bitget_trade_manager import BitgetTradeManager


class FakeClient:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.close_called = False

    async def close(self):
        self.close_called = True
        if self.should_fail:
            raise RuntimeError("Failed to close client")


class FakePublicMarket:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.close_called = False

    async def close(self):
        self.close_called = True
        if self.should_fail:
            raise httpx.HTTPError("Failed to close public market")


@pytest.mark.asyncio
async def test_cleanup_continues_on_client_failure():
    manager = BitgetTradeManager(SimpleNamespace(), settings=SimpleNamespace(bitget_api_url="http://test"))

    client1 = FakeClient(should_fail=True)
    client2 = FakeClient(should_fail=False)

    manager._clients = {1: client1, 2: client2}

    public_market = FakePublicMarket()
    manager.public_market = public_market

    # This should not raise an exception
    await manager.cleanup()

    assert client1.close_called is True
    assert client2.close_called is True
    assert len(manager._clients) == 0
    assert public_market.close_called is True


@pytest.mark.asyncio
async def test_cleanup_continues_on_public_market_failure():
    manager = BitgetTradeManager(SimpleNamespace(), settings=SimpleNamespace(bitget_api_url="http://test"))

    client1 = FakeClient(should_fail=False)
    manager._clients = {1: client1}

    public_market = FakePublicMarket(should_fail=True)
    manager.public_market = public_market

    # This should not raise an exception
    await manager.cleanup()

    assert client1.close_called is True
    assert len(manager._clients) == 0
    assert public_market.close_called is True
