class BotHandlerContext:
    """Explicit facade passed to handler coordinators instead of the whole bot."""

    def __init__(self, owner):
        self._owner = owner

    @property
    def application(self):
        return self._owner.application

    @property
    def user_repo(self):
        return self._owner.user_repo

    @property
    def trade_repo(self):
        return self._owner.trade_repo

    @property
    def pending_order_repo(self):
        return self._owner.pending_order_repo

    @property
    def system_log_repo(self):
        return self._owner.system_log_repo

    @property
    def channel_repo(self):
        return self._owner.channel_repo

    @property
    def signal_record_repo(self):
        return self._owner.signal_record_repo

    @property
    def encryption_manager(self):
        return self._owner.encryption_manager

    @property
    def trade_manager(self):
        return self._owner.trade_manager

    @property
    def started_at(self):
        return getattr(self._owner, "started_at", None)

    def set_user_session(self, telegram_id: int, data: dict):
        return self._owner.set_user_session(telegram_id, data)

    def update_user_session(self, telegram_id: int, updates: dict):
        return self._owner.update_user_session(telegram_id, updates)

    def get_active_user_session(self, telegram_id: int):
        return self._owner.get_active_user_session(telegram_id)

    def peek_user_session(self, telegram_id: int):
        return self._owner.peek_user_session(telegram_id)

    def pop_expired_user_session(self, telegram_id: int):
        return self._owner.pop_expired_user_session(telegram_id)

    def delete_user_session(self, telegram_id: int) -> None:
        self._owner.delete_user_session(telegram_id)

    async def _reply_if_session_expired(self, update, telegram_id: int) -> bool:
        return await self._owner._reply_if_session_expired(update, telegram_id)

    async def _get_or_create_user(self, update):
        return await self._owner._get_or_create_user(update)

    async def _log_user_action(self, user, action: str, details: dict | None = None):
        await self._owner._log_user_action(user, action, details)

    async def _audit_action(self, user, action: str, details: dict | None = None):
        await self._owner._audit_action(user, action, details)

    async def _record_bitget_failure_alert(self, classified_error, source: str, details: dict | None = None):
        await self._owner._record_bitget_failure_alert(classified_error, source, details)

    async def _require_admin(self, update):
        return await self._owner._require_admin(update)

    def _is_admin_user(self, user) -> bool:
        return self._owner._is_admin_user(user)

    async def _is_trader_or_admin(self, telegram_id: int) -> bool:
        return await self._owner._is_trader_or_admin(telegram_id)

    def _get_sender_username(self, update) -> str:
        return self._owner._get_sender_username(update)

    def _order_flow_service(self):
        return self._owner._order_flow_service()

    def _signal_record_service(self):
        return self._owner._signal_record_service()

    def _signal_delivery_service(self):
        return self._owner._signal_delivery_service()

    async def _create_signal_chart(self, signal):
        return await self._owner._create_signal_chart(signal)

    async def _create_signal_update_chart(self, signal, signal_time, granularity: str):
        return await self._owner._create_signal_update_chart(signal, signal_time, granularity)

    async def _get_active_channel_by_number(self, channel_number: int):
        return await self._owner._get_active_channel_by_number(channel_number)

    async def delete_channel_by_number(self, update, context):
        await self._owner.delete_channel_by_number(update, context)
