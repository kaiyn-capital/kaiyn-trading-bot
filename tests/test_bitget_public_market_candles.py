import asyncio
from datetime import UTC, datetime

import pytest

from app import bitget_public_market as market_module
from app.bitget_errors import BitgetAPIError
from app.bitget_public_market import BitgetPublicMarket, parse_bitget_candles_payload


class FakeResponse:
    def __init__(self, status_code, payload, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
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


def test_get_candles_uses_bitget_contract_candle_endpoint(monkeypatch):
    response = FakeResponse(
        200,
        {
            "code": "00000",
            "data": [["1000", "100", "102", "98", "101", "1.5", "150"]],
        },
    )
    client = FakeAsyncClient(response)
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda timeout: client)

    candles = asyncio.run(BitgetPublicMarket().get_candles("btcusdt", granularity="1H", limit=120))

    assert len(candles) == 1
    assert client.requests[0]["url"].endswith("/api/v2/mix/market/candles")
    assert client.requests[0]["params"] == {
        "symbol": "BTCUSDT",
        "granularity": "1H",
        "limit": "120",
        "productType": "USDT-FUTURES",
        "kLineType": "MARKET",
    }


def test_get_candles_accepts_time_window(monkeypatch):
    response = FakeResponse(
        200,
        {
            "code": "00000",
            "data": [["1000", "100", "102", "98", "101", "1.5", "150"]],
        },
    )
    client = FakeAsyncClient(response)
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda timeout: client)

    asyncio.run(
        BitgetPublicMarket().get_candles(
            "BTCUSDT",
            start_time=datetime(2026, 5, 21, 1, 0, tzinfo=UTC),
            end_time=datetime(2026, 5, 21, 2, 0, tzinfo=UTC),
        )
    )

    assert client.requests[0]["params"]["startTime"] == "1779325200000"
    assert client.requests[0]["params"]["endTime"] == "1779328800000"


def test_get_candles_raises_bitget_error_on_api_error(monkeypatch):
    response = FakeResponse(200, {"code": "40001", "msg": "bad request", "data": []})
    monkeypatch.setattr(market_module.httpx, "AsyncClient", lambda timeout: FakeAsyncClient(response))

    with pytest.raises(BitgetAPIError):
        asyncio.run(BitgetPublicMarket().get_candles("BTCUSDT"))
