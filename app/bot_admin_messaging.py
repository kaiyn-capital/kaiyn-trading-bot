import logging

from telegram import Update
from telegram.ext import ContextTypes

from .audit import emit_audit_event, summarize_message_text
from .config import Config

logger = logging.getLogger(__name__)


class AdminMessagingMixin:
    async def admin_broadcast_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Broadcast a message to managed channels."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        message_text = " ".join(context.args)
        if not message_text:
            await update.message.reply_text(
                "📢 **广播消息**\n\n"
                "使用方法：`/admin_broadcast 您的消息内容`\n\n"
                "例如：`/admin_broadcast 系统将于今晚进行维护`",
                parse_mode="Markdown",
            )
            return

        try:
            channels = await self.channel_repo.get_active_channels()
            sent_to_channels = 0
            failed_channels = 0
            status_msg = await update.message.reply_text(
                f"📤 开始广播给 {len(channels)} 个频道/群组..."
            )

            sender_username = self._get_sender_username(update)

            for channel in channels:
                try:
                    await context.bot.send_message(
                        chat_id=channel["chat_id"],
                        text=f"📢 **管理员广播** by @{sender_username}\n\n{message_text}",
                        parse_mode="Markdown",
                    )
                    sent_to_channels += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to send broadcast to channel {channel['chat_id']}: {e}"
                    )
                    failed_channels += 1

            await status_msg.edit_text(
                f"✅ **广播完成**\n\n"
                f"成功发送：{sent_to_channels} 个频道/群组\n"
                f"发送失败：{failed_channels} 个频道/群组",
                parse_mode="Markdown",
            )
            await emit_audit_event(
                self,
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

        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            await emit_audit_event(
                self,
                user,
                "admin_broadcast",
                {
                    "status": "failed",
                    "reason": type(e).__name__,
                    "message": summarize_message_text(message_text),
                },
            )
            await update.message.reply_text("❌ 广播时发生错误")

    async def send_to_channel_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Send a message to a specific channel."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "📤 **发送到频道**\n\n"
                "使用方法：\n"
                "`/send_to_channel @channel_username 消息内容`\n"
                "`/send_to_channel -1001234567890 消息内容`\n\n"
                "例如：\n"
                "`/send_to_channel @my_signals 今日重要公告`",
                parse_mode="Markdown",
            )
            return

        chat_identifier = args[0]
        message_text = " ".join(args[1:])

        try:
            sent_message = await context.bot.send_message(
                chat_id=chat_identifier, text=message_text, parse_mode="Markdown"
            )

            await emit_audit_event(
                self,
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
                f"✅ **消息已发送**\n\n"
                f"目标频道：{chat_identifier}\n"
                f"消息 ID：{sent_message.message_id}",
                parse_mode="Markdown",
            )

        except Exception as e:
            logger.error(f"Send to channel error: {e}")
            await emit_audit_event(
                self,
                user,
                "admin_send_to_channel",
                {
                    "status": "failed",
                    "reason": type(e).__name__,
                    "chat_identifier": chat_identifier,
                    "message": summarize_message_text(message_text),
                },
            )
            await update.message.reply_text(f"❌ 发送失败\n\n" f"错误：{str(e)}")
