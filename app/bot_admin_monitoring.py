import logging

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .audit import AUDIT_MODULE, format_audit_log_entry
from .health import build_admin_health_report
from .telegram_formatting import HTML_PARSE_MODE

logger = logging.getLogger(__name__)


class AdminMonitoring:
    """Standalone coordinator for admin monitoring and health checks."""

    def __init__(self, bot):
        self.bot = bot

    async def admin_audit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show recent operator audit events for admins."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        try:
            limit = 10
            if context.args:
                limit = int(context.args[0])
            limit = max(1, min(limit, 30))
        except ValueError:
            await update.message.reply_text("❌ 数量必须是数字")
            return

        try:
            logs = await self.bot.system_log_repo.get_recent_logs(levels=["INFO"], module=AUDIT_MODULE, limit=limit)
            if not logs:
                await update.message.reply_text("📋 近期没有操作审计记录")
                return

            lines = [format_audit_log_entry(log_entry) for log_entry in logs]
            await update.message.reply_text(
                "📋 近期操作审计\n\n" + "\n".join(f"{index}. {line}" for index, line in enumerate(lines, 1))
            )
        except (SQLAlchemyError, TelegramError, TypeError, ValueError) as e:
            logger.error(f"Admin audit command error: {e}")
            await update.message.reply_text(f"❌ 获取操作审计时发生错误: {str(e)}")

    async def admin_health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show health details for admins."""
        user = await self.bot._require_admin(update)
        if user is None:
            return

        try:
            report, _status = await build_admin_health_report(
                db_manager=self.bot.user_repo.db,
                system_log_repo=self.bot.system_log_repo,
                started_at=getattr(self.bot, "started_at", None),
                pending_order_repo=getattr(self.bot, "pending_order_repo", None),
                settings=self.bot.settings,
            )
            await update.message.reply_text(report, parse_mode=HTML_PARSE_MODE)
        except (SQLAlchemyError, TelegramError, TypeError, ValueError) as e:
            logger.error(f"Admin health command error: {e}")
            await update.message.reply_text(f"❌ 获取健康状态时发生错误: {str(e)}")


class AdminMonitoringMixin:
    @property
    def admin_monitoring(self) -> AdminMonitoring:
        if not hasattr(self, "_admin_monitoring_delegate"):
            self._admin_monitoring_delegate = AdminMonitoring(self)
        return self._admin_monitoring_delegate

    async def admin_audit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_monitoring.admin_audit_command(update, context)

    async def admin_health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.admin_monitoring.admin_health_command(update, context)
