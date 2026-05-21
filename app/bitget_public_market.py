import logging
import time
from datetime import datetime, timezone
from typing import Dict, List

import httpx

from .bitget_errors import BitgetAPIError
from .config import Config
from .market_types import MarketCandle

logger = logging.getLogger(__name__)


def parse_bitget_candles_payload(raw_candles: list[list[str]]) -> list[MarketCandle]:
    candles = []
    for row in raw_candles:
        if len(row) < 6:
            raise ValueError("invalid candle row")

        timestamp = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
        candles.append(
            MarketCandle(
                timestamp=timestamp,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
        )

    return sorted(candles, key=lambda candle: candle.timestamp)


def _datetime_to_millis(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


class BitgetPublicMarket:
    """Public Bitget market data and contract-rule cache."""

    def __init__(self, contracts_cache_ttl_seconds: int = 600):
        self._contracts_cache = {}
        self._contracts_cache_ttl_seconds = contracts_cache_ttl_seconds

    async def get_market_price(self, symbol: str) -> float:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                logger.info(f"Getting futures market price for {symbol}")

                url = f"{Config.BITGET_API_URL}/api/v2/mix/market/tickers?productType=USDT-FUTURES"

                logger.info(f"Fetching from URL: {url}")
                response = await client.get(url)

                if response.status_code == 200:
                    data = response.json()

                    if data.get("code") == "00000" and data.get("data"):
                        for item in data["data"]:
                            if item.get("symbol") == symbol:
                                price = float(item.get("lastPr", 0))
                                logger.info(f"Found price for {symbol}: {price}")
                                return price

                        error_msg = f"Symbol {symbol} not found in Bitget futures contracts"
                        logger.error(error_msg)
                        raise BitgetAPIError(
                            code="symbol_not_found",
                            message=error_msg,
                            data={"symbol": symbol},
                            endpoint="/api/v2/mix/market/tickers",
                            method="GET",
                        )
                    else:
                        error_msg = f"API returned error: {data}"
                        logger.error(error_msg)
                        raise BitgetAPIError(
                            code=data.get("code"),
                            message=data.get("msg", error_msg),
                            data=data,
                            http_status=response.status_code,
                            endpoint="/api/v2/mix/market/tickers",
                            method="GET",
                        )
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    logger.error(error_msg)
                    raise BitgetAPIError(
                        code=str(response.status_code),
                        message=error_msg,
                        data={"response": response.text[:1000]},
                        http_status=response.status_code,
                        endpoint="/api/v2/mix/market/tickers",
                        method="GET",
                    )

            except httpx.TimeoutException as e:
                error_msg = f"Request timeout for {symbol}: {e}"
                logger.error(error_msg)
                raise BitgetAPIError(
                    code="timeout",
                    message=error_msg,
                    data={"symbol": symbol},
                    endpoint="/api/v2/mix/market/tickers",
                    method="GET",
                )
            except httpx.RequestError as e:
                error_msg = f"Network error for {symbol}: {e}"
                logger.error(error_msg)
                raise BitgetAPIError(
                    code="network_error",
                    message=error_msg,
                    data={"symbol": symbol},
                    endpoint="/api/v2/mix/market/tickers",
                    method="GET",
                )
            except BitgetAPIError:
                raise
            except Exception as e:
                error_msg = f"Failed to get futures market price for {symbol}: {e}"
                logger.error(error_msg)
                raise Exception(error_msg)

    async def get_trading_pairs(self, product_type: str = "USDT-FUTURES", force_refresh: bool = False) -> List[Dict]:
        cached = self._contracts_cache.get(product_type)
        if not force_refresh and cached and time.time() - cached["cached_at"] < self._contracts_cache_ttl_seconds:
            return cached["data"]

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{Config.BITGET_API_URL}/api/v2/mix/market/contracts?productType={product_type}"
                )
                response.raise_for_status()
                data = response.json()

                if data.get("code") == "00000":
                    contracts = data.get("data", [])
                    self._contracts_cache[product_type] = {
                        "cached_at": time.time(),
                        "data": contracts,
                    }
                    return contracts
                else:
                    raise BitgetAPIError(
                        code=data.get("code"),
                        message=data.get("msg", "Failed to get futures trading pairs"),
                        data=data,
                        http_status=response.status_code,
                        endpoint="/api/v2/mix/market/contracts",
                        method="GET",
                    )

            except httpx.TimeoutException as e:
                logger.error(f"Timeout getting futures trading pairs: {e}")
                raise BitgetAPIError(
                    code="timeout",
                    message="Bitget request timeout",
                    data={"product_type": product_type},
                    endpoint="/api/v2/mix/market/contracts",
                    method="GET",
                )
            except httpx.RequestError as e:
                logger.error(f"Network error getting futures trading pairs: {e}")
                raise BitgetAPIError(
                    code="network_error",
                    message="Bitget network request error",
                    data={"product_type": product_type},
                    endpoint="/api/v2/mix/market/contracts",
                    method="GET",
                )
            except Exception as e:
                logger.error(f"Failed to get futures trading pairs: {e}")
                raise

    async def get_candles(
        self,
        symbol: str,
        granularity: str = "1H",
        limit: int = 120,
        product_type: str = "USDT-FUTURES",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[MarketCandle]:
        normalized_symbol = symbol.upper()
        endpoint = "/api/v2/mix/market/candles"
        params = {
            "symbol": normalized_symbol,
            "granularity": granularity,
            "limit": str(limit),
            "productType": product_type,
            "kLineType": "MARKET",
        }
        if start_time is not None:
            params["startTime"] = str(_datetime_to_millis(start_time))
        if end_time is not None:
            params["endTime"] = str(_datetime_to_millis(end_time))

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(f"{Config.BITGET_API_URL}{endpoint}", params=params)
                if response.status_code != 200:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    logger.error(error_msg)
                    raise BitgetAPIError(
                        code=str(response.status_code),
                        message=error_msg,
                        data={"response": response.text[:1000]},
                        http_status=response.status_code,
                        endpoint=endpoint,
                        method="GET",
                    )

                data = response.json()
                if data.get("code") != "00000":
                    error_msg = f"API returned error: {data}"
                    logger.error(error_msg)
                    raise BitgetAPIError(
                        code=data.get("code"),
                        message=data.get("msg", error_msg),
                        data=data,
                        http_status=response.status_code,
                        endpoint=endpoint,
                        method="GET",
                    )

                return parse_bitget_candles_payload(data.get("data") or [])

            except httpx.TimeoutException as e:
                logger.error(f"Timeout getting candles for {normalized_symbol}: {e}")
                raise BitgetAPIError(
                    code="timeout",
                    message="Bitget request timeout",
                    data={"symbol": normalized_symbol, "granularity": granularity},
                    endpoint=endpoint,
                    method="GET",
                )
            except httpx.RequestError as e:
                logger.error(f"Network error getting candles for {normalized_symbol}: {e}")
                raise BitgetAPIError(
                    code="network_error",
                    message="Bitget network request error",
                    data={"symbol": normalized_symbol, "granularity": granularity},
                    endpoint=endpoint,
                    method="GET",
                )

    async def get_contract_rules(self, symbol: str, product_type: str = "USDT-FUTURES") -> Dict:
        normalized_symbol = symbol.upper()
        contracts = await self.get_trading_pairs(product_type)

        for contract in contracts:
            if contract.get("symbol") == normalized_symbol:
                return contract

        contracts = await self.get_trading_pairs(product_type, force_refresh=True)
        for contract in contracts:
            if contract.get("symbol") == normalized_symbol:
                return contract

        raise ValueError(f"交易对 {normalized_symbol} 不存在或不支持 U 本位合约")
