import logging

from telegram import Update
from telegram.ext import ContextTypes

from .audit import emit_audit_event
from .bot_keyboards import signal_order_keyboard
from .bot_messages import (
    signal_message,
    signal_sent_message,
    signal_usage_message,
)
from .order_flow import parse_signal_args
from .order_interaction_service import ConfirmedOrderRequest, TelegramOrderFlowService

logger = logging.getLogger(__name__)


class OrderHandlersMixin:
    async def _record_bitget_failure_alert(self, classified_error, source: str, details: dict | None = None):
        return None

    def _order_flow_service(self) -> TelegramOrderFlowService:
        return TelegramOrderFlowService(
            bot=self.application.bot,
            user_repo=self.user_repo,
            pending_order_repo=self.pending_order_repo,
            trade_repo=self.trade_repo,
            trade_manager=self.trade_manager,
            system_log_repo=self.system_log_repo,
            audit_owner=self,
            failure_alert_handler=self._record_bitget_failure_alert,
        )

    async def send_signal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a trading signal to configured channels."""
        user = await self._get_or_create_user(update)

        if not await self._is_trader_or_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有发送交易信号的权限")
            return

        args = context.args
        if len(args) < 3:
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
                        channel_markup = reply_markup if channel_data["forward_with_buttons"] else None
                        send_kwargs = {}
                        if channel_data.get("message_thread_id"):
                            send_kwargs["message_thread_id"] = channel_data["message_thread_id"]

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
                    "status": ("completed" if channel_error is None else "completed_with_channel_lookup_error"),
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
            await update.message.reply_text("❌ 格式错误，请使用 entry[] sl[] tp[]，并输入有效数字")
        except Exception as e:
            logger.error(f"Send signal error: {e}")
            await emit_audit_event(
                self,
                user,
                "signal_sent",
                {"status": "failed", "reason": type(e).__name__},
            )
            await update.message.reply_text("❌ 发送信号时发生错误", parse_mode="Markdown")

    async def _handle_place_order_callback(self, query, user, data):
        """Handle market or limit order button."""
        return await self._order_flow_service().handle_place_order_callback(query, user, data)

    async def _send_private_message(self, query, user, text, reply_markup=None):
        """Send a private Telegram message to the user."""
        return await self._order_flow_service().send_private_message(query, user, text, reply_markup)

    async def _handle_confirm_pending_order_callback(self, query, user, data):
        """Handle pending order confirmation."""
        return await self._order_flow_service().handle_confirm_pending_order_callback(query, user, data)

    async def _handle_cancel_pending_order_callback(self, query, user, data):
        """Handle pending order cancellation."""
        return await self._order_flow_service().handle_cancel_pending_order_callback(query, user, data)

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
        return await self._order_flow_service().execute_order(
            ConfirmedOrderRequest(
                query=query,
                user=user,
                symbol=symbol,
                direction=direction,
                quantity=quantity,
                stop_loss=stop_loss,
                position_value=position_value,
                current_price=current_price,
                order_mode=order_mode,
                limit_price=limit_price,
                pending_order_token=pending_order_token,
            )
        )
