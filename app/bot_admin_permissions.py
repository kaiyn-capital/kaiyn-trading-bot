from telegram import Update

ADMIN_PERMISSION_DENIED_MESSAGE = "❌ 您没有管理员权限"
TRADER_PERMISSION_DENIED_MESSAGE = "❌ 您没有交易员权限"


class AdminPermission:
    """Standalone permission helper for bot admins."""

    def __init__(self, bot):
        self.bot = bot

    async def _require_admin(self, update: Update):
        """Return the current user only when they have admin permission."""
        user = await self.bot._get_or_create_user(update)
        if self.bot._is_admin_user(user):
            return user

        await update.message.reply_text(ADMIN_PERMISSION_DENIED_MESSAGE)
        return None

    def _is_admin_user(self, user) -> bool:
        return self.bot.settings.is_admin(user.telegram_id)

    async def _require_trader(self, update: Update):
        """Return the current user only when they have trader or admin permission."""
        user = await self.bot._get_or_create_user(update)
        if self.bot._is_admin_user(user) or getattr(user, "is_trader", False):
            return user

        await update.message.reply_text(TRADER_PERMISSION_DENIED_MESSAGE)
        return None


class AdminPermissionMixin:
    @property
    def admin_permission(self) -> AdminPermission:
        if not hasattr(self, "_admin_permission_delegate"):
            self._admin_permission_delegate = AdminPermission(self)
        return self._admin_permission_delegate

    async def _require_admin(self, update: Update):
        return await self.admin_permission._require_admin(update)

    def _is_admin_user(self, user) -> bool:
        return self.admin_permission._is_admin_user(user)

    async def _require_trader(self, update: Update):
        return await self.admin_permission._require_trader(update)
