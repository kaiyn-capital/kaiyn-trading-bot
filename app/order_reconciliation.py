import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from telegram.error import TelegramError

from .audit import summarize_identifier
from .bitget_errors import BitgetAPIError, ClassifiedBitgetError, classify_bitget_exception
from .order_flow import build_client_order_id
from .telegram_formatting import HTML_PARSE_MODE, html_escape
from .time_utils import utc_now_naive

logger = logging.getLogger(__name__)

RETRY_ORDER_MESSAGE = (
    "⚠️ <b>订单未完成</b>\n\n"
    "这笔确认单没有在 Bitget 成功完成，系统不会自动重送。\n\n"
    "请回到原交易信号，重新按一次市价/限价下单。"
)

ORDER_NOT_FOUND_CODES = {"25204", "45057", "43001"}
OPEN_EXCHANGE_STATUSES = {"live", "partially_filled"}
FILLED_EXCHANGE_STATUSES = {"filled"}
CANCELLED_EXCHANGE_STATUSES = {"canceled", "cancelled"}
FAILED_EXCHANGE_STATUSES = {"failed", "rejected"}


class InvalidHistoryPayloadError(ValueError):
    def __init__(self, details: dict[str, str]):
        super().__init__("invalid_history_payload")
        self.details = details


@dataclass
class PendingOrderReconciliationSummary:
    scanned: int = 0
    recovered: int = 0
    failed: int = 0
    manual_review: int = 0


class PendingOrderReconciliationService:
    """Recover stale processing pending orders by querying Bitget with clientOid."""

    def __init__(
        self,
        *,
        bot: Any,
        user_repo: Any,
        pending_order_repo: Any,
        trade_repo: Any,
        trade_manager: Any,
        system_log_repo: Any,
        alert_manager: Any,
    ) -> None:
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
        now: datetime | None = None,
    ) -> PendingOrderReconciliationSummary:
        now = now or utc_now_naive()
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
                summary.manual_review += 1

        return summary

    async def _reconcile_one(self, pending_order: Any) -> str:
        client_order_id = build_client_order_id(pending_order.token)
        user = await self.user_repo.get_user_by_telegram_id(pending_order.telegram_id)

        if not _has_api_credentials(user):
            await self._mark_manual_review_with_admin_alert(
                pending_order,
                client_order_id,
                "Cannot reconcile processing order because user API credentials are missing",
                {"reason": "missing_user_or_api_credentials"},
            )
            return "manual_review"

        credentials = (
            user.encrypted_api_key,
            user.encrypted_secret_key,
            user.encrypted_passphrase,
        )
        trade = await self.trade_repo.get_by_client_order_id(client_order_id)

        try:
            order_data = await self._find_bitget_order(user, credentials, pending_order, client_order_id)
        except BitgetAPIError as exc:
            classified = classify_bitget_exception(exc)
            await self._record_query_failure(pending_order, client_order_id, classified)
            return "manual_review"
        except InvalidHistoryPayloadError as exc:
            await self._mark_manual_review_with_admin_alert(
                pending_order,
                client_order_id,
                "Cannot reconcile processing order because Bitget history payload is invalid",
                {"reason": "invalid_history_payload", **exc.details},
            )
            return "manual_review"
        except (RuntimeError, TypeError, ValueError) as exc:
            logger.exception("Unexpected error while reconciling processing order")
            classified = classify_bitget_exception(exc)
            await self._record_unexpected_failure(pending_order, client_order_id, classified, exc)
            return "manual_review"

        if order_data is None:
            await self._mark_failed_not_found(pending_order, trade, client_order_id)
            return "failed"

        exchange_status = _extract_exchange_status(order_data)
        local_status = _map_exchange_status(exchange_status)
        if local_status is None:
            await self._mark_manual_review_with_admin_alert(
                pending_order,
                client_order_id,
                "Cannot reconcile processing order because Bitget returned an unknown order status",
                {
                    "reason": "unknown_exchange_status",
                    "exchange_status": exchange_status,
                    "order": _summarize_order_data(order_data),
                },
            )
            return "manual_review"

        try:
            trade = trade or await self._create_recovered_trade(
                pending_order,
                user,
                client_order_id,
                order_data,
            )
            await self._update_trade_from_order(trade.id, order_data, local_status)
        except (TypeError, ValueError) as exc:
            await self._mark_manual_review_with_admin_alert(
                pending_order,
                client_order_id,
                "Cannot reconcile processing order because Bitget returned invalid numeric trade data",
                {
                    "reason": "invalid_numeric_trade_data",
                    "exception_type": type(exc).__name__,
                    "error": str(exc),
                    "order": _summarize_order_data(order_data),
                },
            )
            return "manual_review"

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

    async def _find_bitget_order(
        self,
        user: Any,
        credentials: tuple[str, str, str],
        pending_order: Any,
        client_order_id: str,
    ) -> dict[str, Any] | None:
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
        except BitgetAPIError as exc:
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
        except BitgetAPIError as exc:
            if _is_order_not_found_error(exc):
                return None
            raise

        if not isinstance(history, dict):
            raise InvalidHistoryPayloadError({"history_type": type(history).__name__})

        data = history.get("data")
        if not isinstance(data, dict):
            raise InvalidHistoryPayloadError(
                {
                    "history_type": type(history).__name__,
                    "data_type": type(data).__name__,
                }
            )

        orders = data.get("entrustedList")
        if not isinstance(orders, list):
            raise InvalidHistoryPayloadError(
                {
                    "history_type": type(history).__name__,
                    "data_type": type(data).__name__,
                    "entrusted_list_type": type(orders).__name__,
                }
            )

        for order in orders:
            if not isinstance(order, dict):
                raise InvalidHistoryPayloadError(
                    {
                        "history_type": type(history).__name__,
                        "data_type": type(data).__name__,
                        "entrusted_list_type": type(orders).__name__,
                        "order_type": type(order).__name__,
                    }
                )
            if order.get("clientOid") == client_order_id:
                return order
        return None

    async def _create_recovered_trade(
        self,
        pending_order: Any,
        user: Any,
        client_order_id: str,
        order_data: dict[str, Any],
    ) -> Any:
        order_type = str(order_data.get("orderType") or pending_order.order_mode or "market").strip().lower()
        if order_type not in {"market", "limit"}:
            order_type = pending_order.order_mode if pending_order.order_mode in {"market", "limit"} else "market"

        exchange_price = (
            _parse_optional_decimal(order_data.get("price"), field_name="price") if order_type == "limit" else None
        )
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

    async def _update_trade_from_order(
        self,
        trade_id: int,
        order_data: dict[str, Any],
        local_status: str,
    ) -> None:
        await self.trade_repo.update_trade_result(
            trade_id,
            bitget_order_id=order_data.get("orderId") or None,
            status=local_status,
            filled_quantity=_parse_decimal(
                order_data.get("baseVolume"),
                default=Decimal("0"),
                field_name="baseVolume",
            ),
            avg_price=_parse_optional_decimal(order_data.get("priceAvg"), field_name="priceAvg"),
            total_amount=_parse_optional_decimal(order_data.get("quoteVolume"), field_name="quoteVolume"),
            fee=_parse_decimal(order_data.get("fee"), default=Decimal("0"), field_name="fee"),
        )

    async def _mark_failed_not_found(self, pending_order: Any, trade: Any, client_order_id: str) -> None:
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
        pending_order: Any,
        client_order_id: str,
        classified: ClassifiedBitgetError,
    ) -> None:
        await self._mark_manual_review_with_admin_alert(
            pending_order,
            client_order_id,
            "Cannot reconcile processing order because Bitget lookup failed",
            {"classified_error": classified.to_log_data()},
        )

    async def _record_unexpected_failure(
        self,
        pending_order: Any,
        client_order_id: str,
        classified: ClassifiedBitgetError,
        exc: Exception,
    ) -> None:
        await self._mark_manual_review_with_admin_alert(
            pending_order,
            client_order_id,
            "Cannot reconcile processing order because an unexpected local error occurred",
            {
                "classified_error": classified.to_log_data(),
                "exception_type": type(exc).__name__,
            },
        )

    async def _mark_manual_review_with_admin_alert(
        self,
        pending_order: Any,
        client_order_id: str,
        message: str,
        extra_data: dict[str, Any],
    ) -> None:
        await self._log_reconciliation_event("WARNING", message, pending_order, client_order_id, extra_data)
        alert_detail_lines = []
        if "exchange_status" in extra_data:
            alert_detail_lines.append(f"Exchange Status：{html_escape(str(extra_data['exchange_status']))}")
        if "order" in extra_data:
            alert_detail_lines.append(f"Order Summary：{html_escape(str(extra_data['order']))}")
        alert_details = "\n" + "\n".join(alert_detail_lines) if alert_detail_lines else ""
        await self.alert_manager.send_alert(
            "⚠️ Kaiyn Trading Bot 订单需要人工核对。\n\n"
            f"Symbol：{html_escape(pending_order.symbol)}\n"
            f"Pending Token：{html_escape(summarize_identifier(pending_order.token))}\n"
            f"Client OID：{html_escape(summarize_identifier(client_order_id))}\n"
            f"原因：{html_escape(message)}"
            f"{alert_details}",
            alert_key="pending_order_manual_review",
        )
        await self.pending_order_repo.mark_manual_review(pending_order.token, message)

    async def _notify_user_to_retry(self, telegram_id: int) -> None:
        try:
            await self.bot.send_message(chat_id=telegram_id, text=RETRY_ORDER_MESSAGE, parse_mode=HTML_PARSE_MODE)
        except TelegramError as exc:
            logger.warning("Failed to notify user about failed processing order: %s", exc)

    async def _log_reconciliation_event(
        self,
        level: str,
        message: str,
        pending_order: Any,
        client_order_id: str,
        extra_data: dict[str, Any],
    ) -> None:
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
        except SQLAlchemyError as exc:
            logger.exception("Failed to persist order reconciliation log: %s", exc)


def _has_api_credentials(user: Any) -> bool:
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


def _extract_exchange_status(order_data: dict[str, Any]) -> str | None:
    value = order_data.get("state") or order_data.get("status")
    return str(value).strip().lower() if value else None


def _map_exchange_status(exchange_status: str | None) -> str | None:
    if exchange_status in OPEN_EXCHANGE_STATUSES:
        return "pending"
    if exchange_status in FILLED_EXCHANGE_STATUSES:
        return "filled"
    if exchange_status in CANCELLED_EXCHANGE_STATUSES:
        return "cancelled"
    if exchange_status in FAILED_EXCHANGE_STATUSES:
        return "failed"
    return None


def _side_from_pending_order(pending_order: Any) -> str:
    return "buy" if pending_order.direction == "long" else "sell"


def _parse_optional_decimal(value: Any, *, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _coerce_decimal_value(value, field_name=field_name)


def _parse_decimal(value: Any, default: Decimal, *, field_name: str) -> Decimal:
    if value is None:
        return default
    parsed = _coerce_decimal_value(value, field_name=field_name)
    return default if parsed is None else parsed


def _coerce_decimal_value(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, float):
        decimal_value = Decimal(str(value))
    elif isinstance(value, (str, int)) and not isinstance(value, bool):
        if value == "":
            raise ValueError(f"{field_name} contains an empty decimal value")
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name} contains an invalid decimal value") from exc
    else:
        raise TypeError(f"{field_name} has unsupported decimal type: {type(value).__name__}")

    if not decimal_value.is_finite():
        raise ValueError(f"{field_name} contains a non-finite decimal value")
    return decimal_value


def _summarize_order_data(order_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "orderId": summarize_identifier(order_data.get("orderId")),
        "clientOid": summarize_identifier(order_data.get("clientOid")),
        "state": order_data.get("state"),
        "status": order_data.get("status"),
        "orderType": order_data.get("orderType"),
    }
