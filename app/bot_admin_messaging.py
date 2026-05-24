import logging

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .audit import emit_audit_event, summarize_message_text
from .telegram_formatting import HTML_PARSE_MODE, html_code, html_escape

logger = logging.getLogger(__name__)


class AdminMessaging:
    """Standalone use-case coordinator for admin messaging."""

    def __init__(self, bot):
        self.bot = bot

    async def admin_broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Broadcast a message to managed channels."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        message_text = " ".join(context.args)
        if not message_text:
            await update.message.reply_text(
                "📢 <b>广播消息</b>\n\n"
                f"使用方法：{html_code('/admin_broadcast 您的消息内容')}\n\n"
                f"例如：{html_code('/admin_broadcast 系统将于今晚进行维护')}",
                parse_mode=HTML_PARSE_MODE,
            )
            return

        try:
            channels = await self.bot.channel_repo.get_active_channels()
            sent_to_channels = 0
            failed_channels = 0
            status_msg = await update.message.reply_text(f"📤 开始广播给 {len(channels)} 个频道/群组...")

            sender_username = self.bot._get_sender_username(update)

            for channel in channels:
                try:
                    send_kwargs = {
                        "chat_id": channel["chat_id"],
                        "text": f"📢 <b>管理员广播</b> by @{html_escape(sender_username)}\n\n{html_escape(message_text)}",
                        "parse_mode": HTML_PARSE_MODE,
                    }
                    if channel.get("message_thread_id"):
                        send_kwargs["message_thread_id"] = channel["message_thread_id"]
                    await context.bot.send_message(**send_kwargs)
                    sent_to_channels += 1
                except TelegramError as e:
                    logger.warning(
                        f"Failed to send broadcast to channel {channel['chat_id']} "
                        f"thread {channel.get('message_thread_id')}: {e}"
                    )
                    failed_channels += 1

            await status_msg.edit_text(
                f"✅ <b>广播完成</b>\n\n成功发送：{sent_to_channels} 个频道/群组\n发送失败：{failed_channels} 个频道/群组",
                parse_mode=HTML_PARSE_MODE,
            )
            await emit_audit_event(
                self.bot,
                user,
                "admin_broadcast",
                {
                    "status": "completed",
                    "target_count": len(channels),
                    "sent_count": sent_to_channels,
                    "failed_count": failed_channels,
                    "message": summarize_message_text(message_text),
                },
            )

        except (SQLAlchemyError, TelegramError) as e:
            logger.error(f"Broadcast error: {e}")
            await emit_audit_event(
                self.bot,
                user,
                "admin_broadcast",
                {
                    "status": "failed",
                    "reason": type(e).__name__,
                    "message": summarize_message_text(message_text),
                },
            )
            await update.message.reply_text("❌ 广播时发生错误")

    async def send_to_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message to a specific channel."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "📤 <b>发送到频道</b>\n\n"
                "使用方法：\n"
                f"{html_code('/send_to_channel @channel_username 消息内容')}\n"
                f"{html_code('/send_to_channel -1001234567890 消息内容')}\n\n"
                "例如：\n"
                f"{html_code('/send_to_channel @my_signals 今日重要公告')}",
                parse_mode=HTML_PARSE_MODE,
            )
            return

        chat_identifier = args[0]
        message_text = " ".join(args[1:])

        try:
            sent_message = await context.bot.send_message(
                chat_id=chat_identifier, text=html_escape(message_text), parse_mode=HTML_PARSE_MODE
            )

            await emit_audit_event(
                self.bot,
                user,
                "admin_send_to_channel",
                {
                    "status": "sent",
                    "chat_identifier": chat_identifier,
                    "telegram_message_id": sent_message.message_id,
                    "message": summarize_message_text(message_text),
                },
            )
            await update.message.reply_text(
                f"✅ <b>消息已发送</b>\n\n目标频道：{html_escape(chat_identifier)}\n消息 ID：{html_escape(sent_message.message_id)}",
                parse_mode=HTML_PARSE_MODE,
            )

        except (SQLAlchemyError, TelegramError) as e:
            logger.error(f"Send to channel error: {e}")
            await emit_audit_event(
                self.bot,
                user,
                "admin_send_to_channel",
                {
                    "status": "failed",
                    "reason": type(e).__name__,
                    "chat_identifier": chat_identifier,
                    "message": summarize_message_text(message_text),
                },
            )
            await update.message.reply_text(f"❌ 发送失败\n\n错误：{str(e)}")


class AdminMessagingMixin:
    @property
    def admin_messaging(self) -> AdminMessaging:
        if not hasattr(self, "_admin_messaging_delegate"):
            self._admin_messaging_delegate = AdminMessaging(self)
        return self._admin_messaging_delegate

    async def admin_broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_messaging.admin_broadcast_command(update, context)

    async def send_to_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_messaging.send_to_channel_command(update, context)
