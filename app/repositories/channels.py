from sqlalchemy import func, select

from ..models import ChannelGroup
from ..repository_types import ChannelRecord
from ..time_utils import utc_now_naive


class ChannelRepository:
    """頻道數據操作"""

    def __init__(self, db_manager):
        self.db = db_manager

    async def create_channel(
        self,
        chat_id: str,
        chat_type: str,
        title: str,
        username: str | None,
        added_by_user_id: int,
        description: str | None = None,
        message_thread_id: int | None = None,
        thread_title: str | None = None,
    ) -> ChannelRecord:
        """創建頻道記錄"""
        async with self.db.get_session() as session:
            channel = ChannelGroup(
                chat_id=chat_id,
                chat_type=chat_type,
                title=title,
                username=username,
                added_by_user_id=added_by_user_id,
                description=description,
                message_thread_id=message_thread_id,
                thread_title=thread_title,
            )
            session.add(channel)
            await session.flush()
            return channel_record_from_model(channel)

    async def get_active_channels(self) -> list[ChannelRecord]:
        """獲取活躍的頻道"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(ChannelGroup).where(ChannelGroup.is_active.is_(True)).order_by(ChannelGroup.created_at)
            )
            return [channel_record_from_model(channel) for channel in result.scalars().all()]

    async def get_signal_channels(self) -> list[ChannelRecord]:
        """獲取啟用交易信號轉發的頻道"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(ChannelGroup).where(
                    ChannelGroup.is_active.is_(True),
                    ChannelGroup.auto_forward_signals.is_(True),
                )
            )
            return [channel_record_from_model(channel) for channel in result.scalars().all()]

    async def get_channel_by_chat_id(self, chat_id: str) -> ChannelRecord | None:
        """根據聊天ID獲取頻道"""
        async with self.db.get_session() as session:
            result = await session.execute(select(ChannelGroup).where(ChannelGroup.chat_id == chat_id))
            channel = result.scalar_one_or_none()
            return channel_record_from_model(channel) if channel else None

    async def update_channel_settings(
        self, chat_id: str, auto_forward: bool = None, forward_with_buttons: bool = None
    ) -> bool:
        """更新頻道設置"""
        async with self.db.get_session() as session:
            result = await session.execute(select(ChannelGroup).where(ChannelGroup.chat_id == chat_id))
            channel = result.scalar_one_or_none()
            if not channel:
                return False

            if auto_forward is not None:
                channel.auto_forward_signals = auto_forward
            if forward_with_buttons is not None:
                channel.forward_with_buttons = forward_with_buttons

            return True

    async def deactivate_channel(self, chat_id: str) -> bool:
        """Soft-delete a channel."""
        async with self.db.get_session() as session:
            result = await session.execute(select(ChannelGroup).where(ChannelGroup.chat_id == chat_id))
            channel = result.scalar_one_or_none()
            if not channel:
                return False

            channel.is_active = False
            channel.updated_at = utc_now_naive()
            return True

    async def reactivate_channel(
        self,
        chat_id: str,
        chat_type: str,
        title: str,
        username: str | None,
        added_by_user_id: int,
        description: str | None = None,
        message_thread_id: int | None = None,
        thread_title: str | None = None,
    ) -> bool:
        """Reactivate a soft-deleted channel and refresh its metadata."""
        async with self.db.get_session() as session:
            result = await session.execute(select(ChannelGroup).where(ChannelGroup.chat_id == chat_id))
            channel = result.scalar_one_or_none()
            if not channel:
                return False

            channel.chat_type = chat_type
            channel.title = title
            channel.username = username
            channel.added_by_user_id = added_by_user_id
            channel.description = description
            channel.message_thread_id = message_thread_id
            channel.thread_title = thread_title
            channel.is_active = True
            channel.auto_forward_signals = True
            channel.forward_with_buttons = True
            channel.updated_at = utc_now_naive()
            return True

    async def update_channel_topic(self, chat_id: str, message_thread_id: int, thread_title: str | None = None) -> bool:
        """Set the default Telegram topic for signal forwarding."""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(ChannelGroup).where(
                    ChannelGroup.chat_id == chat_id,
                    ChannelGroup.is_active.is_(True),
                )
            )
            channel = result.scalar_one_or_none()
            if not channel:
                return False

            channel.message_thread_id = message_thread_id
            channel.thread_title = thread_title
            channel.updated_at = utc_now_naive()
            return True

    async def clear_channel_topic(self, chat_id: str) -> bool:
        """Clear the default Telegram topic for signal forwarding."""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(ChannelGroup).where(
                    ChannelGroup.chat_id == chat_id,
                    ChannelGroup.is_active.is_(True),
                )
            )
            channel = result.scalar_one_or_none()
            if not channel:
                return False

            channel.message_thread_id = None
            channel.thread_title = None
            channel.updated_at = utc_now_naive()
            return True

    async def count_active_channels(self) -> int:
        """Count active channels."""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(func.count()).select_from(ChannelGroup).where(ChannelGroup.is_active.is_(True))
            )
            return int(result.scalar_one())


def channel_record_from_model(channel: ChannelGroup) -> ChannelRecord:
    """Convert a channel model to a detached record."""
    return ChannelRecord(
        id=channel.id,
        chat_id=channel.chat_id,
        chat_type=channel.chat_type,
        title=channel.title,
        username=channel.username,
        is_active=channel.is_active,
        auto_forward_signals=channel.auto_forward_signals,
        forward_with_buttons=channel.forward_with_buttons,
        message_thread_id=channel.message_thread_id,
        thread_title=channel.thread_title,
        added_by_user_id=channel.added_by_user_id,
        description=channel.description,
        created_at=channel.created_at,
        updated_at=channel.updated_at,
    )
