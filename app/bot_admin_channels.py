import logging
import re
import traceback

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .audit import emit_audit_event
from .bot_sessions import SESSION_EXPIRED_MESSAGE, UserSessionMixin
from .config import Config

logger = logging.getLogger(__name__)


class AdminChannelsMixin(UserSessionMixin):
    async def delete_channel_by_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Delete a channel by its displayed number."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        if await self._reply_if_session_expired(update, user.telegram_id):
            return

        try:
            session_data = self.get_active_user_session(user.telegram_id)
            if not session_data:
                await update.message.reply_text(SESSION_EXPIRED_MESSAGE)
                return

            channel_number = int(update.message.text.strip())
            channels_data = session_data.get("channels_data", [])

            if not channels_data or channel_number < 1 or channel_number > len(channels_data):
                self.update_user_session(user.telegram_id, {"step": "delete_channel"})
                await emit_audit_event(
                    self,
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
            deleted = await self.channel_repo.deactivate_channel(channel_to_delete["chat_id"])
            if deleted:
                await emit_audit_event(
                    self,
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
                    f"✅ 频道已删除\n\n频道名称：{channel_to_delete['title']}\n已从管理列表中移除。"
                )
            else:
                await emit_audit_event(
                    self,
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

            self.user_sessions.pop(user.telegram_id, None)

        except ValueError:
            self.update_user_session(user.telegram_id, {"step": "delete_channel"})
            await emit_audit_event(
                self,
                user,
                "admin_delete_channel",
                {"status": "failed", "reason": "invalid_input"},
            )
            await update.message.reply_text("❌ 请输入有效的数字")
        except Exception as e:
            logger.error(f"Delete channel error: {e}")
            await emit_audit_event(
                self,
                user,
                "admin_delete_channel",
                {"status": "failed", "reason": type(e).__name__},
            )
            await update.message.reply_text("❌ 删除频道失败")

    async def admin_channels_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List managed channels."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        try:
            channels = await self.channel_repo.get_active_channels()

            if not channels:
                await update.message.reply_text(
                    "📺 **频道/群组管理**\n\n目前没有管理的频道或群组。\n\n使用 `/add_channel` 添加频道或群组。",
                    parse_mode="Markdown",
                )
                return

            channels_text_html = self._format_admin_channels_html(channels)
            await update.message.reply_text(
                channels_text_html,
                reply_markup=self._admin_channels_keyboard(),
                parse_mode="HTML",
            )

        except Exception as e:
            logger.error(f"Admin channels command error: {e}")
            traceback.print_exc()
            await update.message.reply_text(f"❌ 获取频道列表时发生错误: {str(e)}")

    async def add_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add a managed channel or group."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        args = context.args
        if not args:
            await update.message.reply_text(
                "📺 **添加频道/群组**\n\n"
                "使用方法：\n"
                "`/add_channel @username 描述`\n"
                "`/add_channel -1001234567890 私人群组`\n\n"
                "**注意：**\n"
                "• 机器人必须是频道/群组的管理员\n"
                "• 对于私人群组，请使用群组的数字 ID\n"
                "• 对于公开频道，可使用 @username",
                parse_mode="Markdown",
            )
            return

        chat_identifier = args[0]
        description = " ".join(args[1:]) if len(args) > 1 else "管理员添加的频道"

        try:
            chat_info = await context.bot.get_chat(chat_identifier)
            bot_member = await context.bot.get_chat_member(chat_identifier, context.bot.id)
            if bot_member.status not in ["administrator", "creator"]:
                await emit_audit_event(
                    self,
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

            existing = await self.channel_repo.get_channel_by_chat_id(str(chat_info.id))
            if existing and existing.is_active:
                await emit_audit_event(
                    self,
                    user,
                    "admin_add_channel",
                    {
                        "status": "already_exists",
                        "chat_id": str(chat_info.id),
                        "channel_title": chat_info.title,
                        "chat_type": chat_info.type.value,
                    },
                )
                await update.message.reply_text(f"⚠️ 频道/群组 {chat_info.title} 已经在管理列表中")
                return

            if existing and not existing.is_active:
                reactivated = await self.channel_repo.reactivate_channel(
                    chat_id=str(chat_info.id),
                    chat_type=chat_info.type.value,
                    title=chat_info.title,
                    username=chat_info.username,
                    added_by_user_id=user.telegram_id,
                    description=description,
                )
                if not reactivated:
                    await emit_audit_event(
                        self,
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
                    self,
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
                    f"✅ <b>频道/群组添加成功</b>\n\n"
                    f"<b>名称：</b> {self._escape_html(str(chat_info.title))}\n"
                    f"<b>类型：</b> {chat_info.type.value}\n"
                    f"<b>ID：</b> <code>{chat_info.id}</code>\n"
                    f"<b>描述：</b> {self._escape_html(description)}\n\n"
                    "现在可以向此频道发送交易信号了！",
                    parse_mode="HTML",
                )
                return

            await self.channel_repo.create_channel(
                chat_id=str(chat_info.id),
                chat_type=chat_info.type.value,
                title=chat_info.title,
                username=chat_info.username,
                added_by_user_id=user.telegram_id,
                description=description,
            )

            await emit_audit_event(
                self,
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
                f"✅ <b>频道/群组添加成功</b>\n\n"
                f"<b>名称：</b> {self._escape_html(str(chat_info.title))}\n"
                f"<b>类型：</b> {chat_info.type.value}\n"
                f"<b>ID：</b> <code>{chat_info.id}</code>\n"
                f"<b>描述：</b> {self._escape_html(description)}\n\n"
                "现在可以向此频道发送交易信号了！",
                parse_mode="HTML",
            )

        except Exception as e:
            logger.error(f"Add channel error: {e}")
            await emit_audit_event(
                self,
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
                f"错误详情：{str(e)}"
            )

    async def set_channel_topic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set a default Telegram topic for signal forwarding."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        if len(context.args) < 2:
            await update.message.reply_text(
                "📌 **设置频道指定话题**\n\n"
                "使用方法：\n"
                "`/set_channel_topic 频道编号 topic_id [话题名称]`\n\n"
                "例如：\n"
                "`/set_channel_topic 1 12345 交易信号`",
                parse_mode="Markdown",
            )
            return

        try:
            channel_index = int(context.args[0])
            message_thread_id = int(context.args[1])
            if channel_index <= 0 or message_thread_id <= 0:
                raise ValueError
        except ValueError:
            await emit_audit_event(
                self,
                user,
                "admin_set_channel_topic",
                {"status": "failed", "reason": "invalid_input"},
            )
            await update.message.reply_text("❌ 频道编号和 topic_id 必须是正整数")
            return

        thread_title = " ".join(context.args[2:]).strip() or None
        channel = await self._get_active_channel_by_number(channel_index)
        if not channel:
            await emit_audit_event(
                self,
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

        success = await self.channel_repo.update_channel_topic(channel["chat_id"], message_thread_id, thread_title)
        if not success:
            await emit_audit_event(
                self,
                user,
                "admin_set_channel_topic",
                {
                    "status": "failed",
                    "reason": "repository_returned_false",
                    "channel_number": channel_index,
                    "chat_id": channel["chat_id"],
                    "channel_title": channel.get("title"),
                    "message_thread_id": message_thread_id,
                    "thread_title": thread_title,
                },
            )
            await update.message.reply_text("❌ 设置指定话题失败，请稍后重试")
            return

        display_title = thread_title or str(message_thread_id)
        await emit_audit_event(
            self,
            user,
            "admin_set_channel_topic",
            {
                "status": "success",
                "channel_number": channel_index,
                "chat_id": channel["chat_id"],
                "channel_title": channel.get("title"),
                "message_thread_id": message_thread_id,
                "thread_title": thread_title,
            },
        )
        await update.message.reply_text(
            f"✅ <b>指定话题已设置</b>\n\n"
            f"<b>频道：</b> {self._escape_html(str(channel['title'] or 'Unknown'))}\n"
            f"<b>Topic ID：</b> <code>{message_thread_id}</code>\n"
            f"<b>话题名称：</b> {self._escape_html(display_title)}",
            parse_mode="HTML",
        )

    async def clear_channel_topic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clear a default Telegram topic for signal forwarding."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        if len(context.args) != 1:
            await update.message.reply_text(
                "📌 **清除频道指定话题**\n\n"
                "使用方法：\n"
                "`/clear_channel_topic 频道编号`\n\n"
                "例如：\n"
                "`/clear_channel_topic 1`",
                parse_mode="Markdown",
            )
            return

        try:
            channel_index = int(context.args[0])
            if channel_index <= 0:
                raise ValueError
        except ValueError:
            await emit_audit_event(
                self,
                user,
                "admin_clear_channel_topic",
                {"status": "failed", "reason": "invalid_input"},
            )
            await update.message.reply_text("❌ 频道编号必须是正整数")
            return

        channel = await self._get_active_channel_by_number(channel_index)
        if not channel:
            await emit_audit_event(
                self,
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

        success = await self.channel_repo.clear_channel_topic(channel["chat_id"])
        if not success:
            await emit_audit_event(
                self,
                user,
                "admin_clear_channel_topic",
                {
                    "status": "failed",
                    "reason": "repository_returned_false",
                    "channel_number": channel_index,
                    "chat_id": channel["chat_id"],
                    "channel_title": channel.get("title"),
                },
            )
            await update.message.reply_text("❌ 清除指定话题失败，请稍后重试")
            return

        await emit_audit_event(
            self,
            user,
            "admin_clear_channel_topic",
            {
                "status": "success",
                "channel_number": channel_index,
                "chat_id": channel["chat_id"],
                "channel_title": channel.get("title"),
            },
        )
        await update.message.reply_text(
            f"✅ <b>指定话题已清除</b>\n\n<b>频道：</b> {self._escape_html(str(channel['title'] or 'Unknown'))}",
            parse_mode="HTML",
        )

    async def _handle_add_new_channel_callback(self, query, user):
        await query.edit_message_text(
            "📺 **添加频道/群组**\n\n"
            "请使用 `/add_channel` 命令添加新的频道或群组。\n\n"
            "使用方法：\n"
            "`/add_channel @username 描述`\n"
            "`/add_channel -1001234567890 私人群组`",
            parse_mode="Markdown",
        )

    async def _handle_manage_channels_callback(self, query, user):
        try:
            channels = await self.channel_repo.get_active_channels()

            if not channels:
                await query.edit_message_text(
                    "📺 **管理频道**\n\n目前没有任何频道。\n\n使用 `/add_channel` 添加频道。",
                    parse_mode="Markdown",
                )
                return

            channels_data = [
                {
                    "id": i,
                    "chat_id": channel["chat_id"],
                    "title": channel["title"] or "Unknown",
                    "username": channel["username"],
                }
                for i, channel in enumerate(channels, 1)
            ]

            manage_text = "📺 <b>管理频道</b>\n\n"
            for ch in channels_data:
                title_escaped = self._escape_html(str(ch["title"]))
                username_text = f"(@{ch['username']})" if ch["username"] else ""
                manage_text += f"{ch['id']}. {title_escaped} {username_text}\n"

            manage_text += "\n请选择操作："

            keyboard = [
                [InlineKeyboardButton("🗑️ 删除频道", callback_data="delete_channel_start")],
                [InlineKeyboardButton("🔙 返回", callback_data="return_admin_channels")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            self.set_user_session(user.telegram_id, {"channels_data": channels_data})

            await query.edit_message_text(manage_text, reply_markup=reply_markup, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Manage channels error: {e}")
            await query.edit_message_text(f"❌ 获取频道列表失败\n\n错误详情: {str(e)}\n\n请检查数据库连接状态。")

    async def _handle_delete_channel_start_callback(self, query, user):
        session_data = self.get_active_user_session(user.telegram_id)
        if not session_data or not session_data.get("channels_data"):
            self.user_sessions.pop(user.telegram_id, None)
            await query.edit_message_text(SESSION_EXPIRED_MESSAGE)
            return

        await query.edit_message_text(
            "🗑️ **删除频道**\n\n请输入要删除的频道编号：",
            parse_mode="Markdown",
        )
        self.update_user_session(user.telegram_id, {"step": "delete_channel"})

    async def _handle_return_admin_channels_callback(self, query, user):
        try:
            channels = await self.channel_repo.get_active_channels()

            if not channels:
                await query.edit_message_text(
                    "📺 **频道/群组管理**\n\n目前没有管理的频道或群组。\n\n使用 `/add_channel` 添加频道或群组。",
                    parse_mode="Markdown",
                )
                return

            await query.edit_message_text(
                self._format_admin_channels_html(channels),
                reply_markup=self._admin_channels_keyboard(),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Return admin channels error: {e}")
            await query.edit_message_text("❌ 获取频道列表失败")

    def _admin_channels_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("➕ 添加频道", callback_data="add_new_channel")],
                [InlineKeyboardButton("⚙️ 管理设置", callback_data="manage_channels")],
            ]
        )

    def _format_admin_channels_html(self, channels) -> str:
        channels_text = "📺 **已管理的频道/群组**\n\n"
        for channel in channels:
            status = "✅" if channel["auto_forward_signals"] else "❌"
            title = channel["title"] or "Unknown"
            chat_type = channel["chat_type"]
            username = channel["username"]

            channels_text += f"{status} **{title}**\n"
            channels_text += f"   类型: {chat_type}\n"
            channels_text += f"   ID: `{channel['chat_id']}`\n"
            if username:
                channels_text += f"   用户名: @{username}\n"
            channels_text += f"   自动转发: {'开启' if channel['auto_forward_signals'] else '关闭'}\n"
            channels_text += f"   指定话题: {self._format_channel_topic(channel)}\n\n"

        channels_text_html = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", channels_text)
        return re.sub(r"`(.*?)`", r"<code>\1</code>", channels_text_html)

    def _escape_html(self, text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    async def _get_active_channel_by_number(self, channel_number: int):
        channels = await self.channel_repo.get_active_channels()
        if channel_number < 1 or channel_number > len(channels):
            return None
        return channels[channel_number - 1]

    def _format_channel_topic(self, channel) -> str:
        message_thread_id = channel.get("message_thread_id")
        if not message_thread_id:
            return "未设置"
        return self._escape_html(str(channel.get("thread_title") or message_thread_id))
