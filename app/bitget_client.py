import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from .bitget_errors import BitgetAPIError
from .log_sanitizer import summarize_http_error, summarize_order_payload
from .settings import Settings

logger = logging.getLogger(__name__)


class BitgetAPIClient:
    """Low-level authenticated Bitget API client."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        passphrase: str,
        *,
        base_url: str | None = None,
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = base_url or Settings.from_env().bitget_api_url
        self.client = httpx.AsyncClient(
            timeout=30.0, limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        message = timestamp + method + request_path + body
        mac = hmac.new(self.secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _get_headers(self, method: str, request_path: str, body: str = "") -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp, method, request_path, body)

        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "zh-CN",
        }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"

        query_string = ""
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            if query_string:
                url += f"?{query_string}"

        body = ""
        if data:
            body = json.dumps(data, separators=(",", ":"))

        headers = self._get_headers(method, endpoint + (f"?{query_string}" if query_string else ""), body)

        try:
            if method == "GET":
                response = await self.client.get(url, headers=headers)
            elif method == "POST":
                response = await self.client.post(url, headers=headers, content=body)
            elif method == "PUT":
                response = await self.client.put(url, headers=headers, content=body)
            elif method == "DELETE":
                response = await self.client.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            try:
                result = response.json()
            except ValueError as e:
                raise BitgetAPIError(
                    code=str(response.status_code),
                    message=f"Invalid JSON response from Bitget HTTP {response.status_code}",
                    data={"response": response.text[:1000]},
                    http_status=response.status_code,
                    endpoint=endpoint,
                    method=method,
                ) from e

            if result.get("code") != "00000":
                raise BitgetAPIError(
                    code=result.get("code"),
                    message=result.get("msg", "Unknown error"),
                    data=result,
                    http_status=response.status_code,
                    endpoint=endpoint,
                    method=method,
                )

            if response.status_code >= 400:
                logger.warning(
                    "HTTP status indicates error despite Bitget success code: %s",
                    {
                        "http_status": response.status_code,
                        "endpoint": endpoint,
                        "method": method,
                    },
                )
                raise BitgetAPIError(
                    code=str(response.status_code),
                    message=f"HTTP {response.status_code}",
                    data=result,
                    http_status=response.status_code,
                    endpoint=endpoint,
                    method=method,
                )

            return result

        except httpx.HTTPStatusError as e:
            logger.error(
                "Bitget HTTP error summary: %s",
                {
                    **summarize_http_error(e.response.status_code, e.response.text),
                    "endpoint": endpoint,
                    "method": method,
                },
            )
            try:
                error_data = e.response.json()
                if "code" in error_data and "msg" in error_data:
                    logger.info(f"Parsed Bitget error: code={error_data.get('code')}, msg={error_data.get('msg')}")
                    raise BitgetAPIError(
                        code=error_data.get("code"),
                        message=error_data.get("msg", "Unknown error"),
                        data=error_data,
                        http_status=e.response.status_code,
                        endpoint=endpoint,
                        method=method,
                    )
            except BitgetAPIError:
                raise
            except ValueError as json_error:
                logger.warning(f"Failed to parse error JSON: {json_error}")

            raise BitgetAPIError(
                code=str(e.response.status_code),
                message=f"HTTP {e.response.status_code}",
                data={"response": e.response.text},
                http_status=e.response.status_code,
                endpoint=endpoint,
                method=method,
            ) from e
        except httpx.TimeoutException as e:
            logger.error(f"Bitget request timeout: {method} {endpoint}: {e}")
            raise BitgetAPIError(
                code="timeout",
                message="Bitget request timeout",
                data={"error": str(e)},
                endpoint=endpoint,
                method=method,
            ) from e
        except httpx.RequestError as e:
            logger.error(f"Bitget network request error: {method} {endpoint}: {e}")
            raise BitgetAPIError(
                code="network_error",
                message="Bitget network request error",
                data={"error": str(e)},
                endpoint=endpoint,
                method=method,
            ) from e
        except BitgetAPIError:
            raise

    async def get_account_info(self, product_type: str = "USDT-FUTURES") -> dict[str, Any]:
        params = {"productType": product_type}
        return await self._make_request("GET", "/api/v2/mix/account/account", params=params)

    async def get_account_assets(self, product_type: str = "USDT-FUTURES") -> dict[str, Any]:
        params = {"productType": product_type}
        return await self._make_request("GET", "/api/v2/mix/account/accounts", params=params)

    async def get_positions(self, product_type: str = "USDT-FUTURES") -> dict[str, Any]:
        params = {"productType": product_type}
        return await self._make_request("GET", "/api/v2/mix/position/all-position", params=params)

    async def set_position_mode(
        self, product_type: str = "USDT-FUTURES", pos_mode: str = "hedge_mode"
    ) -> dict[str, Any]:
        data = {
            "productType": product_type,
            "posMode": pos_mode,
        }
        return await self._make_request("POST", "/api/v2/mix/account/set-position-mode", data=data)

    async def get_symbols(self, product_type: str = "USDT-FUTURES") -> dict[str, Any]:
        params = {"productType": product_type}
        return await self._make_request("GET", "/api/v2/mix/market/contracts", params=params)

    async def get_ticker(self, symbol: str, product_type: str = "USDT-FUTURES") -> dict[str, Any]:
        params = {"symbol": symbol, "productType": product_type}
        return await self._make_request("GET", "/api/v2/mix/market/ticker", params=params)

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: str,
        price: str | None = None,
        client_order_id: str | None = None,
        margin_coin: str = "USDT",
        margin_mode: str = "crossed",
        product_type: str = "USDT-FUTURES",
        trade_side: str = "open",
        stop_loss_price: str | None = None,
        take_profit_price: str | None = None,
        force: str | None = None,
    ) -> dict[str, Any]:
        data = {
            "marginCoin": margin_coin,
            "marginMode": margin_mode,
            "productType": product_type,
            "orderType": order_type,
            "side": side,
            "size": size,
            "symbol": symbol,
            "tradeSide": trade_side,
        }

        if price and order_type == "limit":
            data["price"] = price

        if force and order_type == "limit":
            data["force"] = force

        if client_order_id:
            data["clientOid"] = client_order_id

        if stop_loss_price:
            data["presetStopLossPrice"] = str(stop_loss_price)

        if take_profit_price:
            data["presetStopSurplusPrice"] = str(take_profit_price)

        logger.info("Placing order summary: %s", summarize_order_payload(data))
        return await self._make_request("POST", "/api/v2/mix/order/place-order", data=data)

    async def cancel_order(
        self,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
        margin_coin: str = "USDT",
    ) -> dict[str, Any]:
        data = {"symbol": symbol, "marginCoin": margin_coin}

        if order_id:
            data["orderId"] = order_id
        elif client_order_id:
            data["clientOid"] = client_order_id
        else:
            raise ValueError("Either order_id or client_order_id must be provided")

        return await self._make_request("POST", "/api/v2/mix/order/cancel-order", data=data)

    async def get_order_info(
        self,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
        product_type: str = "USDT-FUTURES",
    ) -> dict[str, Any]:
        params = {"symbol": symbol, "productType": product_type}

        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["clientOid"] = client_order_id
        else:
            raise ValueError("Either order_id or client_order_id must be provided")

        return await self._make_request("GET", "/api/v2/mix/order/detail", params=params)

    async def get_order_history(
        self,
        symbol: str | None = None,
        limit: int = 50,
        product_type: str = "USDT-FUTURES",
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        params = {"productType": product_type, "limit": str(limit)}

        if symbol:
            params["symbol"] = symbol
        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["clientOid"] = client_order_id

        return await self._make_request("GET", "/api/v2/mix/order/orders-history", params=params)

    async def get_account_uid(self) -> dict[str, Any]:
        return await self._make_request("GET", "/api/v2/spot/account/info")

    async def close(self) -> None:
        await self.client.aclose()
