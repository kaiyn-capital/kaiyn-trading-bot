import logging

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .audit import emit_audit_event
from .decimal_utils import decimal_text
from .telegram_formatting import HTML_PARSE_MODE, html_code, html_escape

logger = logging.getLogger(__name__)


class AdminCore:
    """Standalone use-case coordinator for core admin functionality."""

    def __init__(self, bot):
        self.bot = bot

    async def add_trader_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add a signal sender."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        if not context.args:
            await update.message.reply_text(
                "👥 <b>添加发单员</b>\n\n"
                f"使用方法：\n{html_code('/add_trader Telegram_ID')}\n\n"
                f"例如：\n{html_code('/add_trader 123456789')}",
                parse_mode=HTML_PARSE_MODE,
            )
            return

        try:
            telegram_id = int(context.args[0])
            success = await self.bot.user_repo.set_trader_status(telegram_id, True)

            if success:
                await emit_audit_event(
                    self.bot,
                    user,
                    "admin_add_trader",
                    {"status": "success", "target_telegram_id": telegram_id},
                )
                await update.message.reply_text(
                    "✅ <b>发单员添加成功</b>\n\n"
                    f"Telegram ID：{html_escape(telegram_id)}\n"
                    f"现在该用户可以使用 {html_code('/send_signal')} 命令发送交易信号。",
                    parse_mode=HTML_PARSE_MODE,
                )
            else:
                await emit_audit_event(
                    self.bot,
                    user,
                    "admin_add_trader",
                    {
                        "status": "failed",
                        "target_telegram_id": telegram_id,
                        "reason": "repository_returned_false",
                    },
                )
                await update.message.reply_text("❌ 设置发单员失败，请稍后重试")

        except ValueError:
            await emit_audit_event(
                self.bot,
                user,
                "admin_add_trader",
                {"status": "failed", "reason": "invalid_telegram_id"},
            )
            await update.message.reply_text("❌ Telegram ID 必须是数字")
        except (SQLAlchemyError, TelegramError) as e:
            logger.error(f"Add trader error: {e}")
            await emit_audit_event(
                self.bot,
                user,
                "admin_add_trader",
                {"status": "failed", "reason": type(e).__name__},
            )
            await update.message.reply_text("❌ 添加发单员失败")

    async def admin_users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List active users for admins."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        try:
            users_data = await self.bot.user_repo.get_active_users()

            users_text = "👥 <b>用户列表</b>\n\n"
            for u in users_data[:20]:
                api_status = "✅" if u.is_api_connected else "❌"
                first_name = html_escape(u.first_name or "Unknown")
                username = html_escape(u.username or "N/A")
                telegram_id = html_escape(u.telegram_id)
                created_at = u.created_at

                trader_status = " | ⭐️发单员" if u.is_trader else ""
                fixed_risk = u.fixed_risk_amount
                risk_status = f" | 1R: {html_escape(decimal_text(fixed_risk))} USDT" if fixed_risk is not None else ""

                users_text += f"{api_status} {first_name} (@{username})\n"
                users_text += (
                    f"   ID: {telegram_id} | 注册: {html_escape(created_at.strftime('%m-%d') if created_at else 'N/A')}"
                    f"{trader_status}{risk_status}\n\n"
                )

            if len(users_data) > 20:
                users_text += f"... 还有 {html_escape(len(users_data) - 20)} 位用户"

            await update.message.reply_text(users_text, parse_mode=HTML_PARSE_MODE)

        except (SQLAlchemyError, TelegramError, TypeError, ValueError) as e:
            logger.error(f"Admin users command error: {e}")
            await update.message.reply_text("❌ 获取用户列表时发生错误")

    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin panel."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        try:
            users_data = await self.bot.user_repo.get_active_users()
            active_users = len(users_data)
            channel_count = await self.bot.channel_repo.count_active_channels()
            db_ok = await self.bot.user_repo.db.health_check()

            admin_text = "👑 <b>管理员面板</b>\n\n"
            admin_text += "📊 <b>系统统计</b>\n"
            admin_text += f"• 活跃用户：{html_escape(active_users)}\n"
            admin_text += f"• 管理频道：{html_escape(channel_count)}\n"
            admin_text += f"• 系统状态：{'正常' if db_ok else '异常'}\n\n"
            admin_text += "🛠️ <b>管理功能</b>\n"
            admin_text += f"• {html_code('/admin_users')} - 查看用户列表\n"
            admin_text += f"• {html_code('/admin_channels')} - 管理频道/群组\n"
            admin_text += f"• {html_code('/add_channel')} - 添加频道/群组\n"
            admin_text += f"• {html_code('/admin_broadcast')} - 广播消息\n"
            admin_text += f"• {html_code('/send_signal')} - 发送交易信号\n"
            admin_text += f"• {html_code('/send_to_channel')} - 发送到指定频道\n"
            admin_text += f"• {html_code('/set_channel_topic')} - 设置频道指定话题\n"
            admin_text += f"• {html_code('/clear_channel_topic')} - 清除频道指定话题\n"
            admin_text += f"• {html_code('/admin_health')} - 查看系统健康状态\n"
            admin_text += f"• {html_code('/admin_audit')} - 查看近期操作审计\n"
            admin_text += f"• {html_code('/add_trader')} - 添加交易员"

            await update.message.reply_text(admin_text, parse_mode=HTML_PARSE_MODE)

        except (SQLAlchemyError, TelegramError, TypeError, ValueError) as e:
            logger.exception(f"Admin command error: {e}")
            await update.message.reply_text(f"❌ 获取管理信息时发生错误: {str(e)}")


class AdminCoreMixin:
    @property
    def admin_core(self) -> AdminCore:
        if not hasattr(self, "_admin_core_delegate"):
            self._admin_core_delegate = AdminCore(self)
        return self._admin_core_delegate

    async def add_trader_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_core.add_trader_command(update, context)

    async def admin_users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_core.admin_users_command(update, context)

    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_core.admin_command(update, context)
