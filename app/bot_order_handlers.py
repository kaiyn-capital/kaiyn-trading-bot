import asyncio
import logging
import secrets
from datetime import UTC, datetime
from io import BytesIO

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .audit import emit_audit_event
from .bitget_errors import BitgetAPIError
from .bot_keyboards import chart_update_preview_keyboard, signal_preview_keyboard
from .bot_messages import (
    chart_update_message,
    signal_usage_message,
)
from .order_flow import parse_signal_args
from .order_interaction_service import ConfirmedOrderRequest, TelegramOrderFlowService
from .order_types import SignalDraft
from .session_types import ChartUpdatePreviewSession, SignalPreviewSession
from .signal_charts import render_signal_chart, render_signal_update_chart
from .signal_delivery_service import TELEGRAM_PHOTO_CAPTION_LIMIT, SignalDeliveryService
from .signal_record_service import SignalRecordService
from .telegram_formatting import HTML_PARSE_MODE, html_code

logger = logging.getLogger(__name__)

SIGNAL_PREVIEW_EXPIRED_MESSAGE = "⏳ 预览已过期或已被新的信号取代，请重新发送 /send_signal"
SIGNAL_PREVIEW_PROMPT = "📋 <b>请确认是否转发以下交易信号</b>"
CHART_UPDATE_PREVIEW_EXPIRED_MESSAGE = "⏳ 预览已过期或已被新的更新取代，请重新发送 /update_chart"
CHART_UPDATE_PREVIEW_PROMPT = "📋 <b>请确认是否转发以下图表更新</b>"


class OrderHandlers:
    """Standalone use-case coordinator for order flow and signals."""

    def __init__(self, bot):
        self.bot = bot

    def _order_flow_service(self) -> TelegramOrderFlowService:
        return TelegramOrderFlowService(
            bot=self.bot.application.bot,
            user_repo=self.bot.user_repo,
            pending_order_repo=self.bot.pending_order_repo,
            trade_repo=self.bot.trade_repo,
            trade_manager=self.bot.trade_manager,
            system_log_repo=self.bot.system_log_repo,
            audit_owner=self.bot,
            failure_alert_handler=self.bot._record_bitget_failure_alert,
            signal_record_repo=self.bot.signal_record_repo,
            settings=self.bot.settings,
        )

    def _signal_record_service(self) -> SignalRecordService:
        return SignalRecordService(
            self.bot.signal_record_repo,
            is_admin_checker=self.bot.settings.is_admin,
            signal_chart_granularity=self.bot.settings.signal_chart_granularity,
        )

    def _signal_delivery_service(self) -> SignalDeliveryService:
        return SignalDeliveryService(self.bot.channel_repo, self.bot.signal_record_repo)

    async def _mark_replaced_active_signal_preview(self, telegram_id: int) -> None:
        session = await self._get_active_preview_session(telegram_id)
        if not isinstance(session, SignalPreviewSession):
            return

        await self.bot._signal_record_service().update_status(session.signal_record_id, "replaced")

    async def _get_active_preview_session(
        self, telegram_id: int
    ) -> SignalPreviewSession | ChartUpdatePreviewSession | None:
        expired_session = await self.bot.pop_expired_user_session(telegram_id)
        if expired_session:
            if isinstance(expired_session, SignalPreviewSession):
                await self.bot._signal_record_service().update_status(expired_session.signal_record_id, "expired")
            return None

        session = await self.bot.peek_user_session(telegram_id)
        if isinstance(session, (SignalPreviewSession, ChartUpdatePreviewSession)):
            return session
        return None

    async def trader_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show trader panel with signal command templates."""
        user = await self.bot._require_trader(update)
        if user is None:
            return

        panel_text = (
            "👨‍💼 <b>交易员面板</b>\n\n"
            "💡 <b>一键复制指令模板</b>\n"
            "点击以下代码块即可复制到输入框进行修改：\n\n"
            "<b>1. 发送新信号</b>\n"
            f"{html_code('/send_signal 交易对 方向 entry[进场] sl[止损] tp[止盈1 止盈2] [备注]')}\n\n"
            "<i>空白模板：</i>\n"
            f"{html_code('/send_signal USDT long entry[] sl[] tp[]')}\n"
            f"{html_code('/send_signal USDT short entry[] sl[] tp[]')}\n\n"
            "<i>完整範例：</i>\n"
            f"{html_code('/send_signal BTCUSDT long entry[65000] sl[64000] tp[66000 68000]')}\n\n"
            "<b>2. 更新已有信号图表</b>\n"
            f"{html_code('/update_chart 交易id [备注文字]')}\n\n"
            "<i>空白模板：</i>\n"
            f"{html_code('/update_chart ')}\n\n"
            "<i>完整範例：</i>\n"
            f"{html_code('/update_chart 7cg8h2k 达到第一止盈位，保护性止损已上移')}"
        )
        await update.message.reply_text(panel_text, parse_mode=HTML_PARSE_MODE)

    async def send_signal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a trading signal to configured channels."""
        user = await self.bot._get_or_create_user(update)

        if not await self.bot._is_trader_or_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有发送交易信号的权限")
            return

        args = context.args
        if len(args) < 3:
            await update.message.reply_text(signal_usage_message(), parse_mode=HTML_PARSE_MODE)
            return

        try:
            signal = parse_signal_args(args)

            if signal.direction not in ["long", "short"]:
                await update.message.reply_text("❌ 交易方向必须是 long 或 short")
                return

            await self._mark_replaced_active_signal_preview(user.telegram_id)
            sender_username = self.bot._get_sender_username(update)
            chart_bytes, chart_status, chart_error = await self._try_create_signal_chart(signal)
            signal_record, signal_text = await self.bot._signal_record_service().create_signal_record(
                user=user,
                signal=signal,
                sender_username=sender_username,
                chart_status=chart_status,
                chart_error=chart_error,
            )
            token = secrets.token_urlsafe(8)
            await self.bot.set_user_session(
                user.telegram_id,
                SignalPreviewSession(
                    token=token,
                    signal_record_id=signal_record.id,
                    signal_public_id=signal_record.public_id,
                    chart_bytes=chart_bytes,
                    chart_status=chart_status,
                    chart_error=chart_error,
                ),
                user_id=getattr(user, "id", None),
            )

            await self._send_signal_preview(update, signal, signal_text, chart_bytes, signal_preview_keyboard(token))
            await emit_audit_event(
                self.bot,
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
                    "signal_id": signal_record.public_id,
                    "chart_status": chart_status,
                    "chart_error": chart_error,
                },
            )

        except ValueError:
            await update.message.reply_text("❌ 格式错误，请使用 entry[] sl[] tp[]，并输入有效数字")
        except (RuntimeError, SQLAlchemyError, TelegramError, TypeError) as e:
            logger.error(f"Send signal error: {e}")
            await emit_audit_event(
                self.bot,
                user,
                "signal_sent",
                {"status": "failed", "reason": type(e).__name__},
            )
            await update.message.reply_text("❌ 发送信号时发生错误", parse_mode=HTML_PARSE_MODE)

    async def update_chart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create a confirmed chart update for an existing signal."""
        user = await self.bot._get_or_create_user(update)
        args = context.args
        if not args:
            await update.message.reply_text(
                f"使用方法：{html_code('/update_chart 交易id [备注文字]')}",
                parse_mode=HTML_PARSE_MODE,
            )
            return

        public_id = args[0].strip().lower()
        remark = " ".join(args[1:]).strip()

        try:
            signal_record_service = self.bot._signal_record_service()
            record = await self.bot.signal_record_repo.get_by_public_id(public_id)
            if not record:
                await update.message.reply_text("❌ 找不到这笔交易信号")
                return

            if not signal_record_service.can_update_signal_record(user, record):
                await update.message.reply_text("❌ 只有原发单者或管理员可以更新这笔交易信号")
                return

            if record.status != "sent":
                await update.message.reply_text("❌ 这笔交易信号尚未成功转发，无法更新图表")
                return

            target_messages = await self.bot.signal_record_repo.get_channel_messages(record.id)
            if not target_messages:
                await update.message.reply_text("❌ 找不到这笔交易信号的原始转发消息")
                return

            if not self.bot.settings.signal_chart_enabled:
                await update.message.reply_text("❌ 图表功能目前已停用")
                return

            signal = signal_record_service.signal_record_to_draft(record)
            try:
                chart_bytes = await asyncio.wait_for(
                    self.bot._create_signal_update_chart(signal, record.created_at, record.granularity),
                    timeout=self.bot.settings.signal_chart_timeout_seconds,
                )
            except ValueError:
                await update.message.reply_text("❌ K 线资料不足，无法生成这笔交易的更新图表")
                return

            update_text = chart_update_message(record.public_id, remark)
            await self._mark_replaced_active_signal_preview(user.telegram_id)
            token = secrets.token_urlsafe(8)
            await self.bot.set_user_session(
                user.telegram_id,
                ChartUpdatePreviewSession(
                    token=token,
                    signal_record_id=record.id,
                    signal_public_id=record.public_id,
                    update_text=update_text,
                    chart_bytes=chart_bytes,
                ),
                user_id=getattr(user, "id", None),
            )

            await self._send_chart_update_preview(
                update,
                update_text,
                chart_bytes,
                chart_update_preview_keyboard(token),
            )
            await emit_audit_event(
                self.bot,
                user,
                "chart_update_preview_created",
                {
                    "status": "pending",
                    "signal_id": record.public_id,
                    "target_count": len(target_messages),
                },
            )
        except (RuntimeError, SQLAlchemyError, TelegramError, TypeError, ValueError) as e:
            logger.error("Update chart error: %s", e)
            await emit_audit_event(
                self.bot,
                user,
                "chart_update_failed",
                {"status": "failed", "signal_id": public_id, "reason": type(e).__name__},
            )
            await update.message.reply_text("❌ 更新图表时发生错误")

    async def _create_signal_update_chart(self, signal: SignalDraft, signal_time: datetime, granularity: str) -> bytes:
        candles = await self.bot.trade_manager.get_candles(
            signal.symbol,
            granularity,
            self.bot.settings.signal_update_candle_limit,
            end_time=datetime.now(UTC),
        )
        return await asyncio.to_thread(render_signal_update_chart, signal, candles, granularity, signal_time)

    async def _send_chart_update_preview(self, update: Update, update_text: str, chart_bytes: bytes, reply_markup):
        preview_text = f"{CHART_UPDATE_PREVIEW_PROMPT}\n\n{update_text}"
        await update.message.reply_photo(
            photo=BytesIO(chart_bytes),
            caption=SignalDeliveryService.fit_photo_caption(preview_text),
            reply_markup=reply_markup,
            parse_mode=HTML_PARSE_MODE,
        )

    async def _handle_place_order_callback(self, query, user, data):
        """Handle market or limit order button."""
        return await self.bot._order_flow_service().handle_place_order_callback(query, user, data)

    async def _create_signal_chart(self, signal: SignalDraft) -> bytes:
        candles = await self.bot.trade_manager.get_candles(
            signal.symbol,
            self.bot.settings.signal_chart_granularity,
            self.bot.settings.signal_chart_candle_limit,
        )
        return await asyncio.to_thread(render_signal_chart, signal, candles, self.bot.settings.signal_chart_granularity)

    async def _try_create_signal_chart(self, signal: SignalDraft) -> tuple[bytes | None, str, str | None]:
        if not self.bot.settings.signal_chart_enabled:
            return None, "disabled", None

        try:
            chart_bytes = await asyncio.wait_for(
                self.bot._create_signal_chart(signal),
                timeout=self.bot.settings.signal_chart_timeout_seconds,
            )
            return chart_bytes, "generated", None
        except (TimeoutError, BitgetAPIError, RuntimeError, ValueError) as e:
            logger.warning("Failed to generate signal chart for %s: %s", signal.symbol, e)
            return None, "failed", type(e).__name__

    async def _send_signal_preview(
        self, update: Update, signal: SignalDraft, signal_text: str, chart_bytes, reply_markup
    ):
        preview_text = f"{SIGNAL_PREVIEW_PROMPT}\n\n{signal_text}"
        if not chart_bytes:
            await update.message.reply_text(preview_text, reply_markup=reply_markup, parse_mode=HTML_PARSE_MODE)
            return

        if len(preview_text) <= TELEGRAM_PHOTO_CAPTION_LIMIT:
            await update.message.reply_photo(
                photo=BytesIO(chart_bytes),
                caption=preview_text,
                reply_markup=reply_markup,
                parse_mode=HTML_PARSE_MODE,
            )
            return

        await update.message.reply_photo(
            photo=BytesIO(chart_bytes),
            caption=SIGNAL_PREVIEW_PROMPT,
            parse_mode=HTML_PARSE_MODE,
        )
        await update.message.reply_text(signal_text, reply_markup=reply_markup, parse_mode=HTML_PARSE_MODE)

    async def _handle_confirm_signal_callback(self, query, user, data):
        token = data.removeprefix("confirm_signal_")
        session = await self._get_signal_preview_session_or_reply(query, user, token)
        if not session:
            return

        record = await self.bot.signal_record_repo.get_by_id(session.signal_record_id)
        if not record:
            await self.bot.delete_user_session(user.telegram_id)
            await self._edit_signal_preview_message(query, SIGNAL_PREVIEW_EXPIRED_MESSAGE)
            return

        signal_record_service = self.bot._signal_record_service()
        signal = signal_record_service.signal_record_to_draft(record)
        result = await self.bot._signal_delivery_service().forward_signal_to_channels(
            self.bot.application.bot,
            signal,
            record.signal_text,
            session.chart_bytes,
            session.chart_status,
            session.chart_error,
            session.signal_record_id,
            signal_public_id=session.signal_public_id,
        )
        await signal_record_service.update_send_status(session.signal_record_id, result["sent_count"])
        await self.bot.delete_user_session(user.telegram_id)
        await self._edit_signal_preview_message(
            query,
            f"✅ <b>交易信号已转发</b>\n交易id: <code>{session.signal_public_id}</code>\n\n📺 发送到频道：{result['sent_count']} 个",
            parse_mode=HTML_PARSE_MODE,
        )
        await emit_audit_event(
            self.bot,
            user,
            "signal_sent",
            {
                "status": result["status"],
                "symbol": signal.symbol,
                "direction": signal.direction,
                "entry_lower": signal.entry_lower,
                "entry_upper": signal.entry_upper,
                "stop_loss": signal.stop_loss,
                "take_profit_levels": signal.take_profit_levels,
                "remark": signal.remark,
                "signal_id": session.signal_public_id,
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

        record = await self.bot.signal_record_repo.get_by_id(session.signal_record_id)
        signal = self.bot._signal_record_service().signal_record_to_draft(record) if record else None
        await self.bot.delete_user_session(user.telegram_id)
        await self.bot._signal_record_service().update_status(session.signal_record_id, "cancelled")
        await self._edit_signal_preview_message(query, "✅ 已取消转发")
        await emit_audit_event(
            self.bot,
            user,
            "signal_preview_cancelled",
            {
                "status": "cancelled",
                "symbol": signal.symbol if signal else None,
                "direction": signal.direction if signal else None,
            },
        )

    async def _handle_confirm_chart_update_callback(self, query, user, data):
        token = data.removeprefix("confirm_chart_update_")
        session = await self._get_chart_update_preview_session_or_reply(query, user, token)
        if not session:
            return

        target_messages = await self.bot.signal_record_repo.get_channel_messages(session.signal_record_id)
        if not target_messages:
            await self.bot.delete_user_session(user.telegram_id)
            await self._edit_signal_preview_message(query, CHART_UPDATE_PREVIEW_EXPIRED_MESSAGE)
            return

        result = await self.bot._signal_delivery_service().forward_chart_update_to_original_targets(
            self.bot.application.bot,
            session.chart_bytes,
            session.update_text,
            target_messages,
        )
        await self.bot.delete_user_session(user.telegram_id)
        await self._edit_signal_preview_message(
            query,
            f"✅ <b>图表更新已转发</b>\n\n📺 发送到频道：{result['sent_count']} 个",
            parse_mode=HTML_PARSE_MODE,
        )
        await emit_audit_event(
            self.bot,
            user,
            "chart_update_sent",
            {
                "status": result["status"],
                "signal_id": session.signal_public_id,
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

        await self.bot.delete_user_session(user.telegram_id)
        await self._edit_signal_preview_message(query, "✅ 已取消转发")
        await emit_audit_event(
            self.bot,
            user,
            "chart_update_preview_cancelled",
            {
                "status": "cancelled",
                "signal_id": session.signal_public_id,
            },
        )

    async def _get_signal_preview_session_or_reply(self, query, user, token: str) -> SignalPreviewSession | None:
        session = await self._get_active_preview_session(user.telegram_id)
        if not isinstance(session, SignalPreviewSession) or session.token != token:
            await self._edit_signal_preview_message(query, SIGNAL_PREVIEW_EXPIRED_MESSAGE)
            await emit_audit_event(
                self.bot,
                user,
                "signal_preview_expired",
                {"status": "missing_or_expired"},
            )
            return None

        return session

    async def _get_chart_update_preview_session_or_reply(
        self,
        query,
        user,
        token: str,
    ) -> ChartUpdatePreviewSession | None:
        session = await self._get_active_preview_session(user.telegram_id)
        if not isinstance(session, ChartUpdatePreviewSession) or session.token != token:
            await self._edit_signal_preview_message(query, CHART_UPDATE_PREVIEW_EXPIRED_MESSAGE)
            await emit_audit_event(
                self.bot,
                user,
                "chart_update_preview_expired",
                {"status": "missing_or_expired"},
            )
            return None

        return session

    async def _edit_signal_preview_message(self, query, text: str, **kwargs):
        try:
            await query.edit_message_caption(caption=text, reply_markup=None, **kwargs)
        except TelegramError:
            await query.edit_message_text(text, reply_markup=None, **kwargs)

    async def _send_private_message(self, query, user, text, reply_markup=None):
        """Send a private Telegram message to the user."""
        return await self.bot._order_flow_service().send_private_message(query, user, text, reply_markup)

    async def _handle_confirm_pending_order_callback(self, query, user, data):
        """Handle pending order confirmation."""
        return await self.bot._order_flow_service().handle_confirm_pending_order_callback(query, user, data)

    async def _handle_cancel_pending_order_callback(self, query, user, data):
        """Handle pending order cancellation."""
        return await self.bot._order_flow_service().handle_cancel_pending_order_callback(query, user, data)

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
        return await self.bot._order_flow_service().execute_order(
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


class OrderHandlersMixin:
    @property
    def order_handlers(self) -> OrderHandlers:
        if not hasattr(self, "_order_handlers_delegate"):
            self._order_handlers_delegate = OrderHandlers(self)
        return self._order_handlers_delegate

    @order_handlers.setter
    def order_handlers(self, value: OrderHandlers):
        self._order_handlers_delegate = value

    async def _record_bitget_failure_alert(self, classified_error, source: str, details: dict | None = None):
        return None

    def _order_flow_service(self) -> TelegramOrderFlowService:
        return self.order_handlers._order_flow_service()

    def _signal_record_service(self) -> SignalRecordService:
        return self.order_handlers._signal_record_service()

    def _signal_delivery_service(self) -> SignalDeliveryService:
        return self.order_handlers._signal_delivery_service()

    async def _mark_replaced_active_signal_preview(self, telegram_id: int) -> None:
        await self.order_handlers._mark_replaced_active_signal_preview(telegram_id)

    async def _get_active_preview_session(
        self, telegram_id: int
    ) -> SignalPreviewSession | ChartUpdatePreviewSession | None:
        return await self.order_handlers._get_active_preview_session(telegram_id)

    async def trader_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.order_handlers.trader_command(update, context)

    async def send_signal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.order_handlers.send_signal_command(update, context)

    async def update_chart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.order_handlers.update_chart_command(update, context)

    async def _create_signal_update_chart(self, signal: SignalDraft, signal_time: datetime, granularity: str) -> bytes:
        return await self.order_handlers._create_signal_update_chart(signal, signal_time, granularity)

    async def _send_chart_update_preview(self, update: Update, update_text: str, chart_bytes: bytes, reply_markup):
        await self.order_handlers._send_chart_update_preview(update, update_text, chart_bytes, reply_markup)

    async def _handle_place_order_callback(self, query, user, data):
        return await self.order_handlers._handle_place_order_callback(query, user, data)

    async def _create_signal_chart(self, signal: SignalDraft) -> bytes:
        return await self.order_handlers._create_signal_chart(signal)

    async def _try_create_signal_chart(self, signal: SignalDraft) -> tuple[bytes | None, str, str | None]:
        return await self.order_handlers._try_create_signal_chart(signal)

    async def _send_signal_preview(
        self, update: Update, signal: SignalDraft, signal_text: str, chart_bytes, reply_markup
    ):
        await self.order_handlers._send_signal_preview(update, signal, signal_text, chart_bytes, reply_markup)

    async def _handle_confirm_signal_callback(self, query, user, data):
        await self.order_handlers._handle_confirm_signal_callback(query, user, data)

    async def _handle_cancel_signal_callback(self, query, user, data):
        await self.order_handlers._handle_cancel_signal_callback(query, user, data)

    async def _handle_confirm_chart_update_callback(self, query, user, data):
        await self.order_handlers._handle_confirm_chart_update_callback(query, user, data)

    async def _handle_cancel_chart_update_callback(self, query, user, data):
        await self.order_handlers._handle_cancel_chart_update_callback(query, user, data)

    async def _get_signal_preview_session_or_reply(self, query, user, token: str) -> SignalPreviewSession | None:
        return await self.order_handlers._get_signal_preview_session_or_reply(query, user, token)

    async def _get_chart_update_preview_session_or_reply(
        self, query, user, token: str
    ) -> ChartUpdatePreviewSession | None:
        return await self.order_handlers._get_chart_update_preview_session_or_reply(query, user, token)

    async def _edit_signal_preview_message(self, query, text: str, **kwargs):
        await self.order_handlers._edit_signal_preview_message(query, text, **kwargs)

    async def _send_private_message(self, query, user, text, reply_markup=None):
        return await self.order_handlers._send_private_message(query, user, text, reply_markup)

    async def _handle_confirm_pending_order_callback(self, query, user, data):
        return await self.order_handlers._handle_confirm_pending_order_callback(query, user, data)

    async def _handle_cancel_pending_order_callback(self, query, user, data):
        return await self.order_handlers._handle_cancel_pending_order_callback(query, user, data)

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
        return await self.order_handlers._execute_order(
            query,
            user,
            symbol,
            direction,
            quantity,
            stop_loss,
            position_value,
            current_price,
            order_mode,
            limit_price,
            pending_order_token,
        )
