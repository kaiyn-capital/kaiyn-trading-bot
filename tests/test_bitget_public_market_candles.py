from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app import bitget_public_market as market_module
from app.bitget_errors import BitgetAPIError
from app.bitget_public_market import BitgetPublicMarket, parse_bitget_candles_payload


class FakeResponse:
    def __init__(self, status_code, payload, text="", json_exc=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.json_exc = json_exc

    def json(self):
        if self.json_exc is not None:
            raise self.json_exc
        return self._payload


class FakeAsyncClient:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        if self.exc is not None:
            raise self.exc
        self.requests.append({"url": url, "params": params})
        return self.response


def test_parse_bitget_candles_payload_sorts_and_maps_rows():
    candles = parse_bitget_candles_payload(
        [
            ["2000", "101", "105", "99", "104", "2.5", "260"],
            ["1000", "100", "102", "98", "101", "1.5", "150"],
        ]
    )

    assert [candle.timestamp.timestamp() for candle in candles] == [1, 2]
    assert candles[0].timestamp.tzinfo == UTC
    assert candles[0].open == 100
    assert candles[0].high == 102
    assert candles[0].low == 98
    assert candles[0].close == 101
    assert candles[0].volume == 1.5


def test_parse_bitget_candles_payload_allows_empty_data():
    assert parse_bitget_candles_payload([]) == []


def test_parse_bitget_candles_payload_rejects_invalid_row():
    with pytest.raises(ValueError):
        parse_bitget_candles_payload([["1000", "100"]])


@pytest.mark.asyncio
async def test_get_market_price_uses_single_symbol_ticker_endpoint(monkeypatch):
    response = FakeResponse(
        200,
        {
            "code": "00000",
            "data": [{"symbol": "BTCUSDT", "lastPr": "67777.123456789"}],
        },
    )
    client = FakeAsyncClient(response)
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: client)

    price = await BitgetPublicMarket().get_market_price("btcusdt")

    assert price == Decimal("67777.123456789")
    assert client.requests == [
        {
            "url": "https://api.bitget.com/api/v2/mix/market/ticker",
            "params": {
                "symbol": "BTCUSDT",
                "productType": "USDT-FUTURES",
            },
        }
    ]


@pytest.mark.asyncio
async def test_get_market_price_raises_bitget_error_on_api_error(monkeypatch):
    response = FakeResponse(200, {"code": "40001", "msg": "bad request", "data": []})
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(response))

    with pytest.raises(BitgetAPIError) as error:
        await BitgetPublicMarket().get_market_price("BTCUSDT")

    assert error.value.code == "40001"
    assert error.value.endpoint == "/api/v2/mix/market/ticker"


@pytest.mark.asyncio
async def test_get_market_price_raises_symbol_not_found_on_empty_ticker(monkeypatch):
    response = FakeResponse(200, {"code": "00000", "data": []})
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(response))

    with pytest.raises(BitgetAPIError) as error:
        await BitgetPublicMarket().get_market_price("BTCUSDT")

    assert error.value.code == "symbol_not_found"
    assert error.value.endpoint == "/api/v2/mix/market/ticker"


@pytest.mark.asyncio
async def test_get_market_price_raises_on_missing_last_price(monkeypatch):
    response = FakeResponse(200, {"code": "00000", "data": [{"symbol": "BTCUSDT"}]})
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(response))

    with pytest.raises(BitgetAPIError) as error:
        await BitgetPublicMarket().get_market_price("BTCUSDT")

    assert error.value.code == "invalid_ticker_response"
    assert error.value.endpoint == "/api/v2/mix/market/ticker"


@pytest.mark.asyncio
async def test_get_market_price_raises_on_invalid_last_price(monkeypatch):
    response = FakeResponse(200, {"code": "00000", "data": [{"symbol": "BTCUSDT", "lastPr": "nan"}]})
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(response))

    with pytest.raises(BitgetAPIError) as error:
        await BitgetPublicMarket().get_market_price("BTCUSDT")

    assert error.value.code == "invalid_ticker_response"
    assert error.value.endpoint == "/api/v2/mix/market/ticker"


@pytest.mark.asyncio
async def test_get_market_price_wraps_invalid_json_response(monkeypatch):
    response = FakeResponse(200, {}, text="not-json", json_exc=ValueError("invalid json"))
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(response))

    with pytest.raises(BitgetAPIError) as error:
        await BitgetPublicMarket().get_market_price("BTCUSDT")

    assert error.value.code == "invalid_json_response"
    assert error.value.endpoint == "/api/v2/mix/market/ticker"


@pytest.mark.asyncio
async def test_get_market_price_raises_bitget_error_on_http_error(monkeypatch):
    response = FakeResponse(500, {}, text="bad gateway")
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(response))

    with pytest.raises(BitgetAPIError) as error:
        await BitgetPublicMarket().get_market_price("BTCUSDT")

    assert error.value.code == "500"
    assert error.value.endpoint == "/api/v2/mix/market/ticker"


@pytest.mark.asyncio
async def test_get_market_price_raises_bitget_error_on_timeout(monkeypatch):
    monkeypatch.setattr(
        market_module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(exc=httpx.TimeoutException("timeout")),
    )

    with pytest.raises(BitgetAPIError) as error:
        await BitgetPublicMarket().get_market_price("BTCUSDT")

    assert error.value.code == "timeout"
    assert error.value.endpoint == "/api/v2/mix/market/ticker"


@pytest.mark.asyncio
async def test_get_market_price_raises_bitget_error_on_network_error(monkeypatch):
    monkeypatch.setattr(
        market_module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(exc=httpx.RequestError("network error")),
    )

    with pytest.raises(BitgetAPIError) as error:
        await BitgetPublicMarket().get_market_price("BTCUSDT")

    assert error.value.code == "network_error"
    assert error.value.endpoint == "/api/v2/mix/market/ticker"


@pytest.mark.asyncio
async def test_get_candles_uses_bitget_contract_candle_endpoint(monkeypatch):
    response = FakeResponse(
        200,
        {
            "code": "00000",
            "data": [["1000", "100", "102", "98", "101", "1.5", "150"]],
        },
    )
    client = FakeAsyncClient(response)
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: client)

    candles = await BitgetPublicMarket().get_candles("btcusdt", granularity="1H", limit=120)

    assert len(candles) == 1
    assert client.requests[0]["url"].endswith("/api/v2/mix/market/candles")
    assert client.requests[0]["params"] == {
        "symbol": "BTCUSDT",
        "granularity": "1H",
        "limit": "120",
        "productType": "USDT-FUTURES",
        "kLineType": "MARKET",
    }


@pytest.mark.asyncio
async def test_get_candles_accepts_time_window(monkeypatch):
    response = FakeResponse(
        200,
        {
            "code": "00000",
            "data": [["1000", "100", "102", "98", "101", "1.5", "150"]],
        },
    )
    client = FakeAsyncClient(response)
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: client)

    await BitgetPublicMarket().get_candles(
        "BTCUSDT",
        start_time=datetime(2026, 5, 21, 1, 0, tzinfo=UTC),
        end_time=datetime(2026, 5, 21, 2, 0, tzinfo=UTC),
    )

    assert client.requests[0]["params"]["startTime"] == "1779325200000"
    assert client.requests[0]["params"]["endTime"] == "1779328800000"


@pytest.mark.asyncio
async def test_get_candles_raises_bitget_error_on_api_error(monkeypatch):
    response = FakeResponse(200, {"code": "40001", "msg": "bad request", "data": []})
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(response))

    with pytest.raises(BitgetAPIError):
        await BitgetPublicMarket().get_candles("BTCUSDT")


@pytest.mark.asyncio
async def test_get_trading_pairs_wraps_invalid_json_response(monkeypatch):
    response = FakeResponse(200, {}, text="not-json", json_exc=ValueError("invalid json"))
    client = FakeAsyncClient(response)
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: client)

    with pytest.raises(BitgetAPIError) as error:
        await BitgetPublicMarket().get_trading_pairs()

    assert client.requests[0]["url"].endswith("/api/v2/mix/market/contracts")
    assert client.requests[0]["params"] == {"productType": "USDT-FUTURES"}
    assert error.value.code == "invalid_json_response"
    assert error.value.endpoint == "/api/v2/mix/market/contracts"


@pytest.mark.asyncio
async def test_get_candles_wraps_invalid_json_response(monkeypatch):
    response = FakeResponse(200, {}, text="not-json", json_exc=ValueError("invalid json"))
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(response))

    with pytest.raises(BitgetAPIError) as error:
        await BitgetPublicMarket().get_candles("BTCUSDT")

    assert error.value.code == "invalid_json_response"
    assert error.value.endpoint == "/api/v2/mix/market/candles"
