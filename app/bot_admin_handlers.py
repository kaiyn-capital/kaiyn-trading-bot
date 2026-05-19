from .bot_admin_channel_topics import AdminChannelTopicsMixin
from .bot_admin_channels import AdminChannelsMixin
from .bot_admin_core import AdminCoreMixin
from .bot_admin_messaging import AdminMessagingMixin
from .bot_admin_monitoring import AdminMonitoringMixin
from .bot_admin_permissions import AdminPermissionMixin


class AdminHandlersMixin(
    AdminPermissionMixin,
    AdminCoreMixin,
    AdminChannelsMixin,
    AdminChannelTopicsMixin,
    AdminMessagingMixin,
    AdminMonitoringMixin,
):
    """Aggregate admin handler mixins for the Telegram bot."""

    pass
