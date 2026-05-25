import secrets
import string

from .bot_messages import signal_message
from .decimal_utils import to_decimal
from .order_types import SignalDraft
from .repository_types import SignalRecordSnapshot
from .settings import Settings

SIGNAL_PUBLIC_ID_ALPHABET = string.ascii_lowercase + string.digits
SIGNAL_PUBLIC_ID_LENGTH = 7


class SignalRecordService:
    """Business logic for persistent trading signal records."""

    def __init__(
        self,
        signal_record_repo,
        *,
        is_admin_checker=None,
        public_id_generator=None,
        signal_chart_granularity: str | None = None,
    ):
        self.signal_record_repo = signal_record_repo
        settings = Settings.from_env() if is_admin_checker is None or signal_chart_granularity is None else None
        if is_admin_checker is None:
            is_admin_checker = settings.is_admin
        if signal_chart_granularity is None:
            signal_chart_granularity = settings.signal_chart_granularity

        self.is_admin_checker = is_admin_checker
        self.public_id_generator = public_id_generator or self._generate_signal_public_id
        self.signal_chart_granularity = signal_chart_granularity

    def _generate_signal_public_id(self) -> str:
        return "".join(secrets.choice(SIGNAL_PUBLIC_ID_ALPHABET) for _ in range(SIGNAL_PUBLIC_ID_LENGTH))

    async def create_signal_record(
        self,
        *,
        user,
        signal: SignalDraft,
        sender_username: str,
        chart_status: str,
        chart_error: str | None,
    ) -> tuple[SignalRecordSnapshot, str]:
        for _ in range(10):
            public_id = self.public_id_generator()
            existing = await self.signal_record_repo.get_by_public_id(public_id)
            if existing:
                continue

            signal_text = signal_message(signal, sender_username, public_id)
            record = await self.signal_record_repo.create_signal_record(
                public_id=public_id,
                user_id=getattr(user, "id", None),
                sender_telegram_id=user.telegram_id,
                sender_username=sender_username,
                signal=signal,
                signal_text=signal_text,
                granularity=self.signal_chart_granularity,
                chart_status=chart_status,
                chart_error=chart_error,
            )
            return record, signal_text

        raise RuntimeError("failed to generate unique signal id")

    async def update_status(self, record_id: int, status: str) -> bool:
        return await self.signal_record_repo.update_status(record_id, status)

    async def update_send_status(self, record_id: int, sent_count: int) -> bool:
        status = "sent" if sent_count > 0 else "send_failed"
        return await self.update_status(record_id, status)

    def can_update_signal_record(self, user, record: SignalRecordSnapshot) -> bool:
        return self.is_admin_checker(user.telegram_id) or record.sender_telegram_id == user.telegram_id

    def signal_record_to_draft(self, record: SignalRecordSnapshot) -> SignalDraft:
        return SignalDraft(
            symbol=record.symbol,
            direction=record.direction,
            entry_lower=to_decimal(record.entry_lower),
            entry_upper=to_decimal(record.entry_upper),
            stop_loss=to_decimal(record.stop_loss),
            take_profit_levels=[to_decimal(tp) for tp in record.take_profit_levels],
            remark=record.remark or "",
        )
