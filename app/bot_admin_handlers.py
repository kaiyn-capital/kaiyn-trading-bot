from .bot_admin_channels import AdminChannelsMixin
from .bot_admin_core import AdminCoreMixin
from .bot_admin_messaging import AdminMessagingMixin
from .bot_admin_monitoring import AdminMonitoringMixin


class AdminHandlersMixin(
    AdminCoreMixin,
    AdminChannelsMixin,
    AdminMessagingMixin,
    AdminMonitoringMixin,
):
    """Aggregate admin handler mixins for the Telegram bot."""

    pass
