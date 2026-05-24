import logging

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .audit import emit_audit_event
from .bot_admin_channel_formatters import (
    ADD_CHANNEL_USAGE_MESSAGE,
    ADD_NEW_CHANNEL_CALLBACK_MESSAGE,
    ADMIN_CHANNELS_EMPTY_MESSAGE,
    DELETE_CHANNEL_PROMPT_MESSAGE,
    MANAGE_CHANNELS_EMPTY_MESSAGE,
    admin_channels_keyboard,
    build_manage_channels_data,
    format_admin_channels_html,
    format_channel_added_html,
    format_manage_channels_html,
    manage_channels_keyboard,
)
from .bot_sessions import SESSION_EXPIRED_MESSAGE, UserSessionMixin
from .telegram_formatting import HTML_PARSE_MODE, html_escape

logger = logging.getLogger(__name__)


class AdminChannels:
    """Standalone use-case coordinator for admin channels management."""

    def __init__(self, bot):
        self.bot = bot

    async def delete_channel_by_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Delete a channel by its displayed number."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        if await self.bot._reply_if_session_expired(update, user.telegram_id):
            return

        try:
            session_data = self.bot.get_active_user_session(user.telegram_id)
            if not session_data:
                await update.message.reply_text(SESSION_EXPIRED_MESSAGE)
                return

            channel_number = int(update.message.text.strip())
            channels_data = session_data.get("channels_data", [])

            if not channels_data or channel_number < 1 or channel_number > len(channels_data):
                self.bot.update_user_session(user.telegram_id, {"step": "delete_channel"})
                await emit_audit_event(
                    self.bot,
                    user,
                    "admin_delete_channel",
                    {
                        "status": "failed",
                        "reason": "invalid_channel_number",
                        "channel_number": channel_number,
                    },
                )
                await update.message.reply_text("❌ 无效的频道编号")
                return

            channel_to_delete = channels_data[channel_number - 1]
            deleted = await self.bot.channel_repo.deactivate_channel(channel_to_delete["chat_id"])
            if deleted:
                await emit_audit_event(
                    self.bot,
                    user,
                    "admin_delete_channel",
                    {
                        "status": "success",
                        "channel_number": channel_number,
                        "chat_id": channel_to_delete["chat_id"],
                        "channel_title": channel_to_delete.get("title"),
                    },
                )
                await update.message.reply_text(
                    f"✅ 频道已删除\n\n频道名称：{html_escape(channel_to_delete['title'])}\n已从管理列表中移除。",
                    parse_mode=HTML_PARSE_MODE,
                )
            else:
                await emit_audit_event(
                    self.bot,
                    user,
                    "admin_delete_channel",
                    {
                        "status": "failed",
                        "reason": "not_found",
                        "channel_number": channel_number,
                        "chat_id": channel_to_delete["chat_id"],
                        "channel_title": channel_to_delete.get("title"),
                    },
                )
                await update.message.reply_text("❌ 找不到指定的频道")

            self.bot.delete_user_session(user.telegram_id)

        except ValueError:
            self.bot.update_user_session(user.telegram_id, {"step": "delete_channel"})
            await emit_audit_event(
                self.bot,
                user,
                "admin_delete_channel",
                {"status": "failed", "reason": "invalid_input"},
            )
            await update.message.reply_text("❌ 请输入有效的数字")
        except (KeyError, SQLAlchemyError, TelegramError, TypeError) as e:
            logger.error(f"Delete channel error: {e}")
            await emit_audit_event(
                self.bot,
                user,
                "admin_delete_channel",
                {"status": "failed", "reason": type(e).__name__},
            )
            await update.message.reply_text("❌ 删除频道失败")

    async def admin_channels_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List managed channels."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        try:
            channels = await self.bot.channel_repo.get_active_channels()

            if not channels:
                await update.message.reply_text(
                    ADMIN_CHANNELS_EMPTY_MESSAGE,
                    parse_mode=HTML_PARSE_MODE,
                )
                return

            channels_text_html = format_admin_channels_html(channels)
            await update.message.reply_text(
                channels_text_html,
                reply_markup=admin_channels_keyboard(),
                parse_mode=HTML_PARSE_MODE,
            )

        except (SQLAlchemyError, TelegramError, TypeError, ValueError) as e:
            logger.exception(f"Admin channels command error: {e}")
            await update.message.reply_text(
                f"❌ 获取频道列表时发生错误: {html_escape(e)}",
                parse_mode=HTML_PARSE_MODE,
            )

    async def add_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add a managed channel or group."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        args = context.args
        if not args:
            await update.message.reply_text(
                ADD_CHANNEL_USAGE_MESSAGE,
                parse_mode=HTML_PARSE_MODE,
            )
            return

        chat_identifier = args[0]
        description = " ".join(args[1:]) if len(args) > 1 else "管理员添加的频道"

        try:
            chat_info = await context.bot.get_chat(chat_identifier)
            bot_member = await context.bot.get_chat_member(chat_identifier, context.bot.id)
            if bot_member.status not in ["administrator", "creator"]:
                await emit_audit_event(
                    self.bot,
                    user,
                    "admin_add_channel",
                    {
                        "status": "failed",
                        "reason": "bot_not_admin",
                        "chat_id": str(chat_info.id),
                        "channel_title": chat_info.title,
                        "chat_type": chat_info.type.value,
                    },
                )
                await update.message.reply_text(
                    "❌ 机器人在该频道/群组中不是管理员\n\n请确保机器人有管理员权限后再试。"
                )
                return

            existing = await self.bot.channel_repo.get_channel_by_chat_id(str(chat_info.id))
            if existing and existing.is_active:
                await emit_audit_event(
                    self.bot,
                    user,
                    "admin_add_channel",
                    {
                        "status": "already_exists",
                        "chat_id": str(chat_info.id),
                        "channel_title": chat_info.title,
                        "chat_type": chat_info.type.value,
                    },
                )
                await update.message.reply_text(
                    f"⚠️ 频道/群组 {html_escape(chat_info.title)} 已经在管理列表中",
                    parse_mode=HTML_PARSE_MODE,
                )
                return

            if existing and not existing.is_active:
                reactivated = await self.bot.channel_repo.reactivate_channel(
                    chat_id=str(chat_info.id),
                    chat_type=chat_info.type.value,
                    title=chat_info.title,
                    username=chat_info.username,
                    added_by_user_id=user.telegram_id,
                    description=description,
                )
                if not reactivated:
                    await emit_audit_event(
                        self.bot,
                        user,
                        "admin_add_channel",
                        {
                            "status": "failed",
                            "reason": "reactivate_failed",
                            "chat_id": str(chat_info.id),
                            "channel_title": chat_info.title,
                            "chat_type": chat_info.type.value,
                        },
                    )
                    await update.message.reply_text("❌ 重新启用频道失败，请稍后重试")
                    return

                await emit_audit_event(
                    self.bot,
                    user,
                    "admin_add_channel",
                    {
                        "status": "reactivated",
                        "chat_id": str(chat_info.id),
                        "channel_title": chat_info.title,
                        "chat_type": chat_info.type.value,
                    },
                )
                await update.message.reply_text(
                    format_channel_added_html(chat_info.title, chat_info.type.value, chat_info.id, description),
                    parse_mode=HTML_PARSE_MODE,
                )
                return

            await self.bot.channel_repo.create_channel(
                chat_id=str(chat_info.id),
                chat_type=chat_info.type.value,
                title=chat_info.title,
                username=chat_info.username,
                added_by_user_id=user.telegram_id,
                description=description,
            )

            await emit_audit_event(
                self.bot,
                user,
                "admin_add_channel",
                {
                    "status": "created",
                    "chat_id": str(chat_info.id),
                    "channel_title": chat_info.title,
                    "chat_type": chat_info.type.value,
                },
            )
            await update.message.reply_text(
                format_channel_added_html(chat_info.title, chat_info.type.value, chat_info.id, description),
                parse_mode=HTML_PARSE_MODE,
            )

        except (SQLAlchemyError, TelegramError, TypeError, ValueError) as e:
            logger.error(f"Add channel error: {e}")
            await emit_audit_event(
                self.bot,
                user,
                "admin_add_channel",
                {
                    "status": "failed",
                    "reason": type(e).__name__,
                    "chat_identifier": chat_identifier,
                },
            )
            await update.message.reply_text(
                f"❌ 添加频道失败\n\n"
                f"可能的原因：\n"
                f"• 频道/群组不存在\n"
                f"• 机器人没有访问权限\n"
                f"• ID 格式错误\n\n"
                f"错误详情：{html_escape(e)}",
                parse_mode=HTML_PARSE_MODE,
            )

    async def _handle_add_new_channel_callback(self, query, user):
        await query.edit_message_text(
            ADD_NEW_CHANNEL_CALLBACK_MESSAGE,
            parse_mode=HTML_PARSE_MODE,
        )

    async def _handle_manage_channels_callback(self, query, user):
        try:
            channels = await self.bot.channel_repo.get_active_channels()

            if not channels:
                await query.edit_message_text(
                    MANAGE_CHANNELS_EMPTY_MESSAGE,
                    parse_mode=HTML_PARSE_MODE,
                )
                return

            channels_data = build_manage_channels_data(channels)

            self.bot.set_user_session(user.telegram_id, {"channels_data": channels_data})

            await query.edit_message_text(
                format_manage_channels_html(channels_data),
                reply_markup=manage_channels_keyboard(),
                parse_mode=HTML_PARSE_MODE,
            )

        except (SQLAlchemyError, TelegramError, TypeError, ValueError) as e:
            logger.error(f"Manage channels error: {e}")
            await query.edit_message_text(
                f"❌ 获取频道列表失败\n\n错误详情: {html_escape(e)}\n\n请检查数据库连接状态。",
                parse_mode=HTML_PARSE_MODE,
            )

    async def _handle_delete_channel_start_callback(self, query, user):
        session_data = self.bot.get_active_user_session(user.telegram_id)
        if not session_data or not session_data.get("channels_data"):
            self.bot.delete_user_session(user.telegram_id)
            await query.edit_message_text(SESSION_EXPIRED_MESSAGE)
            return

        await query.edit_message_text(
            DELETE_CHANNEL_PROMPT_MESSAGE,
            parse_mode=HTML_PARSE_MODE,
        )
        self.bot.update_user_session(user.telegram_id, {"step": "delete_channel"})

    async def _handle_return_admin_channels_callback(self, query, user):
        try:
            channels = await self.bot.channel_repo.get_active_channels()

            if not channels:
                await query.edit_message_text(
                    ADMIN_CHANNELS_EMPTY_MESSAGE,
                    parse_mode=HTML_PARSE_MODE,
                )
                return

            await query.edit_message_text(
                format_admin_channels_html(channels),
                reply_markup=admin_channels_keyboard(),
                parse_mode=HTML_PARSE_MODE,
            )
        except (SQLAlchemyError, TelegramError, TypeError, ValueError) as e:
            logger.error(f"Return admin channels error: {e}")
            await query.edit_message_text("❌ 获取频道列表失败")


class AdminChannelsMixin(UserSessionMixin):
    @property
    def admin_channels(self) -> AdminChannels:
        if not hasattr(self, "_admin_channels_delegate"):
            self._admin_channels_delegate = AdminChannels(self)
        return self._admin_channels_delegate

    async def delete_channel_by_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_channels.delete_channel_by_number(update, context)

    async def admin_channels_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_channels.admin_channels_command(update, context)

    async def add_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_channels.add_channel_command(update, context)

    async def _handle_add_new_channel_callback(self, query, user):
        await self.admin_channels._handle_add_new_channel_callback(query, user)

    async def _handle_manage_channels_callback(self, query, user):
        await self.admin_channels._handle_manage_channels_callback(query, user)

    async def _handle_delete_channel_start_callback(self, query, user):
        await self.admin_channels._handle_delete_channel_start_callback(query, user)

    async def _handle_return_admin_channels_callback(self, query, user):
        await self.admin_channels._handle_return_admin_channels_callback(query, user)
