from datetime import datetime

from sqlalchemy import select

from ..models import SystemLog
from ..repository_types import SystemLogRecord


class SystemLogRepository:
    """系統日誌操作"""

    def __init__(self, db_manager):
        self.db = db_manager

    async def log(
        self,
        level: str,
        message: str,
        module: str,
        function: str | None = None,
        user_id: int | None = None,
        telegram_id: int | None = None,
        extra_data: dict | None = None,
        stack_trace: str | None = None,
    ) -> SystemLogRecord:
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
            return system_log_record_from_model(log_entry)

    async def get_latest_log(
        self,
        module: str | None = None,
        function: str | None = None,
        levels: list[str] | None = None,
    ) -> SystemLogRecord | None:
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
            log_entry = result.scalars().first()
            return system_log_record_from_model(log_entry) if log_entry else None

    async def get_recent_logs(
        self,
        levels: list[str] | None = None,
        module: str | None = None,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[SystemLogRecord]:
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
            return [system_log_record_from_model(log_entry) for log_entry in result.scalars().all()]


def system_log_record_from_model(log_entry: SystemLog) -> SystemLogRecord:
    return SystemLogRecord(
        id=log_entry.id,
        level=log_entry.level,
        message=log_entry.message,
        module=log_entry.module,
        function=log_entry.function,
        user_id=log_entry.user_id,
        telegram_id=log_entry.telegram_id,
        extra_data=log_entry.get_extra_data(),
        stack_trace=log_entry.stack_trace,
        created_at=log_entry.created_at,
    )
