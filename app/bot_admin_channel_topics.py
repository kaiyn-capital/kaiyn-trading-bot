import logging

from telegram import Update
from telegram.ext import ContextTypes

from .audit import emit_audit_event
from .bot_admin_channel_formatters import (
    CLEAR_CHANNEL_TOPIC_USAGE_MESSAGE,
    SET_CHANNEL_TOPIC_USAGE_MESSAGE,
    format_topic_cleared_html,
    format_topic_set_html,
)
from .telegram_formatting import HTML_PARSE_MODE

logger = logging.getLogger(__name__)


class AdminChannelTopics:
    """Standalone use-case coordinator for channel topics management."""

    def __init__(self, bot):
        self.bot = bot

    async def set_channel_topic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set a default Telegram topic for signal forwarding."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        if len(context.args) < 2:
            await update.message.reply_text(
                SET_CHANNEL_TOPIC_USAGE_MESSAGE,
                parse_mode=HTML_PARSE_MODE,
            )
            return

        try:
            channel_index = int(context.args[0])
            message_thread_id = int(context.args[1])
            if channel_index <= 0 or message_thread_id <= 0:
                raise ValueError
        except ValueError:
            await emit_audit_event(
                self.bot,
                user,
                "admin_set_channel_topic",
                {"status": "failed", "reason": "invalid_input"},
            )
            await update.message.reply_text("❌ 频道编号和 topic_id 必须是正整数")
            return

        thread_title = " ".join(context.args[2:]).strip() or None
        channel = await self.bot._get_active_channel_by_number(channel_index)
        if not channel:
            await emit_audit_event(
                self.bot,
                user,
                "admin_set_channel_topic",
                {
                    "status": "failed",
                    "reason": "invalid_channel_number",
                    "channel_number": channel_index,
                    "message_thread_id": message_thread_id,
                    "thread_title": thread_title,
                },
            )
            await update.message.reply_text("❌ 无效的频道编号，请先使用 /admin_channels 查看列表")
            return

        success = await self.bot.channel_repo.update_channel_topic(channel.chat_id, message_thread_id, thread_title)
        if not success:
            await emit_audit_event(
                self.bot,
                user,
                "admin_set_channel_topic",
                {
                    "status": "failed",
                    "reason": "repository_returned_false",
                    "channel_number": channel_index,
                    "chat_id": channel.chat_id,
                    "channel_title": channel.title,
                    "message_thread_id": message_thread_id,
                    "thread_title": thread_title,
                },
            )
            await update.message.reply_text("❌ 设置指定话题失败，请稍后重试")
            return

        display_title = thread_title or str(message_thread_id)
        await emit_audit_event(
            self.bot,
            user,
            "admin_set_channel_topic",
            {
                "status": "success",
                "channel_number": channel_index,
                "chat_id": channel.chat_id,
                "channel_title": channel.title,
                "message_thread_id": message_thread_id,
                "thread_title": thread_title,
            },
        )
        await update.message.reply_text(
            format_topic_set_html(channel.title, message_thread_id, display_title),
            parse_mode=HTML_PARSE_MODE,
        )

    async def clear_channel_topic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clear a default Telegram topic for signal forwarding."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        if len(context.args) != 1:
            await update.message.reply_text(
                CLEAR_CHANNEL_TOPIC_USAGE_MESSAGE,
                parse_mode=HTML_PARSE_MODE,
            )
            return

        try:
            channel_index = int(context.args[0])
            if channel_index <= 0:
                raise ValueError
        except ValueError:
            await emit_audit_event(
                self.bot,
                user,
                "admin_clear_channel_topic",
                {"status": "failed", "reason": "invalid_input"},
            )
            await update.message.reply_text("❌ 频道编号必须是正整数")
            return

        channel = await self.bot._get_active_channel_by_number(channel_index)
        if not channel:
            await emit_audit_event(
                self.bot,
                user,
                "admin_clear_channel_topic",
                {
                    "status": "failed",
                    "reason": "invalid_channel_number",
                    "channel_number": channel_index,
                },
            )
            await update.message.reply_text("❌ 无效的频道编号，请先使用 /admin_channels 查看列表")
            return

        success = await self.bot.channel_repo.clear_channel_topic(channel.chat_id)
        if not success:
            await emit_audit_event(
                self.bot,
                user,
                "admin_clear_channel_topic",
                {
                    "status": "failed",
                    "reason": "repository_returned_false",
                    "channel_number": channel_index,
                    "chat_id": channel.chat_id,
                    "channel_title": channel.title,
                },
            )
            await update.message.reply_text("❌ 清除指定话题失败，请稍后重试")
            return

        await emit_audit_event(
            self.bot,
            user,
            "admin_clear_channel_topic",
            {
                "status": "success",
                "channel_number": channel_index,
                "chat_id": channel.chat_id,
                "channel_title": channel.title,
            },
        )
        await update.message.reply_text(
            format_topic_cleared_html(channel.title),
            parse_mode=HTML_PARSE_MODE,
        )

    async def _get_active_channel_by_number(self, channel_number: int):
        channels = await self.bot.channel_repo.get_active_channels()
        if channel_number < 1 or channel_number > len(channels):
            return None
        return channels[channel_number - 1]


class AdminChannelTopicsMixin:
    @property
    def admin_channel_topics(self) -> AdminChannelTopics:
        if not hasattr(self, "_admin_channel_topics_delegate"):
            self._admin_channel_topics_delegate = AdminChannelTopics(self)
        return self._admin_channel_topics_delegate

    async def set_channel_topic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_channel_topics.set_channel_topic_command(update, context)

    async def clear_channel_topic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_channel_topics.clear_channel_topic_command(update, context)

    async def _get_active_channel_by_number(self, channel_number: int):
        return await self.admin_channel_topics._get_active_channel_by_number(channel_number)
