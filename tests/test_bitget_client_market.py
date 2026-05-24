import pytest

from app.bitget_client import BitgetAPIClient
from app.bitget_errors import BitgetAPIError


class FakeResponse:
    status_code = 200
    text = "not-json"

    def json(self):
        raise ValueError("invalid json")


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
async def test_make_request_wraps_invalid_json_as_bitget_error(monkeypatch):
    client = BitgetAPIClient("api", "secret", "pass")

    async def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(client.client, "get", fake_get)

    with pytest.raises(BitgetAPIError) as error:
        await client.get_ticker("BTCUSDT")

    assert error.value.code == "200"
    assert error.value.endpoint == "/api/v2/mix/market/ticker"
    assert "Invalid JSON response" in error.value.message

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
