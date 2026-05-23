from .bot_admin_channel_topics import AdminChannelTopics, AdminChannelTopicsMixin
from .bot_admin_channels import AdminChannels, AdminChannelsMixin
from .bot_admin_core import AdminCore, AdminCoreMixin
from .bot_admin_messaging import AdminMessaging, AdminMessagingMixin
from .bot_admin_monitoring import AdminMonitoring, AdminMonitoringMixin
from .bot_admin_permissions import AdminPermission, AdminPermissionMixin


class AdminHandlers:
    """Composed coordinator for admin operations."""

    def __init__(self, bot):
        self.bot = bot
        self.permissions = AdminPermission(bot)
        self.core = AdminCore(bot)
        self.channels = AdminChannels(bot)
        self.channel_topics = AdminChannelTopics(bot)
        self.messaging = AdminMessaging(bot)
        self.monitoring = AdminMonitoring(bot)


class AdminHandlersMixin(
    AdminPermissionMixin,
    AdminCoreMixin,
    AdminChannelsMixin,
    AdminChannelTopicsMixin,
    AdminMessagingMixin,
    AdminMonitoringMixin,
):
    """Aggregate admin handler mixins for the Telegram bot."""

    @property
    def admin_handlers(self) -> AdminHandlers:
        if not hasattr(self, "_admin_handlers_delegate"):
            self._admin_handlers_delegate = AdminHandlers(self)
        return self._admin_handlers_delegate

    @admin_handlers.setter
    def admin_handlers(self, value: AdminHandlers):
        self._admin_handlers_delegate = value

    @property
    def admin_permission(self) -> AdminPermission:
        return self.admin_handlers.permissions

    @property
    def admin_core(self) -> AdminCore:
        return self.admin_handlers.core

    @property
    def admin_channels(self) -> AdminChannels:
        return self.admin_handlers.channels

    @property
    def admin_channel_topics(self) -> AdminChannelTopics:
        return self.admin_handlers.channel_topics

    @property
    def admin_messaging(self) -> AdminMessaging:
        return self.admin_handlers.messaging

    @property
    def admin_monitoring(self) -> AdminMonitoring:
        return self.admin_handlers.monitoring
