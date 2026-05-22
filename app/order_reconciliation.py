import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from .audit import summarize_identifier
from .bitget_errors import ClassifiedBitgetError, classify_bitget_exception
from .decimal_utils import to_decimal_or_none
from .order_flow import build_client_order_id

logger = logging.getLogger(__name__)

RETRY_ORDER_MESSAGE = (
    "⚠️ **订单未完成**\n\n"
    "这笔确认单没有在 Bitget 成功完成，系统不会自动重送。\n\n"
    "请回到原交易信号，重新按一次市价/限价下单。"
)

ORDER_NOT_FOUND_CODES = {"25204", "45057", "43001"}
OPEN_EXCHANGE_STATUSES = {"live", "partially_filled"}
FILLED_EXCHANGE_STATUSES = {"filled"}
CANCELLED_EXCHANGE_STATUSES = {"canceled", "cancelled"}
FAILED_EXCHANGE_STATUSES = {"failed", "rejected"}


@dataclass
class PendingOrderReconciliationSummary:
    scanned: int = 0
    recovered: int = 0
    failed: int = 0
    deferred: int = 0


class PendingOrderReconciliationService:
    """Recover stale processing pending orders by querying Bitget with clientOid."""

    def __init__(
        self,
        *,
        bot,
        user_repo,
        pending_order_repo,
        trade_repo,
        trade_manager,
        system_log_repo,
        alert_manager,
    ):
        self.bot = bot
        self.user_repo = user_repo
        self.pending_order_repo = pending_order_repo
        self.trade_repo = trade_repo
        self.trade_manager = trade_manager
        self.system_log_repo = system_log_repo
        self.alert_manager = alert_manager

    async def reconcile_stale_processing_orders(
        self,
        *,
        stale_after_seconds: int,
        limit: int,
        now: Optional[datetime] = None,
    ) -> PendingOrderReconciliationSummary:
        now = now or datetime.utcnow()
        cutoff = now - timedelta(seconds=stale_after_seconds)
        pending_orders = await self.pending_order_repo.get_stale_processing_orders(cutoff, limit)
        summary = PendingOrderReconciliationSummary(scanned=len(pending_orders))

        for pending_order in pending_orders:
            outcome = await self._reconcile_one(pending_order)
            if outcome == "recovered":
                summary.recovered += 1
            elif outcome == "failed":
                summary.failed += 1
            else:
                summary.deferred += 1

        return summary

    async def _reconcile_one(self, pending_order) -> str:
        client_order_id = build_client_order_id(pending_order.token)
        user = await self.user_repo.get_user_by_telegram_id(pending_order.telegram_id)

        if not _has_api_credentials(user):
            await self._defer_with_admin_alert(
                pending_order,
                client_order_id,
                "Cannot reconcile processing order because user API credentials are missing",
                {"reason": "missing_user_or_api_credentials"},
            )
            return "deferred"

        credentials = (
            user.encrypted_api_key,
            user.encrypted_secret_key,
            user.encrypted_passphrase,
        )
        trade = await self.trade_repo.get_by_client_order_id(client_order_id)

        try:
            order_data = await self._find_bitget_order(user, credentials, pending_order, client_order_id)
        except Exception as exc:
            classified = classify_bitget_exception(exc)
            await self._record_query_failure(pending_order, client_order_id, classified)
            return "deferred"

        if order_data is None:
            await self._mark_failed_not_found(pending_order, trade, client_order_id)
            return "failed"

        exchange_status = _extract_exchange_status(order_data)
        local_status = _map_exchange_status(exchange_status)
        if local_status is None:
            await self._defer_with_admin_alert(
                pending_order,
                client_order_id,
                "Cannot reconcile processing order because Bitget returned an unknown order status",
                {
                    "reason": "unknown_exchange_status",
                    "exchange_status": exchange_status,
                    "order": _summarize_order_data(order_data),
                },
            )
            return "deferred"

        trade = trade or await self._create_recovered_trade(pending_order, user, client_order_id, order_data)
        await self._update_trade_from_order(trade.id, order_data, local_status)

        if local_status in {"cancelled", "failed"}:
            await self.pending_order_repo.mark_failed(pending_order.token, RETRY_ORDER_MESSAGE)
            await self._notify_user_to_retry(pending_order.telegram_id)
            await self._log_reconciliation_event(
                "WARNING",
                "Processing order resolved as failed by Bitget reconciliation",
                pending_order,
                client_order_id,
                {"exchange_status": exchange_status, "local_status": local_status},
            )
            return "failed"

        await self.pending_order_repo.mark_executed(pending_order.token, trade.id)
        await self._log_reconciliation_event(
            "INFO",
            "Processing order recovered by Bitget reconciliation",
            pending_order,
            client_order_id,
            {"exchange_status": exchange_status, "local_status": local_status},
        )
        return "recovered"

    async def _find_bitget_order(self, user, credentials, pending_order, client_order_id: str) -> Optional[dict]:
        try:
            detail = await self.trade_manager.get_order_status(
                user.id,
                credentials,
                pending_order.symbol,
                client_order_id=client_order_id,
                product_type="USDT-FUTURES",
            )
            data = detail.get("data") or {}
            if data:
                return data
        except Exception as exc:
            if not _is_order_not_found_error(exc):
                raise

        try:
            history = await self.trade_manager.get_order_history(
                user.id,
                credentials,
                symbol=pending_order.symbol,
                limit=20,
                product_type="USDT-FUTURES",
                client_order_id=client_order_id,
            )
        except Exception as exc:
            if _is_order_not_found_error(exc):
                return None
            raise

        orders = ((history.get("data") or {}).get("entrustedList")) or []
        for order in orders:
            if order.get("clientOid") == client_order_id:
                return order
        return None

    async def _create_recovered_trade(self, pending_order, user, client_order_id: str, order_data: dict):
        order_type = str(order_data.get("orderType") or pending_order.order_mode or "market").strip().lower()
        if order_type not in {"market", "limit"}:
            order_type = pending_order.order_mode if pending_order.order_mode in {"market", "limit"} else "market"

        exchange_price = _parse_optional_decimal(order_data.get("price"))
        return await self.trade_repo.create_trade(
            user_id=user.id,
            symbol=pending_order.symbol,
            side=_side_from_pending_order(pending_order),
            order_type=order_type,
            quantity=pending_order.quantity,
            price=(exchange_price if exchange_price is not None else pending_order.limit_price)
            if order_type == "limit"
            else None,
            client_order_id=client_order_id,
        )

    async def _update_trade_from_order(self, trade_id: int, order_data: dict, local_status: str):
        await self.trade_repo.update_trade_result(
            trade_id,
            bitget_order_id=order_data.get("orderId") or None,
            status=local_status,
            filled_quantity=_parse_decimal(order_data.get("baseVolume"), default=Decimal("0")),
            avg_price=_parse_optional_decimal(order_data.get("priceAvg")),
            total_amount=_parse_optional_decimal(order_data.get("quoteVolume")),
            fee=_parse_decimal(order_data.get("fee"), default=Decimal("0")),
        )

    async def _mark_failed_not_found(self, pending_order, trade, client_order_id: str):
        if trade:
            await self.trade_repo.update_trade_result(
                trade.id,
                bitget_order_id=getattr(trade, "bitget_order_id", None),
                status="failed",
                error_message="Bitget detail/history lookup found no order for clientOid",
            )
        await self.pending_order_repo.mark_failed(pending_order.token, RETRY_ORDER_MESSAGE)
        await self._notify_user_to_retry(pending_order.telegram_id)
        await self._log_reconciliation_event(
            "WARNING",
            "Processing order marked failed because Bitget detail/history lookup found no order",
            pending_order,
            client_order_id,
            {"reason": "order_not_found"},
        )

    async def _record_query_failure(
        self,
        pending_order,
        client_order_id: str,
        classified: ClassifiedBitgetError,
    ):
        await self._defer_with_admin_alert(
            pending_order,
            client_order_id,
            "Cannot reconcile processing order because Bitget lookup failed",
            {"classified_error": classified.to_log_data()},
        )

    async def _defer_with_admin_alert(self, pending_order, client_order_id: str, message: str, extra_data: dict):
        await self._log_reconciliation_event("WARNING", message, pending_order, client_order_id, extra_data)
        await self.alert_manager.send_alert(
            "⚠️ Kaiyn Trading Bot processing 订单查单无法完成。\n\n"
            f"Symbol：{pending_order.symbol}\n"
            f"Pending Token：{summarize_identifier(pending_order.token)}\n"
            f"Client OID：{summarize_identifier(client_order_id)}\n"
            f"原因：{message}",
            alert_key="pending_order_reconciliation_deferred",
        )

    async def _notify_user_to_retry(self, telegram_id: int):
        try:
            await self.bot.send_message(chat_id=telegram_id, text=RETRY_ORDER_MESSAGE, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Failed to notify user about failed processing order: %s", exc)

    async def _log_reconciliation_event(
        self,
        level: str,
        message: str,
        pending_order,
        client_order_id: str,
        extra_data: dict,
    ):
        try:
            await self.system_log_repo.log(
                level=level,
                message=message,
                module="order_reconciliation",
                function="reconcile_stale_processing_orders",
                user_id=pending_order.user_id,
                telegram_id=pending_order.telegram_id,
                extra_data={
                    "symbol": pending_order.symbol,
                    "pending_order_token": summarize_identifier(pending_order.token),
                    "client_order_id": summarize_identifier(client_order_id),
                    **extra_data,
                },
            )
        except Exception as exc:
            logger.error("Failed to persist order reconciliation log: %s", exc)


def _has_api_credentials(user) -> bool:
    return bool(
        user
        and getattr(user, "is_api_connected", False)
        and getattr(user, "encrypted_api_key", None)
        and getattr(user, "encrypted_secret_key", None)
        and getattr(user, "encrypted_passphrase", None)
    )


def _is_order_not_found_error(exc: Exception) -> bool:
    raw_code = str(getattr(exc, "code", "") or "")
    if raw_code in ORDER_NOT_FOUND_CODES:
        return True

    raw_message = str(getattr(exc, "message", "") or exc).lower()
    return ("order" in raw_message and "not exist" in raw_message) or "订单不存在" in raw_message


def _extract_exchange_status(order_data: dict) -> Optional[str]:
    value = order_data.get("state") or order_data.get("status")
    return str(value).strip().lower() if value else None


def _map_exchange_status(exchange_status: Optional[str]) -> Optional[str]:
    if exchange_status in OPEN_EXCHANGE_STATUSES:
        return "pending"
    if exchange_status in FILLED_EXCHANGE_STATUSES:
        return "filled"
    if exchange_status in CANCELLED_EXCHANGE_STATUSES:
        return "cancelled"
    if exchange_status in FAILED_EXCHANGE_STATUSES:
        return "failed"
    return None


def _side_from_pending_order(pending_order) -> str:
    return "buy" if pending_order.direction == "long" else "sell"


def _parse_optional_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    return to_decimal_or_none(value)


def _parse_decimal(value: Any, default: Decimal) -> Decimal:
    parsed = _parse_optional_decimal(value)
    return default if parsed is None else parsed


def _summarize_order_data(order_data: dict) -> dict:
    return {
        "orderId": summarize_identifier(order_data.get("orderId")),
        "clientOid": summarize_identifier(order_data.get("clientOid")),
        "state": order_data.get("state"),
        "status": order_data.get("status"),
        "orderType": order_data.get("orderType"),
    }
