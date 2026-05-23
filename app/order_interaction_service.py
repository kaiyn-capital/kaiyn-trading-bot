import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .audit import emit_audit_event, summarize_identifier
from .bitget_errors import classify_bitget_exception
from .bot_keyboards import pending_order_keyboard
from .bot_messages import order_preview_message, order_success_message
from .decimal_utils import decimal_json, to_decimal, to_decimal_or_none
from .order_flow import (
    OrderCallbackData,
    OrderPreview,
    apply_order_validation,
    build_client_order_id,
    parse_contract_rules,
    parse_tokenized_callback_data,
    prepare_order_preview,
    validate_order_preview,
)
from .order_flow import (
    execute_order as execute_order_flow,
)
from .risk_limits import (
    RiskLimitExceeded,
    ensure_daily_trade_limit_not_reached,
    ensure_position_within_limit,
    get_daily_limit_day_start_utc,
    get_effective_daily_trade_limit,
    get_effective_position_limit,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfirmedOrderRequest:
    query: Any
    user: Any
    symbol: str
    direction: str
    quantity: Decimal
    stop_loss: Decimal
    position_value: Decimal
    current_price: Decimal
    order_mode: str = "market"
    limit_price: Decimal | None = None
    pending_order_token: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "quantity", to_decimal(self.quantity))
        object.__setattr__(self, "stop_loss", to_decimal(self.stop_loss))
        object.__setattr__(self, "position_value", to_decimal(self.position_value))
        object.__setattr__(self, "current_price", to_decimal(self.current_price))
        if self.limit_price is not None:
            object.__setattr__(self, "limit_price", to_decimal(self.limit_price))


class TelegramOrderFlowService:
    """Telegram-facing order callback and pending-order flow."""

    def __init__(
        self,
        *,
        bot,
        user_repo,
        pending_order_repo,
        trade_repo,
        trade_manager,
        system_log_repo,
        audit_owner,
        failure_alert_handler=None,
        signal_record_repo=None,
    ):
        self.bot = bot
        self.user_repo = user_repo
        self.pending_order_repo = pending_order_repo
        self.trade_repo = trade_repo
        self.trade_manager = trade_manager
        self.system_log_repo = system_log_repo
        self.audit_owner = audit_owner
        self.failure_alert_handler = failure_alert_handler
        self.signal_record_repo = signal_record_repo

    async def _record_bitget_failure_alert(self, classified_error, source: str, details: dict | None = None):
        if self.failure_alert_handler:
            await self.failure_alert_handler(classified_error, source, details)

    async def _get_daily_trade_count(self, user_data, day_start_utc: datetime) -> int:
        return await self.trade_repo.count_daily_non_failed_trades(user_data.id, day_start_utc)

    async def _ensure_daily_trade_limit_available(self, user_data, day_start_utc: datetime) -> int:
        daily_trade_limit = get_effective_daily_trade_limit(user_data)
        current_count = await self._get_daily_trade_count(user_data, day_start_utc)
        ensure_daily_trade_limit_not_reached(
            current_count=current_count,
            daily_trade_limit=daily_trade_limit,
            day_start_utc=day_start_utc,
        )
        return daily_trade_limit

    async def _log_risk_limit_block(self, user, user_data, risk_error: RiskLimitExceeded, symbol: str, details: dict):
        try:
            await self.system_log_repo.log(
                level="WARNING",
                message="Order blocked by local risk limit",
                module="risk_limits",
                function=details.get("function"),
                user_id=getattr(user_data, "id", None),
                telegram_id=user.telegram_id,
                extra_data={
                    "symbol": symbol,
                    "reason": risk_error.reason,
                    **risk_error.details,
                    **details,
                },
            )
        except Exception as exc:
            logger.error("Failed to log risk limit block: %s", exc)

    async def _send_risk_limit_block_message(
        self,
        *,
        query,
        user,
        user_data,
        risk_error: RiskLimitExceeded,
        symbol: str,
        direction: str,
        order_mode: str,
        action: str,
        pending_order_token: str | None = None,
        position_value=None,
        mark_pending_failed: bool = False,
    ):
        if mark_pending_failed and pending_order_token:
            await self.pending_order_repo.mark_failed(pending_order_token, risk_error.user_message)

        details = {
            "status": "failed" if mark_pending_failed else "blocked",
            "reason": risk_error.reason,
            "symbol": symbol,
            "direction": direction,
            "order_mode": order_mode,
            "position_value": decimal_json(position_value),
            "effective_position_limit": decimal_json(get_effective_position_limit(user_data)),
            "effective_daily_trade_limit": get_effective_daily_trade_limit(user_data),
            "pending_order_token": summarize_identifier(pending_order_token),
            **risk_error.details,
        }
        await emit_audit_event(self.audit_owner, user, action, details)
        await self._log_risk_limit_block(
            user,
            user_data,
            risk_error,
            symbol,
            {
                **details,
                "function": action,
            },
        )
        await self.send_private_message(query, user, risk_error.user_message)

    async def send_private_message(self, query, user, text, reply_markup=None):
        """Send a private Telegram message to the user."""
        try:
            await self.bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Failed to send private message to {user.telegram_id}: {e}")
            with contextlib.suppress(Exception):
                await query.answer(f"请查看私人聊天: {text[:50]}...")

    async def handle_place_order_callback(self, query, user, data):
        """Handle market or limit order button."""
        await query.answer("正在处理下单请求...")

        try:
            order_mode, token = parse_tokenized_callback_data(data)
        except (ValueError, IndexError):
            await emit_audit_event(
                self.audit_owner,
                user,
                "order_place_clicked",
                {"status": "failed", "reason": "invalid_callback_data"},
            )
            await self.send_private_message(query, user, "❌ 交易信号数据解析失败")
            return

        record = None
        if self.signal_record_repo:
            record = await self.signal_record_repo.get_by_public_id(token)

        if not record or record.get("status") in {"cancelled", "expired", "preview_pending"}:
            reason = "signal_not_found" if not record else f"signal_{record.get('status')}"
            await emit_audit_event(
                self.audit_owner,
                user,
                "order_place_blocked",
                {
                    "status": "blocked",
                    "reason": reason,
                    "token": token,
                    "requested_order_mode": order_mode,
                },
            )
            await self.send_private_message(
                query,
                user,
                "❌ 无法下单：该交易信号不存在或已过期。",
            )
            return

        callback_data = OrderCallbackData(
            order_mode=order_mode,
            symbol=record["symbol"],
            direction=record["direction"],
            entry_lower=to_decimal(record["entry_lower"]),
            entry_upper=to_decimal(record["entry_upper"]),
            stop_loss=to_decimal(record["stop_loss"]),
        )

        await emit_audit_event(
            self.audit_owner,
            user,
            "order_place_clicked",
            {
                "status": "received",
                "symbol": callback_data.symbol,
                "direction": callback_data.direction,
                "requested_order_mode": callback_data.order_mode,
            },
        )

        user_data = await self.user_repo.get_user_by_telegram_id(user.telegram_id)

        if not user_data or not user_data.is_api_connected:
            await emit_audit_event(
                self.audit_owner,
                user,
                "order_place_blocked",
                {
                    "status": "blocked",
                    "reason": "api_not_connected",
                    "symbol": callback_data.symbol,
                    "direction": callback_data.direction,
                    "requested_order_mode": callback_data.order_mode,
                },
            )
            await self.send_private_message(
                query,
                user,
                "❌ **无法下单**\n\n您尚未连接 Bitget API。\n\n请使用 `/setapi` 命令设置您的 API 密钥。",
            )
            return

        if not getattr(user_data, "fixed_risk_amount", None):
            await emit_audit_event(
                self.audit_owner,
                user,
                "order_place_blocked",
                {
                    "status": "blocked",
                    "reason": "fixed_risk_not_set",
                    "symbol": callback_data.symbol,
                    "direction": callback_data.direction,
                    "requested_order_mode": callback_data.order_mode,
                },
            )
            await self.send_private_message(
                query,
                user,
                "❌ **无法下单**\n\n您尚未设定固定风险金额(1R)。\n\n请使用 `/settings` 命令设置您的风险管理参数。",
            )
            return

        try:
            day_start_utc = get_daily_limit_day_start_utc()
            await self._ensure_daily_trade_limit_available(user_data, day_start_utc)

            await self.send_private_message(query, user, "🔄 正在获取当前市价与交易规则...")

            contract_payload = await self.trade_manager.get_contract_rules(callback_data.symbol)
            contract_rules = parse_contract_rules(contract_payload)
            current_price = await self.trade_manager.get_market_price(callback_data.symbol)

            try:
                preview = prepare_order_preview(callback_data, current_price, user_data.fixed_risk_amount)
            except ValueError as e:
                if "entry price" in str(e):
                    await emit_audit_event(
                        self.audit_owner,
                        user,
                        "order_place_blocked",
                        {
                            "status": "blocked",
                            "reason": "invalid_entry_price",
                            "symbol": callback_data.symbol,
                            "direction": callback_data.direction,
                            "requested_order_mode": callback_data.order_mode,
                        },
                    )
                    await self.send_private_message(query, user, "❌ 进场价格错误，无法计算仓位")
                    return
                await emit_audit_event(
                    self.audit_owner,
                    user,
                    "order_place_blocked",
                    {
                        "status": "blocked",
                        "reason": "invalid_stop_loss",
                        "symbol": callback_data.symbol,
                        "direction": callback_data.direction,
                        "requested_order_mode": callback_data.order_mode,
                    },
                )
                await self.send_private_message(query, user, "❌ 止损价格设置错误，无法计算仓位")
                return

            validation = validate_order_preview(preview, contract_rules, callback_data.direction)
            if not validation.is_valid:
                await emit_audit_event(
                    self.audit_owner,
                    user,
                    "order_place_blocked",
                    {
                        "status": "blocked",
                        "reason": "validation_failed",
                        "symbol": callback_data.symbol,
                        "direction": callback_data.direction,
                        "requested_order_mode": callback_data.order_mode,
                        "error_message": validation.error_message,
                    },
                )
                await self.send_private_message(query, user, validation.error_message or "❌ 无法下单")
                return

            preview = apply_order_validation(preview, validation)
            ensure_position_within_limit(preview.position_value, user_data)

            pending_order = await self.pending_order_repo.create_pending_order(
                user_id=user_data.id,
                telegram_id=user.telegram_id,
                symbol=callback_data.symbol,
                direction=callback_data.direction,
                order_mode=preview.order_mode,
                limit_price=preview.limit_price,
                entry_lower=preview.entry_lower,
                entry_upper=preview.entry_upper,
                quantity=preview.quantity,
                stop_loss=preview.stop_loss,
                position_value=preview.position_value,
                current_price=preview.current_price,
                expires_at=datetime.utcnow() + timedelta(minutes=10),
            )
            logger.info(
                f"Stored {preview.order_mode} pending order {pending_order.token} "
                f"for user {user.telegram_id}; "
                f"requested_mode={preview.requested_order_mode}"
            )
            await emit_audit_event(
                self.audit_owner,
                user,
                "pending_order_created",
                {
                    "status": "pending",
                    "symbol": callback_data.symbol,
                    "direction": callback_data.direction,
                    "requested_order_mode": preview.requested_order_mode,
                    "order_mode": preview.order_mode,
                    "limit_price": preview.limit_price,
                    "quantity": preview.quantity,
                    "position_value": preview.position_value,
                    "expires_at": pending_order.expires_at,
                    "pending_order_id": getattr(pending_order, "id", None),
                    "pending_order_token": summarize_identifier(pending_order.token),
                },
            )

            await self.send_private_message(
                query,
                user,
                order_preview_message(callback_data.symbol, callback_data.direction, preview),
                pending_order_keyboard(pending_order.token),
            )

        except RiskLimitExceeded as e:
            await self._send_risk_limit_block_message(
                query=query,
                user=user,
                user_data=user_data,
                risk_error=e,
                symbol=callback_data.symbol,
                direction=callback_data.direction,
                order_mode=callback_data.order_mode,
                action="order_place_blocked",
                position_value=e.details.get("position_value"),
            )
        except Exception as e:
            classified = classify_bitget_exception(e)
            logger.error(f"Place order callback error: {classified.storage_message()}")
            await self._record_bitget_failure_alert(
                classified,
                "_handle_place_order_callback",
                {
                    "telegram_id": user.telegram_id,
                    "symbol": callback_data.symbol,
                    "order_mode": callback_data.order_mode,
                },
            )
            await emit_audit_event(
                self.audit_owner,
                user,
                "pending_order_create_failed",
                {
                    "status": "failed",
                    "symbol": callback_data.symbol,
                    "direction": callback_data.direction,
                    "requested_order_mode": callback_data.order_mode,
                    "error_category": classified.category.value,
                    "raw_code": classified.raw_code,
                    "raw_message": classified.raw_message,
                },
            )
            await self.send_private_message(
                query,
                user,
                f"❌ 无法获取 {callback_data.symbol} 当前价格或交易规则。\n\n{classified.user_message}",
            )

    async def handle_confirm_pending_order_callback(self, query, user, data):
        """Handle pending order confirmation."""
        try:
            token = data.removeprefix("confirm_order_")
            pending_order, status = await self.pending_order_repo.claim_pending_order(token, user.telegram_id)

            if not pending_order:
                await emit_audit_event(
                    self.audit_owner,
                    user,
                    "pending_order_confirm",
                    {
                        "status": "missing",
                        "pending_order_token": summarize_identifier(token),
                    },
                )
                await self.send_private_message(query, user, "❌ 找不到这笔待确认订单，请重新点击最新信号下单。")
                return

            if status == "expired":
                await emit_audit_event(
                    self.audit_owner,
                    user,
                    "pending_order_confirm",
                    {
                        "status": "expired",
                        "symbol": pending_order.symbol,
                        "direction": pending_order.direction,
                        "order_mode": pending_order.order_mode,
                        "pending_order_token": summarize_identifier(token),
                    },
                )
                await self.send_private_message(query, user, "❌ 这笔待确认订单已过期，请重新点击信号下单。")
                return

            if status != "processing":
                await emit_audit_event(
                    self.audit_owner,
                    user,
                    "pending_order_confirm",
                    {
                        "status": status,
                        "symbol": pending_order.symbol,
                        "direction": pending_order.direction,
                        "order_mode": pending_order.order_mode,
                        "pending_order_token": summarize_identifier(token),
                    },
                )
                await self.send_private_message(query, user, f"⚠️ 这笔待确认订单目前状态为 {status}，无法重复执行。")
                return

            await emit_audit_event(
                self.audit_owner,
                user,
                "pending_order_confirm",
                {
                    "status": "processing",
                    "symbol": pending_order.symbol,
                    "direction": pending_order.direction,
                    "order_mode": pending_order.order_mode,
                    "quantity": pending_order.quantity,
                    "position_value": pending_order.position_value,
                    "pending_order_token": summarize_identifier(token),
                },
            )
            await self.execute_order(
                ConfirmedOrderRequest(
                    query=query,
                    user=user,
                    symbol=pending_order.symbol,
                    direction=pending_order.direction,
                    quantity=pending_order.quantity,
                    stop_loss=pending_order.stop_loss,
                    position_value=pending_order.position_value,
                    current_price=pending_order.current_price,
                    order_mode=pending_order.order_mode,
                    limit_price=pending_order.limit_price,
                    pending_order_token=token,
                )
            )

        except Exception as e:
            logger.error(f"Confirm pending order error: {e}")
            await emit_audit_event(
                self.audit_owner,
                user,
                "pending_order_confirm",
                {
                    "status": "failed",
                    "reason": type(e).__name__,
                    "pending_order_token": summarize_identifier(data.removeprefix("confirm_order_")),
                },
            )
            await self.send_private_message(query, user, "❌ 确认下单时发生错误")

    async def handle_cancel_pending_order_callback(self, query, user, data):
        """Handle pending order cancellation."""
        token = data.removeprefix("cancel_order_")
        status = await self.pending_order_repo.cancel_pending_order(token, user.telegram_id)

        await emit_audit_event(
            self.audit_owner,
            user,
            "pending_order_cancel",
            {
                "status": status,
                "pending_order_token": summarize_identifier(token),
            },
        )

        if status == "cancelled":
            await query.answer("已取消下单")
            await self.send_private_message(query, user, "✅ 已取消下单")
        elif status == "missing":
            await self.send_private_message(query, user, "❌ 找不到这笔待确认订单")
        else:
            await self.send_private_message(query, user, f"⚠️ 这笔待确认订单目前状态为 {status}，无法取消。")

    async def execute_order(self, request: ConfirmedOrderRequest):
        """Execute a confirmed order."""
        query = request.query
        user = request.user
        symbol = request.symbol
        direction = request.direction
        quantity = to_decimal(request.quantity)
        stop_loss = to_decimal(request.stop_loss)
        position_value = to_decimal(request.position_value)
        current_price = to_decimal(request.current_price)
        order_mode = request.order_mode
        limit_price = to_decimal_or_none(request.limit_price)
        pending_order_token = request.pending_order_token

        await query.answer("正在执行下单...")
        await self.send_private_message(query, user, "🔄 **正在执行下单...**")

        try:
            user_data = await self.user_repo.get_user_by_telegram_id(user.telegram_id)
            if (
                not user_data
                or not user_data.is_api_connected
                or not all(
                    [
                        user_data.encrypted_api_key,
                        user_data.encrypted_secret_key,
                        user_data.encrypted_passphrase,
                    ]
                )
            ):
                raise RuntimeError("User API credentials are not configured")

            credentials = (
                user_data.encrypted_api_key,
                user_data.encrypted_secret_key,
                user_data.encrypted_passphrase,
            )
            day_start_utc = get_daily_limit_day_start_utc()
            daily_trade_limit = await self._ensure_daily_trade_limit_available(user_data, day_start_utc)

            order_mode = order_mode if order_mode in {"market", "limit"} else "market"
            contract_payload = await self.trade_manager.get_contract_rules(symbol)
            contract_rules = parse_contract_rules(contract_payload)
            current_price = await self.trade_manager.get_market_price(symbol)
            current_price = to_decimal(current_price)
            calculation_price = limit_price if order_mode == "limit" and limit_price is not None else current_price
            if calculation_price <= 0:
                raise RuntimeError("Invalid calculation price")

            stop_distance_pct = abs((calculation_price - stop_loss) / calculation_price)
            if stop_distance_pct <= 0:
                raise RuntimeError("Invalid stop distance")

            validation_preview = OrderPreview(
                requested_order_mode=order_mode,
                order_mode=order_mode,
                limit_price=limit_price,
                entry_lower=calculation_price,
                entry_upper=calculation_price,
                quantity=quantity,
                stop_loss=stop_loss,
                position_value=position_value,
                current_price=current_price,
                risk_amount=user_data.fixed_risk_amount,
                stop_distance_pct=stop_distance_pct,
            )
            validation = validate_order_preview(validation_preview, contract_rules, direction)
            if not validation.is_valid:
                error_message = validation.error_message or "❌ 订单已不符合交易所规则"
                if pending_order_token:
                    await self.pending_order_repo.mark_failed(pending_order_token, error_message)
                await emit_audit_event(
                    self.audit_owner,
                    user,
                    "order_validation_failed",
                    {
                        "status": "failed",
                        "reason": "validation_failed",
                        "symbol": symbol,
                        "direction": direction,
                        "order_mode": order_mode,
                        "quantity": quantity,
                        "position_value": position_value,
                        "limit_price": limit_price,
                        "error_message": error_message,
                        "pending_order_token": summarize_identifier(pending_order_token),
                    },
                )
                await self.send_private_message(
                    query,
                    user,
                    "❌ **订单已不符合交易所规则，请重新点击最新信号下单。**\n\n"
                    f"原因：{error_message.replace('❌ ', '')}",
                )
                return False

            quantity = validation.quantity or quantity
            position_value = validation.position_value or position_value
            if order_mode == "limit":
                limit_price = validation.limit_price
            ensure_position_within_limit(position_value, user_data)

            logger.info(
                f"Executing {order_mode} order for {symbol}, direction: {direction}, "
                f"quantity: {quantity}, limit_price: {limit_price}"
            )
            client_order_id = build_client_order_id(pending_order_token)

            result = await execute_order_flow(
                user_data=user_data,
                trade_repo=self.trade_repo,
                trade_manager=self.trade_manager,
                credentials=credentials,
                telegram_id=user.telegram_id,
                symbol=symbol,
                direction=direction,
                quantity=quantity,
                stop_loss=stop_loss,
                position_value=position_value,
                order_mode=order_mode,
                limit_price=limit_price,
                quantity_text=validation.quantity_text,
                limit_price_text=validation.limit_price_text,
                client_order_id=client_order_id,
                daily_trade_limit=daily_trade_limit,
                daily_limit_day_start_utc=day_start_utc,
            )

            if pending_order_token:
                await self.pending_order_repo.mark_executed(pending_order_token, result.trade_id)

            await self.send_private_message(
                query,
                user,
                order_success_message(
                    result,
                    direction,
                    stop_loss,
                    current_price,
                    user_data.fixed_risk_amount,
                ),
            )

            await emit_audit_event(
                self.audit_owner,
                user,
                "order_executed",
                {
                    "status": result.status,
                    "symbol": result.symbol,
                    "direction": direction,
                    "quantity": result.quantity,
                    "position_value": result.position_value,
                    "bitget_order_id": summarize_identifier(result.bitget_order_id),
                    "stop_loss": stop_loss,
                    "order_mode": result.order_type,
                    "limit_price": result.limit_price,
                    "trade_id": result.trade_id,
                    "pending_order_token": summarize_identifier(pending_order_token),
                },
            )
            return True

        except RiskLimitExceeded as e:
            await self._send_risk_limit_block_message(
                query=query,
                user=user,
                user_data=user_data,
                risk_error=e,
                symbol=symbol,
                direction=direction,
                order_mode=order_mode,
                action="order_risk_limit_failed",
                pending_order_token=pending_order_token,
                position_value=e.details.get("position_value", position_value),
                mark_pending_failed=True,
            )
            return False

        except Exception as e:
            classified = classify_bitget_exception(e)
            logger.error(f"Order execution error: {classified.storage_message()}")
            await self._record_bitget_failure_alert(
                classified,
                "_execute_order",
                {
                    "telegram_id": user.telegram_id,
                    "symbol": symbol,
                    "direction": direction,
                    "order_mode": order_mode,
                    "pending_order_token": summarize_identifier(pending_order_token),
                },
            )
            if pending_order_token:
                await self.pending_order_repo.mark_failed(pending_order_token, classified.storage_message())

            await emit_audit_event(
                self.audit_owner,
                user,
                "order_failed",
                {
                    "status": "failed",
                    "symbol": symbol,
                    "direction": direction,
                    "quantity": quantity,
                    "position_value": position_value,
                    "order_mode": order_mode,
                    "limit_price": limit_price,
                    "pending_order_token": summarize_identifier(pending_order_token),
                    "error_category": classified.category.value,
                    "raw_code": classified.raw_code,
                    "raw_message": classified.raw_message,
                    "http_status": classified.http_status,
                },
            )

            try:
                await self.system_log_repo.log(
                    level="ERROR",
                    message="Bitget order execution failed",
                    module="telegram_bot",
                    function="_execute_order",
                    user_id=getattr(user, "id", None),
                    telegram_id=user.telegram_id,
                    extra_data={
                        "symbol": symbol,
                        "direction": direction,
                        "quantity": quantity,
                        "position_value": position_value,
                        "order_mode": order_mode,
                        "limit_price": limit_price,
                        "pending_order_token": summarize_identifier(pending_order_token),
                        "classified_error": classified.to_log_data(),
                    },
                )
            except Exception as log_error:
                logger.error(f"Failed to log Bitget order error: {log_error}")

            await self.send_private_message(
                query,
                user,
                f"❌ **下单失败**\n\n{classified.user_message}",
            )
            return False
