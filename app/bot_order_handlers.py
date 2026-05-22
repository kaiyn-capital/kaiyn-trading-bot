import asyncio
import logging
import secrets
from datetime import datetime, timezone
from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes

from .audit import emit_audit_event
from .bot_keyboards import chart_update_preview_keyboard, signal_preview_keyboard
from .bot_messages import (
    chart_update_message,
    signal_usage_message,
)
from .config import Config
from .order_flow import parse_signal_args
from .order_interaction_service import ConfirmedOrderRequest, TelegramOrderFlowService
from .order_types import SignalDraft
from .signal_charts import render_signal_chart, render_signal_update_chart
from .signal_delivery_service import TELEGRAM_PHOTO_CAPTION_LIMIT, SignalDeliveryService
from .signal_record_service import SignalRecordService

logger = logging.getLogger(__name__)

SIGNAL_PREVIEW_STEP = "signal_preview"
SIGNAL_PREVIEW_EXPIRED_MESSAGE = "⏳ 预览已过期或已被新的信号取代，请重新发送 /send_signal"
SIGNAL_PREVIEW_PROMPT = "📋 **请确认是否转发以下交易信号**"
CHART_UPDATE_PREVIEW_STEP = "chart_update_preview"
CHART_UPDATE_PREVIEW_EXPIRED_MESSAGE = "⏳ 预览已过期或已被新的更新取代，请重新发送 /update_chart"
CHART_UPDATE_PREVIEW_PROMPT = "📋 **请确认是否转发以下图表更新**"


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
            signal_record_repo=self.signal_record_repo,
        )

    def _signal_record_service(self) -> SignalRecordService:
        return SignalRecordService(self.signal_record_repo)

    def _signal_delivery_service(self) -> SignalDeliveryService:
        return SignalDeliveryService(self.channel_repo, self.signal_record_repo)

    async def _mark_replaced_active_signal_preview(self, telegram_id: int) -> None:
        session = await self._get_active_preview_session(telegram_id)
        if not session or session.get("step") != SIGNAL_PREVIEW_STEP:
            return

        signal_record_id = session.get("signal_record_id")
        if signal_record_id:
            await self._signal_record_service().update_status(signal_record_id, "replaced")

    async def _get_active_preview_session(self, telegram_id: int) -> dict | None:
        session = self.user_sessions.get(telegram_id)
        if not session:
            return None

        expires_at = session.get("expires_at")
        if not isinstance(expires_at, datetime) or self._session_now() >= expires_at:
            if session.get("step") == SIGNAL_PREVIEW_STEP and session.get("signal_record_id"):
                await self._signal_record_service().update_status(session["signal_record_id"], "expired")
            self.user_sessions.pop(telegram_id, None)
            return None

        return session

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

            await self._mark_replaced_active_signal_preview(user.telegram_id)
            sender_username = self._get_sender_username(update)
            chart_bytes, chart_status, chart_error = await self._try_create_signal_chart(signal)
            signal_record, signal_text = await self._signal_record_service().create_signal_record(
                user=user,
                signal=signal,
                sender_username=sender_username,
                chart_status=chart_status,
                chart_error=chart_error,
            )
            token = secrets.token_urlsafe(8)
            self.set_user_session(
                user.telegram_id,
                {
                    "step": SIGNAL_PREVIEW_STEP,
                    "token": token,
                    "signal_record_id": signal_record["id"],
                    "signal_public_id": signal_record["public_id"],
                    "signal": signal,
                    "signal_text": signal_text,
                    "chart_bytes": chart_bytes,
                    "chart_status": chart_status,
                    "chart_error": chart_error,
                },
            )

            await self._send_signal_preview(update, signal, signal_text, chart_bytes, signal_preview_keyboard(token))
            await emit_audit_event(
                self,
                user,
                "signal_preview_created",
                {
                    "status": "pending",
                    "symbol": signal.symbol,
                    "direction": signal.direction,
                    "entry_lower": signal.entry_lower,
                    "entry_upper": signal.entry_upper,
                    "stop_loss": signal.stop_loss,
                    "take_profit_levels": signal.take_profit_levels,
                    "remark": signal.remark,
                    "signal_id": signal_record["public_id"],
                    "chart_status": chart_status,
                    "chart_error": chart_error,
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

    async def update_chart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create a confirmed chart update for an existing signal."""
        user = await self._get_or_create_user(update)
        args = context.args
        if not args:
            await update.message.reply_text("使用方法：`/update_chart 交易id [备注文字]`", parse_mode="Markdown")
            return

        public_id = args[0].strip().lower()
        remark = " ".join(args[1:]).strip()

        try:
            signal_record_service = self._signal_record_service()
            record = await self.signal_record_repo.get_by_public_id(public_id)
            if not record:
                await update.message.reply_text("❌ 找不到这笔交易信号")
                return

            if not signal_record_service.can_update_signal_record(user, record):
                await update.message.reply_text("❌ 只有原发单者或管理员可以更新这笔交易信号")
                return

            if record["status"] != "sent":
                await update.message.reply_text("❌ 这笔交易信号尚未成功转发，无法更新图表")
                return

            target_messages = await self.signal_record_repo.get_channel_messages(record["id"])
            if not target_messages:
                await update.message.reply_text("❌ 找不到这笔交易信号的原始转发消息")
                return

            if not Config.SIGNAL_CHART_ENABLED:
                await update.message.reply_text("❌ 图表功能目前已停用")
                return

            signal = signal_record_service.signal_record_to_draft(record)
            try:
                chart_bytes = await asyncio.wait_for(
                    self._create_signal_update_chart(signal, record["created_at"], record["granularity"]),
                    timeout=Config.SIGNAL_CHART_TIMEOUT_SECONDS,
                )
            except ValueError:
                await update.message.reply_text("❌ K 线资料不足，无法生成这笔交易的更新图表")
                return

            update_text = chart_update_message(record["public_id"], remark)
            await self._mark_replaced_active_signal_preview(user.telegram_id)
            token = secrets.token_urlsafe(8)
            self.set_user_session(
                user.telegram_id,
                {
                    "step": CHART_UPDATE_PREVIEW_STEP,
                    "token": token,
                    "signal_record_id": record["id"],
                    "signal_public_id": record["public_id"],
                    "chart_bytes": chart_bytes,
                    "update_text": update_text,
                    "target_messages": target_messages,
                },
            )

            await self._send_chart_update_preview(
                update,
                update_text,
                chart_bytes,
                chart_update_preview_keyboard(token),
            )
            await emit_audit_event(
                self,
                user,
                "chart_update_preview_created",
                {
                    "status": "pending",
                    "signal_id": record["public_id"],
                    "target_count": len(target_messages),
                },
            )
        except Exception as e:
            logger.error("Update chart error: %s", e)
            await emit_audit_event(
                self,
                user,
                "chart_update_failed",
                {"status": "failed", "signal_id": public_id, "reason": type(e).__name__},
            )
            await update.message.reply_text("❌ 更新图表时发生错误")

    async def _create_signal_update_chart(self, signal: SignalDraft, signal_time: datetime, granularity: str) -> bytes:
        candles = await self.trade_manager.get_candles(
            signal.symbol,
            granularity,
            Config.SIGNAL_UPDATE_CANDLE_LIMIT,
            end_time=datetime.now(timezone.utc),
        )
        return await asyncio.to_thread(render_signal_update_chart, signal, candles, granularity, signal_time)

    async def _send_chart_update_preview(self, update: Update, update_text: str, chart_bytes: bytes, reply_markup):
        preview_text = f"{CHART_UPDATE_PREVIEW_PROMPT}\n\n{update_text}"
        await update.message.reply_photo(
            photo=BytesIO(chart_bytes),
            caption=SignalDeliveryService.fit_photo_caption(preview_text),
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    async def _handle_place_order_callback(self, query, user, data):
        """Handle market or limit order button."""
        return await self._order_flow_service().handle_place_order_callback(query, user, data)

    async def _create_signal_chart(self, signal: SignalDraft) -> bytes:
        candles = await self.trade_manager.get_candles(
            signal.symbol,
            Config.SIGNAL_CHART_GRANULARITY,
            Config.SIGNAL_CHART_CANDLE_LIMIT,
        )
        return await asyncio.to_thread(render_signal_chart, signal, candles, Config.SIGNAL_CHART_GRANULARITY)

    async def _try_create_signal_chart(self, signal: SignalDraft) -> tuple[bytes | None, str, str | None]:
        if not Config.SIGNAL_CHART_ENABLED:
            return None, "disabled", None

        try:
            chart_bytes = await asyncio.wait_for(
                self._create_signal_chart(signal),
                timeout=Config.SIGNAL_CHART_TIMEOUT_SECONDS,
            )
            return chart_bytes, "generated", None
        except Exception as e:
            logger.warning("Failed to generate signal chart for %s: %s", signal.symbol, e)
            return None, "failed", type(e).__name__

    async def _send_signal_preview(
        self, update: Update, signal: SignalDraft, signal_text: str, chart_bytes, reply_markup
    ):
        preview_text = f"{SIGNAL_PREVIEW_PROMPT}\n\n{signal_text}"
        if not chart_bytes:
            await update.message.reply_text(preview_text, reply_markup=reply_markup, parse_mode="Markdown")
            return

        if len(preview_text) <= TELEGRAM_PHOTO_CAPTION_LIMIT:
            await update.message.reply_photo(
                photo=BytesIO(chart_bytes),
                caption=preview_text,
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return

        await update.message.reply_photo(
            photo=BytesIO(chart_bytes),
            caption=SIGNAL_PREVIEW_PROMPT,
            parse_mode="Markdown",
        )
        await update.message.reply_text(signal_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_confirm_signal_callback(self, query, user, data):
        token = data.removeprefix("confirm_signal_")
        session = await self._get_signal_preview_session_or_reply(query, user, token)
        if not session:
            return

        result = await self._signal_delivery_service().forward_signal_to_channels(
            self.application.bot,
            session["signal"],
            session["signal_text"],
            session.get("chart_bytes"),
            session.get("chart_status", "disabled"),
            session.get("chart_error"),
            session.get("signal_record_id"),
            signal_public_id=session.get("signal_public_id"),
        )
        if session.get("signal_record_id"):
            await self._signal_record_service().update_send_status(session["signal_record_id"], result["sent_count"])
        self.user_sessions.pop(user.telegram_id, None)
        await self._edit_signal_preview_message(
            query,
            f"✅ 交易信号已转发\n\n📺 发送到频道：{result['sent_count']} 个",
            parse_mode="Markdown",
        )
        await emit_audit_event(
            self,
            user,
            "signal_sent",
            {
                "status": result["status"],
                "symbol": session["signal"].symbol,
                "direction": session["signal"].direction,
                "entry_lower": session["signal"].entry_lower,
                "entry_upper": session["signal"].entry_upper,
                "stop_loss": session["signal"].stop_loss,
                "take_profit_levels": session["signal"].take_profit_levels,
                "remark": session["signal"].remark,
                "signal_id": session.get("signal_public_id"),
                "target_count": result["target_count"],
                "sent_count": result["sent_count"],
                "failed_count": result["failed_count"],
                "chart_status": result["chart_status"],
                "chart_error": result["chart_error"],
                "chart_send_fallback_count": result["chart_send_fallback_count"],
                "reason": result["reason"],
            },
        )

    async def _handle_cancel_signal_callback(self, query, user, data):
        token = data.removeprefix("cancel_signal_")
        session = await self._get_signal_preview_session_or_reply(query, user, token)
        if not session:
            return

        self.user_sessions.pop(user.telegram_id, None)
        if session.get("signal_record_id"):
            await self._signal_record_service().update_status(session["signal_record_id"], "cancelled")
        await self._edit_signal_preview_message(query, "✅ 已取消转发")
        await emit_audit_event(
            self,
            user,
            "signal_preview_cancelled",
            {
                "status": "cancelled",
                "symbol": session["signal"].symbol,
                "direction": session["signal"].direction,
            },
        )

    async def _handle_confirm_chart_update_callback(self, query, user, data):
        token = data.removeprefix("confirm_chart_update_")
        session = await self._get_chart_update_preview_session_or_reply(query, user, token)
        if not session:
            return

        result = await self._signal_delivery_service().forward_chart_update_to_original_targets(
            self.application.bot,
            session["chart_bytes"],
            session["update_text"],
            session["target_messages"],
        )
        self.user_sessions.pop(user.telegram_id, None)
        await self._edit_signal_preview_message(
            query,
            f"✅ 图表更新已转发\n\n📺 发送到频道：{result['sent_count']} 个",
            parse_mode="Markdown",
        )
        await emit_audit_event(
            self,
            user,
            "chart_update_sent",
            {
                "status": result["status"],
                "signal_id": session.get("signal_public_id"),
                "target_count": result["target_count"],
                "sent_count": result["sent_count"],
                "failed_count": result["failed_count"],
                "reply_fallback_count": result["reply_fallback_count"],
            },
        )

    async def _handle_cancel_chart_update_callback(self, query, user, data):
        token = data.removeprefix("cancel_chart_update_")
        session = await self._get_chart_update_preview_session_or_reply(query, user, token)
        if not session:
            return

        self.user_sessions.pop(user.telegram_id, None)
        await self._edit_signal_preview_message(query, "✅ 已取消转发")
        await emit_audit_event(
            self,
            user,
            "chart_update_preview_cancelled",
            {
                "status": "cancelled",
                "signal_id": session.get("signal_public_id"),
            },
        )

    async def _get_signal_preview_session_or_reply(self, query, user, token: str) -> dict | None:
        session = await self._get_active_preview_session(user.telegram_id)
        if not session or session.get("step") != SIGNAL_PREVIEW_STEP or session.get("token") != token:
            await self._edit_signal_preview_message(query, SIGNAL_PREVIEW_EXPIRED_MESSAGE)
            await emit_audit_event(
                self,
                user,
                "signal_preview_expired",
                {"status": "missing_or_expired"},
            )
            return None

        return session

    async def _get_chart_update_preview_session_or_reply(self, query, user, token: str) -> dict | None:
        session = await self._get_active_preview_session(user.telegram_id)
        if not session or session.get("step") != CHART_UPDATE_PREVIEW_STEP or session.get("token") != token:
            await self._edit_signal_preview_message(query, CHART_UPDATE_PREVIEW_EXPIRED_MESSAGE)
            await emit_audit_event(
                self,
                user,
                "chart_update_preview_expired",
                {"status": "missing_or_expired"},
            )
            return None

        return session

    async def _edit_signal_preview_message(self, query, text: str, **kwargs):
        try:
            await query.edit_message_caption(caption=text, reply_markup=None, **kwargs)
        except Exception:
            await query.edit_message_text(text, reply_markup=None, **kwargs)

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
