from telegram import Update

from .config import Config

ADMIN_PERMISSION_DENIED_MESSAGE = "❌ 您没有管理员权限"


class AdminPermissionMixin:
    async def _require_admin(self, update: Update):
        """Return the current user only when they have admin permission."""
        user = await self._get_or_create_user(update)
        if self._is_admin_user(user):
            return user

        await update.message.reply_text(ADMIN_PERMISSION_DENIED_MESSAGE)
        return None

    def _is_admin_user(self, user) -> bool:
        return Config.is_admin(user.telegram_id)
