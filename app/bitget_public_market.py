import logging
import time
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from .bitget_errors import BitgetAPIError
from .config import Config
from .decimal_utils import to_decimal
from .market_types import MarketCandle

logger = logging.getLogger(__name__)


def parse_bitget_candles_payload(raw_candles: list[list[str]]) -> list[MarketCandle]:
    candles = []
    for row in raw_candles:
        if len(row) < 6:
            raise ValueError("invalid candle row")

        timestamp = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC)
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
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


class BitgetPublicMarket:
    """Public Bitget market data and contract-rule cache."""

    def __init__(self, contracts_cache_ttl_seconds: int = 600):
        self._contracts_cache = {}
        self._contracts_cache_ttl_seconds = contracts_cache_ttl_seconds
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def get_market_price(self, symbol: str) -> Decimal:
        normalized_symbol = symbol.upper()
        endpoint = "/api/v2/mix/market/ticker"
        params = {
            "symbol": normalized_symbol,
            "productType": "USDT-FUTURES",
        }
        try:
            logger.info(f"Getting futures market price for {normalized_symbol}")

            url = f"{Config.BITGET_API_URL}{endpoint}"

            logger.info(f"Fetching from URL: {url}")
            response = await self.client.get(url, params=params)

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError as e:
                    raise BitgetAPIError(
                        code="invalid_json_response",
                        message=f"Invalid JSON response from Bitget HTTP {response.status_code}",
                        data={"response": response.text[:1000]},
                        http_status=response.status_code,
                        endpoint=endpoint,
                        method="GET",
                    ) from e

                tickers = data.get("data")
                if data.get("code") == "00000" and tickers:
                    ticker = tickers[0] if isinstance(tickers, list) else tickers
                    if not isinstance(ticker, dict):
                        error_msg = f"Bitget ticker response has invalid data for {normalized_symbol}"
                        logger.error(error_msg)
                        raise BitgetAPIError(
                            code="invalid_ticker_response",
                            message=error_msg,
                            data=data,
                            http_status=response.status_code,
                            endpoint=endpoint,
                            method="GET",
                        )
                    last_price = ticker.get("lastPr")
                    if last_price is None:
                        error_msg = f"Bitget ticker response missing lastPr for {normalized_symbol}"
                        logger.error(error_msg)
                        raise BitgetAPIError(
                            code="invalid_ticker_response",
                            message=error_msg,
                            data=data,
                            http_status=response.status_code,
                            endpoint=endpoint,
                            method="GET",
                        )

                    try:
                        price = to_decimal(last_price)
                    except ValueError as e:
                        error_msg = f"Bitget ticker response has invalid lastPr for {normalized_symbol}"
                        logger.error(error_msg)
                        raise BitgetAPIError(
                            code="invalid_ticker_response",
                            message=error_msg,
                            data=data,
                            http_status=response.status_code,
                            endpoint=endpoint,
                            method="GET",
                        ) from e
                    logger.info(f"Found price for {normalized_symbol}: {price}")
                    return price
                if data.get("code") == "00000":
                    error_msg = f"Symbol {normalized_symbol} not found in Bitget futures ticker"
                    logger.error(error_msg)
                    raise BitgetAPIError(
                        code="symbol_not_found",
                        message=error_msg,
                        data={"symbol": normalized_symbol},
                        http_status=response.status_code,
                        endpoint=endpoint,
                        method="GET",
                    )
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

        except httpx.TimeoutException as e:
            error_msg = f"Request timeout for {normalized_symbol}: {e}"
            logger.error(error_msg)
            raise BitgetAPIError(
                code="timeout",
                message=error_msg,
                data={"symbol": normalized_symbol},
                endpoint=endpoint,
                method="GET",
            ) from e
        except httpx.RequestError as e:
            error_msg = f"Network error for {normalized_symbol}: {e}"
            logger.error(error_msg)
            raise BitgetAPIError(
                code="network_error",
                message=error_msg,
                data={"symbol": normalized_symbol},
                endpoint=endpoint,
                method="GET",
            ) from e
        except BitgetAPIError:
            raise

    async def get_trading_pairs(self, product_type: str = "USDT-FUTURES", force_refresh: bool = False) -> list[dict]:
        cached = self._contracts_cache.get(product_type)
        if not force_refresh and cached and time.time() - cached["cached_at"] < self._contracts_cache_ttl_seconds:
            return cached["data"]

        endpoint = "/api/v2/mix/market/contracts"
        params = {"productType": product_type}
        try:
            response = await self.client.get(f"{Config.BITGET_API_URL}{endpoint}", params=params)
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
            try:
                data = response.json()
            except ValueError as e:
                raise BitgetAPIError(
                    code="invalid_json_response",
                    message=f"Invalid JSON response from Bitget HTTP {response.status_code}",
                    data={"response": response.text[:1000]},
                    http_status=response.status_code,
                    endpoint=endpoint,
                    method="GET",
                ) from e

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
                    endpoint=endpoint,
                    method="GET",
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting futures trading pairs: {e}")
            raise BitgetAPIError(
                code="timeout",
                message="Bitget request timeout",
                data={"product_type": product_type},
                endpoint=endpoint,
                method="GET",
            ) from e
        except httpx.RequestError as e:
            logger.error(f"Network error getting futures trading pairs: {e}")
            raise BitgetAPIError(
                code="network_error",
                message="Bitget network request error",
                data={"product_type": product_type},
                endpoint=endpoint,
                method="GET",
            ) from e
        except BitgetAPIError:
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

        try:
            response = await self.client.get(f"{Config.BITGET_API_URL}{endpoint}", params=params)
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

            try:
                data = response.json()
            except ValueError as e:
                raise BitgetAPIError(
                    code="invalid_json_response",
                    message=f"Invalid JSON response from Bitget HTTP {response.status_code}",
                    data={"response": response.text[:1000]},
                    http_status=response.status_code,
                    endpoint=endpoint,
                    method="GET",
                ) from e
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
            ) from e
        except httpx.RequestError as e:
            logger.error(f"Network error getting candles for {normalized_symbol}: {e}")
            raise BitgetAPIError(
                code="network_error",
                message="Bitget network request error",
                data={"symbol": normalized_symbol, "granularity": granularity},
                endpoint=endpoint,
                method="GET",
            ) from e

    async def get_contract_rules(self, symbol: str, product_type: str = "USDT-FUTURES") -> dict:
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
