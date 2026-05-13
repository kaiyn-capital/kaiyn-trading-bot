import logging

from telegram import Update
from telegram.ext import ContextTypes

from .audit import AUDIT_MODULE, format_audit_log_entry
from .config import Config
from .health import build_admin_health_report

logger = logging.getLogger(__name__)


class AdminMonitoringMixin:
    async def admin_audit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show recent operator audit events for admins."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
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
            logs = await self.system_log_repo.get_recent_logs(levels=["INFO"], module=AUDIT_MODULE, limit=limit)
            if not logs:
                await update.message.reply_text("📋 近期没有操作审计记录")
                return

            lines = [format_audit_log_entry(log_entry) for log_entry in logs]
            await update.message.reply_text(
                "📋 近期操作审计\n\n" + "\n".join(f"{index}. {line}" for index, line in enumerate(lines, 1))
            )
        except Exception as e:
            logger.error(f"Admin audit command error: {e}")
            await update.message.reply_text(f"❌ 获取操作审计时发生错误: {str(e)}")

    async def admin_health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show health details for admins."""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        try:
            report, _status = await build_admin_health_report(
                db_manager=self.user_repo.db,
                system_log_repo=self.system_log_repo,
                started_at=getattr(self, "started_at", None),
            )
            await update.message.reply_text(report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Admin health command error: {e}")
            await update.message.reply_text(f"❌ 获取健康状态时发生错误: {str(e)}")
