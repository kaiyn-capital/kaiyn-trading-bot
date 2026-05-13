from datetime import datetime
from typing import Optional

from sqlalchemy import select

from ..models import NotificationLog


class NotificationRepository:
    """通知數據操作"""

    def __init__(self, db_manager):
        self.db = db_manager

    async def create_notification(
        self,
        user_id: int,
        message_type: str,
        title: str,
        message: str,
        extra_data: Optional[dict] = None,
    ) -> NotificationLog:
        """創建通知記錄"""
        async with self.db.get_session() as session:
            notification = NotificationLog(user_id=user_id, message_type=message_type, title=title, message=message)

            if extra_data:
                notification.set_extra_data(extra_data)

            session.add(notification)
            await session.flush()
            return notification

    async def mark_as_sent(self, notification_id: int, telegram_message_id: int) -> bool:
        """標記通知已發送"""
        async with self.db.get_session() as session:
            notification = await session.get(NotificationLog, notification_id)
            if not notification:
                return False

            notification.is_sent = True
            notification.telegram_message_id = telegram_message_id
            notification.sent_at = datetime.utcnow()
            return True

    async def get_unsent_notifications(self) -> list[NotificationLog]:
        """獲取未發送的通知"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(NotificationLog).where(NotificationLog.is_sent.is_(False)).order_by(NotificationLog.created_at)
            )
            return list(result.scalars().all())
