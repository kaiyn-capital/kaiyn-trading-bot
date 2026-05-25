from datetime import datetime

from sqlalchemy import select

from ..models import SignalChannelMessage, SignalRecord
from ..order_types import SignalDraft
from ..repository_types import SignalChannelMessageRecord, SignalRecordSnapshot


class SignalRecordRepository:
    """Persistence for published trading signals and Telegram message anchors."""

    def __init__(self, db_manager):
        self.db = db_manager

    async def create_signal_record(
        self,
        *,
        public_id: str,
        user_id: int | None,
        sender_telegram_id: int,
        sender_username: str,
        signal: SignalDraft,
        signal_text: str,
        granularity: str,
        chart_status: str,
        chart_error: str | None,
    ) -> SignalRecordSnapshot:
        async with self.db.get_session() as session:
            record = SignalRecord(
                public_id=public_id,
                user_id=user_id,
                sender_telegram_id=sender_telegram_id,
                sender_username=sender_username,
                symbol=signal.symbol,
                direction=signal.direction,
                entry_lower=float(signal.entry_lower),
                entry_upper=float(signal.entry_upper),
                stop_loss=float(signal.stop_loss),
                remark=signal.remark,
                signal_text=signal_text,
                granularity=granularity,
                chart_status=chart_status,
                chart_error=chart_error,
            )
            record.set_take_profit_levels(signal.take_profit_levels)
            session.add(record)
            await session.flush()
            return signal_record_snapshot_from_model(record)

    async def get_by_public_id(self, public_id: str) -> SignalRecordSnapshot | None:
        async with self.db.get_session() as session:
            result = await session.execute(select(SignalRecord).where(SignalRecord.public_id == public_id.lower()))
            record = result.scalar_one_or_none()
            return signal_record_snapshot_from_model(record) if record else None

    async def get_by_id(self, record_id: int) -> SignalRecordSnapshot | None:
        async with self.db.get_session() as session:
            record = await session.get(SignalRecord, record_id)
            return signal_record_snapshot_from_model(record) if record else None

    async def update_status(self, record_id: int, status: str) -> bool:
        async with self.db.get_session() as session:
            record = await session.get(SignalRecord, record_id)
            if not record:
                return False

            record.status = status
            record.updated_at = datetime.utcnow()
            if status == "sent":
                record.confirmed_at = datetime.utcnow()
            return True

    async def add_channel_message(
        self,
        *,
        signal_record_id: int,
        chat_id: str,
        message_thread_id: int | None,
        telegram_message_id: int,
        sent_as: str,
    ) -> SignalChannelMessageRecord:
        async with self.db.get_session() as session:
            message = SignalChannelMessage(
                signal_record_id=signal_record_id,
                chat_id=str(chat_id),
                message_thread_id=message_thread_id,
                telegram_message_id=telegram_message_id,
                sent_as=sent_as,
            )
            session.add(message)
            await session.flush()
            return signal_channel_message_record_from_model(message)

    async def get_channel_messages(self, signal_record_id: int) -> list[SignalChannelMessageRecord]:
        async with self.db.get_session() as session:
            result = await session.execute(
                select(SignalChannelMessage)
                .where(SignalChannelMessage.signal_record_id == signal_record_id)
                .order_by(SignalChannelMessage.created_at)
            )
            return [signal_channel_message_record_from_model(message) for message in result.scalars().all()]


def signal_record_snapshot_from_model(record: SignalRecord) -> SignalRecordSnapshot:
    return SignalRecordSnapshot(
        id=record.id,
        public_id=record.public_id,
        user_id=record.user_id,
        sender_telegram_id=record.sender_telegram_id,
        sender_username=record.sender_username,
        symbol=record.symbol,
        direction=record.direction,
        entry_lower=record.entry_lower,
        entry_upper=record.entry_upper,
        stop_loss=record.stop_loss,
        take_profit_levels=record.get_take_profit_levels(),
        remark=record.remark,
        signal_text=record.signal_text,
        granularity=record.granularity,
        status=record.status,
        chart_status=record.chart_status,
        chart_error=record.chart_error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        confirmed_at=record.confirmed_at,
    )


def signal_channel_message_record_from_model(message: SignalChannelMessage) -> SignalChannelMessageRecord:
    return SignalChannelMessageRecord(
        id=message.id,
        signal_record_id=message.signal_record_id,
        chat_id=message.chat_id,
        message_thread_id=message.message_thread_id,
        telegram_message_id=message.telegram_message_id,
        sent_as=message.sent_as,
        created_at=message.created_at,
    )
