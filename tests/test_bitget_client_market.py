import pytest

from app.bitget_client import BitgetAPIClient


@pytest.mark.asyncio
async def test_get_ticker_includes_default_product_type(monkeypatch):
    client = BitgetAPIClient("api", "secret", "pass")
    calls = []

    async def fake_make_request(method, endpoint, params=None, data=None):
        calls.append({"method": method, "endpoint": endpoint, "params": params, "data": data})
        return {"code": "00000", "data": [{"symbol": "BTCUSDT", "lastPr": "67777"}]}

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    await client.get_ticker("BTCUSDT")

    assert calls == [
        {
            "method": "GET",
            "endpoint": "/api/v2/mix/market/ticker",
            "params": {"symbol": "BTCUSDT", "productType": "USDT-FUTURES"},
            "data": None,
        }
    ]

    await client.close()


@pytest.mark.asyncio
async def test_get_ticker_allows_product_type_override(monkeypatch):
    client = BitgetAPIClient("api", "secret", "pass")
    calls = []

    async def fake_make_request(method, endpoint, params=None, data=None):
        calls.append({"method": method, "endpoint": endpoint, "params": params, "data": data})
        return {"code": "00000", "data": [{"symbol": "ETHUSDC", "lastPr": "3200"}]}

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    await client.get_ticker("ETHUSDC", product_type="USDC-FUTURES")

    assert calls == [
        {
            "method": "GET",
            "endpoint": "/api/v2/mix/market/ticker",
            "params": {"symbol": "ETHUSDC", "productType": "USDC-FUTURES"},
            "data": None,
        }
    ]

    await client.close()
