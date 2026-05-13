from datetime import datetime
from typing import Optional

from sqlalchemy import select

from ..models import SystemLog


class SystemLogRepository:
    """系統日誌操作"""

    def __init__(self, db_manager):
        self.db = db_manager

    async def log(
        self,
        level: str,
        message: str,
        module: str,
        function: Optional[str] = None,
        user_id: Optional[int] = None,
        telegram_id: Optional[int] = None,
        extra_data: Optional[dict] = None,
        stack_trace: Optional[str] = None,
    ) -> SystemLog:
        """創建系統日誌"""
        async with self.db.get_session() as session:
            log_entry = SystemLog(
                level=level,
                message=message,
                module=module,
                function=function,
                user_id=user_id,
                telegram_id=telegram_id,
                stack_trace=stack_trace,
            )

            if extra_data:
                log_entry.set_extra_data(extra_data)

            session.add(log_entry)
            await session.flush()
            return log_entry

    async def get_latest_log(
        self,
        module: Optional[str] = None,
        function: Optional[str] = None,
        levels: Optional[list[str]] = None,
    ) -> Optional[SystemLog]:
        """Return the newest system log matching simple filters."""
        async with self.db.get_session() as session:
            query = select(SystemLog)
            if module:
                query = query.where(SystemLog.module == module)
            if function:
                query = query.where(SystemLog.function == function)
            if levels:
                query = query.where(SystemLog.level.in_(levels))
            query = query.order_by(SystemLog.created_at.desc()).limit(1)
            result = await session.execute(query)
            return result.scalars().first()

    async def get_recent_logs(
        self,
        levels: Optional[list[str]] = None,
        module: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 10,
    ) -> list[SystemLog]:
        """Return recent system logs matching simple filters."""
        async with self.db.get_session() as session:
            query = select(SystemLog)
            if levels:
                query = query.where(SystemLog.level.in_(levels))
            if module:
                query = query.where(SystemLog.module == module)
            if since:
                query = query.where(SystemLog.created_at >= since)
            query = query.order_by(SystemLog.created_at.desc()).limit(limit)
            result = await session.execute(query)
            return list(result.scalars().all())
