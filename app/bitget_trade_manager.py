import contextlib
import logging
from decimal import Decimal

import httpx

from .bitget_client import BitgetAPIClient
from .bitget_errors import BitgetAPIError, classify_bitget_exception
from .bitget_public_market import BitgetPublicMarket
from .decimal_utils import decimal_text, to_decimal
from .encryption import EncryptionManager
from .log_sanitizer import summarize_order_response
from .market_types import MarketCandle
from .settings import Settings

logger = logging.getLogger(__name__)


class BitgetTradeManager:
    """Higher-level Bitget trading operations for bot users."""

    def __init__(self, encryption_manager: EncryptionManager, *, settings: Settings | None = None):
        self.encryption_manager = encryption_manager
        self.settings = settings or Settings.from_env()
        self._clients = {}
        self.public_market = BitgetPublicMarket(base_url=self.settings.bitget_api_url)

    def _get_client(self, user_id: int, encrypted_credentials: tuple[str, str, str]) -> BitgetAPIClient:
        if user_id not in self._clients:
            api_key, secret_key, passphrase = self.encryption_manager.decrypt_api_credentials(*encrypted_credentials)
            self._clients[user_id] = BitgetAPIClient(
                api_key,
                secret_key,
                passphrase,
                base_url=self.settings.bitget_api_url,
            )

        return self._clients[user_id]

    async def invalidate_user_client(self, user_id: int) -> bool:
        """Remove and close a cached authenticated client for one user."""
        client = self._clients.pop(user_id, None)
        if not client:
            return False

        try:
            await client.close()
        except (RuntimeError, httpx.HTTPError):
            logger.warning("Failed to close cached Bitget client for user_id=%s", user_id, exc_info=True)

        return True

    async def test_api_connection(self, encrypted_credentials: tuple[str, str, str]) -> tuple[bool, str]:
        client = None
        try:
            api_key, secret_key, passphrase = self.encryption_manager.decrypt_api_credentials(*encrypted_credentials)
            client = BitgetAPIClient(api_key, secret_key, passphrase, base_url=self.settings.bitget_api_url)

            result = await client.get_account_assets()

            if result.get("code") == "00000":
                return True, "API 連接成功"
            else:
                return False, f"API 錯誤: {result.get('msg', 'Unknown error')}"

        except BitgetAPIError as e:
            classified = classify_bitget_exception(e)
            return False, classified.user_message
        except (TypeError, ValueError) as e:
            logger.error(f"API 連接測試失敗: {e}")
            classified = classify_bitget_exception(e)
            return False, classified.user_message
        finally:
            if client:
                with contextlib.suppress(RuntimeError, httpx.HTTPError):
                    await client.close()

    async def get_account_balance(self, user_id: int, encrypted_credentials: tuple[str, str, str]) -> dict:
        client = self._get_client(user_id, encrypted_credentials)
        return await client.get_account_assets()

    async def get_user_uid(self, encrypted_credentials: tuple[str, str, str]) -> str:
        client = None
        try:
            api_key, secret_key, passphrase = self.encryption_manager.decrypt_api_credentials(*encrypted_credentials)
            client = BitgetAPIClient(api_key, secret_key, passphrase, base_url=self.settings.bitget_api_url)

            result = await client.get_account_uid()

            if result.get("code") == "00000" and result.get("data"):
                return result["data"].get("userId", "Unknown")
            else:
                return "Unknown"

        except (BitgetAPIError, TypeError, ValueError) as e:
            logger.error(f"Failed to get user UID: {e}")
            return "Unknown"
        finally:
            if client:
                with contextlib.suppress(RuntimeError, httpx.HTTPError):
                    await client.close()

    async def get_market_price(self, symbol: str) -> Decimal:
        return to_decimal(await self.public_market.get_market_price(symbol))

    async def get_trading_pairs(self, product_type: str = "USDT-FUTURES", force_refresh: bool = False) -> list[dict]:
        return await self.public_market.get_trading_pairs(product_type, force_refresh=force_refresh)

    async def get_contract_rules(self, symbol: str, product_type: str = "USDT-FUTURES") -> dict:
        return await self.public_market.get_contract_rules(symbol, product_type)

    async def get_candles(
        self,
        symbol: str,
        granularity: str = "1H",
        limit: int = 120,
        product_type: str = "USDT-FUTURES",
        start_time=None,
        end_time=None,
    ) -> list[MarketCandle]:
        return await self.public_market.get_candles(symbol, granularity, limit, product_type, start_time, end_time)

    async def place_market_order(
        self,
        user_id: int,
        encrypted_credentials: tuple[str, str, str],
        symbol: str,
        side: str,
        size: str,
        client_order_id: str = None,
        margin_coin: str = "USDT",
        trade_side: str = "open",
        stop_loss_price: Decimal = None,
        take_profit_price: Decimal = None,
    ) -> dict:
        client = self._get_client(user_id, encrypted_credentials)

        result = await client.place_order(
            symbol=symbol,
            side=side,
            order_type="market",
            size=size,
            client_order_id=client_order_id,
            margin_coin=margin_coin,
            margin_mode="crossed",
            trade_side=trade_side,
            stop_loss_price=decimal_text(stop_loss_price) if stop_loss_price else None,
            take_profit_price=decimal_text(take_profit_price) if take_profit_price else None,
        )
        logger.info("Market order placed summary: %s", summarize_order_response(result))
        return result

    async def place_limit_order(
        self,
        user_id: int,
        encrypted_credentials: tuple[str, str, str],
        symbol: str,
        side: str,
        size: str,
        price: str,
        client_order_id: str = None,
        margin_coin: str = "USDT",
        trade_side: str = "open",
        stop_loss_price: Decimal = None,
        take_profit_price: Decimal = None,
        force: str = "gtc",
    ) -> dict:
        client = self._get_client(user_id, encrypted_credentials)
        return await client.place_order(
            symbol=symbol,
            side=side,
            order_type="limit",
            size=size,
            price=price,
            client_order_id=client_order_id,
            margin_coin=margin_coin,
            margin_mode="crossed",
            trade_side=trade_side,
            stop_loss_price=decimal_text(stop_loss_price) if stop_loss_price else None,
            take_profit_price=decimal_text(take_profit_price) if take_profit_price else None,
            force=force,
        )

    async def get_order_status(
        self,
        user_id: int,
        encrypted_credentials: tuple[str, str, str],
        symbol: str,
        order_id: str = None,
        client_order_id: str = None,
        product_type: str = "USDT-FUTURES",
    ) -> dict:
        client = self._get_client(user_id, encrypted_credentials)
        return await client.get_order_info(symbol, order_id, client_order_id, product_type)

    async def get_order_history(
        self,
        user_id: int,
        encrypted_credentials: tuple[str, str, str],
        symbol: str = None,
        limit: int = 50,
        product_type: str = "USDT-FUTURES",
        order_id: str = None,
        client_order_id: str = None,
    ) -> dict:
        client = self._get_client(user_id, encrypted_credentials)
        return await client.get_order_history(
            symbol=symbol,
            limit=limit,
            product_type=product_type,
            order_id=order_id,
            client_order_id=client_order_id,
        )

    async def cancel_order(
        self,
        user_id: int,
        encrypted_credentials: tuple[str, str, str],
        symbol: str,
        order_id: str = None,
        client_order_id: str = None,
    ) -> dict:
        client = self._get_client(user_id, encrypted_credentials)
        return await client.cancel_order(symbol, order_id, client_order_id)

    async def cleanup(self):
        """Close all cached authenticated clients and the public market client."""
        for user_id, client in list(self._clients.items()):
            try:
                await client.close()
            except (RuntimeError, httpx.HTTPError):
                logger.warning(
                    "Failed to close cached Bitget client for user_id=%s during cleanup", user_id, exc_info=True
                )

        self._clients.clear()

        try:
            await self.public_market.close()
        except (RuntimeError, httpx.HTTPError):
            logger.warning("Failed to close Bitget public market client during cleanup", exc_info=True)
