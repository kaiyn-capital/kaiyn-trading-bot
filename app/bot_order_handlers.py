import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from .audit import emit_audit_event, summarize_identifier
from .bitget_errors import classify_bitget_exception
from .bot_keyboards import pending_order_keyboard, signal_order_keyboard
from .bot_messages import (
    order_preview_message,
    order_success_message,
    signal_message,
    signal_sent_message,
    signal_usage_message,
)
from .order_flow import (
    OrderPreview,
    apply_order_validation,
    execute_order as execute_order_flow,
    parse_contract_rules,
    parse_order_callback_data,
    parse_signal_args,
    prepare_order_preview,
    validate_order_preview,
)

logger = logging.getLogger(__name__)


class OrderHandlersMixin:
    async def _record_bitget_failure_alert(
        self, classified_error, source: str, details: dict | None = None
    ):
        return None

    async def send_signal_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Send a trading signal to configured channels."""
        user = await self._get_or_create_user(update)

        if not await self._is_trader_or_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有发送交易信号的权限")
            return

        args = context.args
        if len(args) < 6:
            await update.message.reply_text(signal_usage_message(), parse_mode="Markdown")
            return

        try:
            signal = parse_signal_args(args)

            if signal.direction not in ["long", "short"]:
                await update.message.reply_text("❌ 交易方向必须是 long 或 short")
                return

            sender_username = self._get_sender_username(update)
            signal_text = signal_message(signal, sender_username)
            reply_markup = signal_order_keyboard(
                signal.symbol,
                signal.direction,
                signal.entry_lower,
                signal.entry_upper,
                signal.stop_loss,
            )

            sent_to_channels = 0
            failed_channels = 0
            target_count = 0
            channel_error = None
            try:
                channels_data = await self.channel_repo.get_signal_channels()
                target_count = len(channels_data)

                for channel_data in channels_data:
                    try:
                        channel_markup = (
                            reply_markup
                            if channel_data["forward_with_buttons"]
                            else None
                        )
                        send_kwargs = {}
                        if channel_data.get("message_thread_id"):
                            send_kwargs["message_thread_id"] = channel_data[
                                "message_thread_id"
                            ]

                        await context.bot.send_message(
                            chat_id=channel_data["chat_id"],
                            text=signal_text,
                            reply_markup=channel_markup,
                            parse_mode="Markdown",
                            **send_kwargs,
                        )
                        sent_to_channels += 1
                    except Exception as e:
                        failed_channels += 1
                        logger.warning(
                            "Failed to send signal to channel "
                            f"{channel_data['chat_id']} "
                            f"thread={channel_data.get('message_thread_id')}: {e}"
                        )

            except Exception as e:
                channel_error = type(e).__name__
                logger.error(f"Error getting channels: {e}")

            await update.message.reply_text(
                signal_sent_message(sent_to_channels, signal_text),
                parse_mode="Markdown",
            )
            await emit_audit_event(
                self,
                user,
                "signal_sent",
                {
                    "status": (
                        "completed"
                        if channel_error is None
                        else "completed_with_channel_lookup_error"
                    ),
                    "symbol": signal.symbol,
                    "direction": signal.direction,
                    "entry_lower": signal.entry_lower,
                    "entry_upper": signal.entry_upper,
                    "stop_loss": signal.stop_loss,
                    "take_profit_levels": signal.take_profit_levels,
                    "remark": signal.remark,
                    "target_count": target_count,
                    "sent_count": sent_to_channels,
                    "failed_count": failed_channels,
                    "reason": channel_error,
                },
            )

        except ValueError:
            await update.message.reply_text("❌ 价格格式错误，请输入有效数字")
        except Exception as e:
            logger.error(f"Send signal error: {e}")
            await emit_audit_event(
                self,
                user,
                "signal_sent",
                {"status": "failed", "reason": type(e).__name__},
            )
            await update.message.reply_text(
                "❌ 发送信号时发生错误", parse_mode="Markdown"
            )

    async def _handle_place_order_callback(self, query, user, data):
        """Handle market or limit order button."""
        await query.answer("正在处理下单请求...")

        try:
            callback_data = parse_order_callback_data(data)
        except (ValueError, IndexError):
            await emit_audit_event(
                self,
                user,
                "order_place_clicked",
                {"status": "failed", "reason": "invalid_callback_data"},
            )
            await self._send_private_message(query, user, "❌ 交易信号数据解析失败")
            return

        await emit_audit_event(
            self,
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
                self,
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
            await self._send_private_message(
                query,
                user,
                "❌ **无法下单**\n\n"
                "您尚未连接 Bitget API。\n\n"
                "请使用 `/setapi` 命令设置您的 API 密钥。",
            )
            return

        if not getattr(user_data, "fixed_risk_amount", None):
            await emit_audit_event(
                self,
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
            await self._send_private_message(
                query,
                user,
                "❌ **无法下单**\n\n"
                "您尚未设定固定风险金额(1R)。\n\n"
                "请使用 `/settings` 命令设置您的风险管理参数。",
            )
            return

        try:
            await self._send_private_message(
                query, user, "🔄 正在获取当前市价与交易规则..."
            )

            contract_payload = await self.trade_manager.get_contract_rules(
                callback_data.symbol
            )
            contract_rules = parse_contract_rules(contract_payload)
            current_price = await self.trade_manager.get_market_price(
                callback_data.symbol
            )

            try:
                preview = prepare_order_preview(
                    callback_data, current_price, user_data.fixed_risk_amount
                )
            except ValueError as e:
                if "entry price" in str(e):
                    await emit_audit_event(
                        self,
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
                    await self._send_private_message(
                        query, user, "❌ 进场价格错误，无法计算仓位"
                    )
                    return
                await emit_audit_event(
                    self,
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
                await self._send_private_message(
                    query, user, "❌ 止损价格设置错误，无法计算仓位"
                )
                return

            validation = validate_order_preview(
                preview, contract_rules, callback_data.direction
            )
            if not validation.is_valid:
                await emit_audit_event(
                    self,
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
                await self._send_private_message(
                    query, user, validation.error_message or "❌ 无法下单"
                )
                return

            preview = apply_order_validation(preview, validation)

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
                self,
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

            await self._send_private_message(
                query,
                user,
                order_preview_message(
                    callback_data.symbol, callback_data.direction, preview
                ),
                pending_order_keyboard(pending_order.token),
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
                self,
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
            await self._send_private_message(
                query,
                user,
                f"❌ 无法获取 {callback_data.symbol} 当前价格或交易规则。\n\n"
                f"{classified.user_message}",
            )

    async def _send_private_message(self, query, user, text, reply_markup=None):
        """Send a private Telegram message to the user."""
        try:
            await self.application.bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Failed to send private message to {user.telegram_id}: {e}")
            try:
                await query.answer(f"请查看私人聊天: {text[:50]}...")
            except Exception:
                pass

    async def _handle_confirm_pending_order_callback(self, query, user, data):
        """Handle pending order confirmation."""
        try:
            token = data.removeprefix("confirm_order_")
            pending_order, status = await self.pending_order_repo.claim_pending_order(
                token, user.telegram_id
            )

            if not pending_order:
                await emit_audit_event(
                    self,
                    user,
                    "pending_order_confirm",
                    {
                        "status": "missing",
                        "pending_order_token": summarize_identifier(token),
                    },
                )
                await self._send_private_message(
                    query, user, "❌ 找不到这笔待确认订单，请重新点击最新信号下单。"
                )
                return

            if status == "expired":
                await emit_audit_event(
                    self,
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
                await self._send_private_message(
                    query, user, "❌ 这笔待确认订单已过期，请重新点击信号下单。"
                )
                return

            if status != "processing":
                await emit_audit_event(
                    self,
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
                await self._send_private_message(
                    query, user, f"⚠️ 这笔待确认订单目前状态为 {status}，无法重复执行。"
                )
                return

            await emit_audit_event(
                self,
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
            await self._execute_order(
                query,
                user,
                pending_order.symbol,
                pending_order.direction,
                pending_order.quantity,
                pending_order.stop_loss,
                pending_order.position_value,
                pending_order.current_price,
                order_mode=pending_order.order_mode,
                limit_price=pending_order.limit_price,
                pending_order_token=token,
            )

        except Exception as e:
            logger.error(f"Confirm pending order error: {e}")
            await emit_audit_event(
                self,
                user,
                "pending_order_confirm",
                {
                    "status": "failed",
                    "reason": type(e).__name__,
                    "pending_order_token": summarize_identifier(
                        data.removeprefix("confirm_order_")
                    ),
                },
            )
            await self._send_private_message(query, user, "❌ 确认下单时发生错误")

    async def _handle_cancel_pending_order_callback(self, query, user, data):
        """Handle pending order cancellation."""
        token = data.removeprefix("cancel_order_")
        status = await self.pending_order_repo.cancel_pending_order(
            token, user.telegram_id
        )

        await emit_audit_event(
            self,
            user,
            "pending_order_cancel",
            {
                "status": status,
                "pending_order_token": summarize_identifier(token),
            },
        )

        if status == "cancelled":
            await query.answer("已取消下单")
            await self._send_private_message(query, user, "✅ 已取消下单")
        elif status == "missing":
            await self._send_private_message(query, user, "❌ 找不到这笔待确认订单")
        else:
            await self._send_private_message(
                query, user, f"⚠️ 这笔待确认订单目前状态为 {status}，无法取消。"
            )

    async def _execute_order(
        self,
        query,
        user,
        symbol,
        direction,
        quantity,
        stop_loss,
        position_value,
        current_price,
        order_mode="market",
        limit_price=None,
        pending_order_token=None,
    ):
        """Execute a confirmed order."""
        await query.answer("正在执行下单...")
        await self._send_private_message(query, user, "🔄 **正在执行下单...**")

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

            order_mode = order_mode if order_mode in {"market", "limit"} else "market"
            contract_payload = await self.trade_manager.get_contract_rules(symbol)
            contract_rules = parse_contract_rules(contract_payload)
            current_price = await self.trade_manager.get_market_price(symbol)
            calculation_price = (
                limit_price
                if order_mode == "limit" and limit_price is not None
                else current_price
            )
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
            validation = validate_order_preview(
                validation_preview, contract_rules, direction
            )
            if not validation.is_valid:
                error_message = validation.error_message or "❌ 订单已不符合交易所规则"
                if pending_order_token:
                    await self.pending_order_repo.mark_failed(
                        pending_order_token, error_message
                    )
                await emit_audit_event(
                    self,
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
                        "pending_order_token": summarize_identifier(
                            pending_order_token
                        ),
                    },
                )
                await self._send_private_message(
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

            logger.info(
                f"Executing {order_mode} order for {symbol}, direction: {direction}, "
                f"quantity: {quantity}, limit_price: {limit_price}"
            )

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
            )

            if pending_order_token:
                await self.pending_order_repo.mark_executed(
                    pending_order_token, result.trade_id
                )

            await self._send_private_message(
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
                self,
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
                await self.pending_order_repo.mark_failed(
                    pending_order_token, classified.storage_message()
                )

            await emit_audit_event(
                self,
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
                        "pending_order_token": summarize_identifier(
                            pending_order_token
                        ),
                        "classified_error": classified.to_log_data(),
                    },
                )
            except Exception as log_error:
                logger.error(f"Failed to log Bitget order error: {log_error}")

            await self._send_private_message(
                query,
                user,
                f"❌ **下单失败**\n\n{classified.user_message}",
            )
            return False
