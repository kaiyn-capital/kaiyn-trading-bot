from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import logging
from typing import AsyncGenerator

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import Config
from .models import NotificationLog, PendingOrder, SystemLog, Trade
from .repositories import (
    ChannelRepository,
    NotificationRepository,
    PendingOrderRepository,
    SystemLogRepository,
    TradeRepository,
    UserRepository,
    channel_to_dict,
    user_to_dict,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """PostgreSQL async database manager."""

    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("Missing DATABASE_URL")
        if not database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg://")

        self.database_url = database_url
        self.engine = create_async_engine(
            database_url,
            echo=Config.DEBUG,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield a transactional async database session."""
        session = self.SessionLocal()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            async with self.get_session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    async def close(self):
        """Dispose the database engine."""
        await self.engine.dispose()


async def cleanup_retention_records(retention_days: int, dry_run: bool = False) -> dict:
    """Delete retention-managed records older than the configured window."""
    if retention_days <= 0:
        raise ValueError("retention_days must be greater than 0")

    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    cleanup_targets = [
        ("pending_orders", PendingOrder),
        ("trades", Trade),
        ("notification_logs", NotificationLog),
        ("system_logs", SystemLog),
    ]

    result = {
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "dry_run": dry_run,
        "tables": {},
    }

    async with get_db_manager().get_session() as session:
        for table_name, model in cleanup_targets:
            count_result = await session.execute(
                select(func.count()).select_from(model).where(model.created_at < cutoff)
            )
            count = int(count_result.scalar_one())
            result["tables"][table_name] = count

            if count and not dry_run:
                await session.execute(delete(model).where(model.created_at < cutoff))

    return result


# 全局資料庫實例
db_manager = None
user_repo = None
trade_repo = None
pending_order_repo = None
notification_repo = None
system_log_repo = None
channel_repo = None


def init_database(database_url: str = None):
    """初始化資料庫連線物件，不建立資料表。"""
    global db_manager, user_repo, trade_repo, pending_order_repo
    global notification_repo, system_log_repo, channel_repo

    if database_url is None:
        database_url = Config.DATABASE_URL

    if db_manager is not None and db_manager.database_url == database_url:
        return

    db_manager = DatabaseManager(database_url)
    user_repo = UserRepository(db_manager)
    trade_repo = TradeRepository(db_manager)
    pending_order_repo = PendingOrderRepository(db_manager)
    notification_repo = NotificationRepository(db_manager)
    system_log_repo = SystemLogRepository(db_manager)
    channel_repo = ChannelRepository(db_manager)

    logger.info("Database manager initialized successfully")


def get_db_manager() -> DatabaseManager:
    """獲取資料庫管理器"""
    if db_manager is None:
        init_database()
    return db_manager


def get_user_repo() -> UserRepository:
    """獲取用戶倉庫"""
    if user_repo is None:
        init_database()
    return user_repo


def get_trade_repo() -> TradeRepository:
    """獲取交易倉庫"""
    if trade_repo is None:
        init_database()
    return trade_repo


def get_pending_order_repo() -> PendingOrderRepository:
    """獲取待確認訂單倉庫"""
    if pending_order_repo is None:
        init_database()
    return pending_order_repo


def get_notification_repo() -> NotificationRepository:
    """獲取通知倉庫"""
    if notification_repo is None:
        init_database()
    return notification_repo


def get_system_log_repo() -> SystemLogRepository:
    """獲取系統日誌倉庫"""
    if system_log_repo is None:
        init_database()
    return system_log_repo


def get_channel_repo() -> ChannelRepository:
    """獲取頻道倉庫"""
    if channel_repo is None:
        init_database()
    return channel_repo


async def health_check() -> bool:
    """資料庫健康檢查"""
    try:
        manager = get_db_manager()
        return await manager.health_check()
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
