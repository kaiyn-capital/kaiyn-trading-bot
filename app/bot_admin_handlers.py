import logging
import re
import traceback

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .config import Config

logger = logging.getLogger(__name__)


class AdminHandlersMixin:
    async def add_trader_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Add a signal sender."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        if not context.args:
            await update.message.reply_text(
                "👥 **添加发单员**\n\n"
                "使用方法：\n"
                "`/add_trader Telegram_ID`\n\n"
                "例如：\n"
                "`/add_trader 123456789`",
                parse_mode="Markdown",
            )
            return

        try:
            telegram_id = int(context.args[0])
            success = await self.user_repo.set_trader_status(telegram_id, True)

            if success:
                await update.message.reply_text(
                    f"✅ **发单员添加成功**\n\n"
                    f"Telegram ID：{telegram_id}\n"
                    f"现在该用户可以使用 `/send_signal` 命令发送交易信号。",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("❌ 设置发单员失败，请稍后重试")

        except ValueError:
            await update.message.reply_text("❌ Telegram ID 必须是数字")
        except Exception as e:
            logger.error(f"Add trader error: {e}")
            await update.message.reply_text("❌ 添加发单员失败")

    async def delete_channel_by_number(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Delete a channel by its displayed number."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        try:
            channel_number = int(update.message.text.strip())
            session_data = self.user_sessions.get(user.telegram_id, {})
            channels_data = session_data.get("channels_data", [])

            if (
                not channels_data
                or channel_number < 1
                or channel_number > len(channels_data)
            ):
                await update.message.reply_text("❌ 无效的频道编号")
                return

            channel_to_delete = channels_data[channel_number - 1]
            deleted = await self.channel_repo.deactivate_channel(
                channel_to_delete["chat_id"]
            )
            if deleted:
                await update.message.reply_text(
                    f"✅ 频道已删除\n\n"
                    f"频道名称：{channel_to_delete['title']}\n"
                    f"已从管理列表中移除。"
                )
            else:
                await update.message.reply_text("❌ 找不到指定的频道")

            self.user_sessions.pop(user.telegram_id, None)

        except ValueError:
            await update.message.reply_text("❌ 请输入有效的数字")
        except Exception as e:
            logger.error(f"Delete channel error: {e}")
            await update.message.reply_text("❌ 删除频道失败")

    async def admin_users_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """List active users for admins."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        try:
            users_data = await self.user_repo.get_active_users()

            users_text = "👥 **用户列表**\n\n"
            for u in users_data[:20]:
                api_status = "✅" if u.get("is_api_connected") else "❌"
                first_name = u.get("first_name") or "Unknown"
                username = u.get("username") or "N/A"
                telegram_id = u.get("telegram_id")
                created_at = u.get("created_at")

                users_text += f"{api_status} {first_name} (@{username})\n"
                users_text += f"   ID: {telegram_id} | 注册: {created_at.strftime('%m-%d') if created_at else 'N/A'}\n\n"

            if len(users_data) > 20:
                users_text += f"... 还有 {len(users_data) - 20} 位用户"

            users_text_html = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", users_text)
            await update.message.reply_text(users_text_html, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Admin users command error: {e}")
            await update.message.reply_text("❌ 获取用户列表时发生错误")

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

        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            await update.message.reply_text("❌ 广播时发生错误")

    async def admin_channels_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """List managed channels."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        try:
            channels = await self.channel_repo.get_active_channels()

            if not channels:
                await update.message.reply_text(
                    "📺 **频道/群组管理**\n\n"
                    "目前没有管理的频道或群组。\n\n"
                    "使用 `/add_channel` 添加频道或群组。",
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

    async def add_channel_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
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
            bot_member = await context.bot.get_chat_member(
                chat_identifier, context.bot.id
            )
            if bot_member.status not in ["administrator", "creator"]:
                await update.message.reply_text(
                    "❌ 机器人在该频道/群组中不是管理员\n\n"
                    "请确保机器人有管理员权限后再试。"
                )
                return

            existing = await self.channel_repo.get_channel_by_chat_id(str(chat_info.id))
            if existing and existing.is_active:
                await update.message.reply_text(
                    f"⚠️ 频道/群组 {chat_info.title} 已经在管理列表中"
                )
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
                    await update.message.reply_text("❌ 重新启用频道失败，请稍后重试")
                    return

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
            await update.message.reply_text(
                f"❌ 添加频道失败\n\n"
                f"可能的原因：\n"
                f"• 频道/群组不存在\n"
                f"• 机器人没有访问权限\n"
                f"• ID 格式错误\n\n"
                f"错误详情：{str(e)}"
            )

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

            await update.message.reply_text(
                f"✅ **消息已发送**\n\n"
                f"目标频道：{chat_identifier}\n"
                f"消息 ID：{sent_message.message_id}",
                parse_mode="Markdown",
            )

        except Exception as e:
            logger.error(f"Send to channel error: {e}")
            await update.message.reply_text(f"❌ 发送失败\n\n" f"错误：{str(e)}")

    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin panel."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        try:
            users_data = await self.user_repo.get_active_users()
            active_users = len(users_data)
            channel_count = await self.channel_repo.count_active_channels()
            db_ok = await self.user_repo.db.health_check()

            admin_text = f"👑 **管理员面板**\n\n"
            admin_text += f"📊 **系统统计**\n"
            admin_text += f"• 活跃用户：{active_users}\n"
            admin_text += f"• 管理频道：{channel_count}\n"
            admin_text += f"• 系统状态：{'正常' if db_ok else '异常'}\n\n"
            admin_text += f"🛠️ **管理功能**\n"
            admin_text += f"• `/admin_users` - 查看用户列表\n"
            admin_text += f"• `/admin_channels` - 管理频道/群组\n"
            admin_text += f"• `/add_channel` - 添加频道/群组\n"
            admin_text += f"• `/admin_broadcast` - 广播消息\n"
            admin_text += f"• `/send_signal` - 发送交易信号\n"
            admin_text += f"• `/send_to_channel` - 发送到指定频道\n"
            admin_text += f"• `/add_trader` - 添加交易员"

            await update.message.reply_text(admin_text, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Admin command error: {e}")
            traceback.print_exc()
            await update.message.reply_text(f"❌ 获取管理信息时发生错误: {str(e)}")

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
                    "📺 **管理频道**\n\n"
                    "目前没有任何频道。\n\n"
                    "使用 `/add_channel` 添加频道。",
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

            self.user_sessions[user.telegram_id] = {"channels_data": channels_data}

            await query.edit_message_text(
                manage_text, reply_markup=reply_markup, parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Manage channels error: {e}")
            await query.edit_message_text(
                "❌ 获取频道列表失败\n\n"
                f"错误详情: {str(e)}\n\n"
                "请检查数据库连接状态。"
            )

    async def _handle_delete_channel_start_callback(self, query, user):
        await query.edit_message_text(
            "🗑️ **删除频道**\n\n" "请输入要删除的频道编号：",
            parse_mode="Markdown",
        )
        if user.telegram_id in self.user_sessions:
            self.user_sessions[user.telegram_id]["step"] = "delete_channel"
        else:
            self.user_sessions[user.telegram_id] = {"step": "delete_channel"}

    async def _handle_return_admin_channels_callback(self, query, user):
        try:
            channels = await self.channel_repo.get_active_channels()

            if not channels:
                await query.edit_message_text(
                    "📺 **频道/群组管理**\n\n"
                    "目前没有管理的频道或群组。\n\n"
                    "使用 `/add_channel` 添加频道或群组。",
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
            channels_text += f"   自动转发: {'开启' if channel['auto_forward_signals'] else '关闭'}\n\n"

        channels_text_html = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", channels_text)
        return re.sub(r"`(.*?)`", r"<code>\1</code>", channels_text_html)

    def _escape_html(self, text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
