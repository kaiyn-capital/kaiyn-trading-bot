from contextlib import asynccontextmanager
from datetime import datetime
import logging
import secrets
from typing import AsyncGenerator, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import Config
from .models import (
    User,
    Trade,
    NotificationLog,
    SystemLog,
    ChannelGroup,
    PendingOrder,
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


class UserRepository:
    """用戶數據操作"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    async def create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> User:
        """創建新用戶"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            existing_user = result.scalar_one_or_none()
            if existing_user:
                return existing_user

            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            session.add(user)
            await session.flush()
            return user

    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """根據 Telegram ID 獲取用戶"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    async def update_user_api_credentials(
        self,
        user_id: int,
        encrypted_api_key: str,
        encrypted_secret_key: str,
        encrypted_passphrase: str,
    ) -> bool:
        """更新用戶 API 憑證"""
        async with self.db.get_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return False

            user.encrypted_api_key = encrypted_api_key
            user.encrypted_secret_key = encrypted_secret_key
            user.encrypted_passphrase = encrypted_passphrase
            user.is_api_connected = True
            return True

    async def update_user_risk_amount(self, user_id: int, risk_amount: float) -> bool:
        """更新用戶風險金額設置"""
        async with self.db.get_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return False

            user.fixed_risk_amount = risk_amount
            return True

    async def set_trader_status(self, telegram_id: int, is_trader: bool = True) -> bool:
        """設置用戶發單員狀態"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                return False

            user.is_trader = is_trader
            return True

    async def is_active_trader(self, telegram_id: int) -> bool:
        """檢查用戶是否為啟用中的發單員"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(User.id).where(
                    User.telegram_id == telegram_id,
                    User.is_trader == True,
                    User.is_active == True,
                )
            )
            return result.scalar_one_or_none() is not None

    async def get_active_users(self) -> list[dict]:
        """獲取所有活躍用戶（返回字典格式避免 Session 問題）"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(User).where(User.is_active == True).order_by(User.created_at)
            )
            users = result.scalars().all()
            return [user_to_dict(user) for user in users]


class TradeRepository:
    """交易數據操作"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    async def create_trade(
        self,
        user_id: int,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Trade:
        """創建新交易記錄"""
        async with self.db.get_session() as session:
            trade = Trade(
                user_id=user_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                client_order_id=client_order_id,
            )
            session.add(trade)
            await session.flush()
            return trade

    async def update_trade_result(
        self,
        trade_id: int,
        bitget_order_id: Optional[str],
        status: str,
        filled_quantity: float = 0,
        avg_price: Optional[float] = None,
        total_amount: Optional[float] = None,
        fee: float = 0,
        error_message: Optional[str] = None,
    ) -> bool:
        """更新交易結果"""
        async with self.db.get_session() as session:
            trade = await session.get(Trade, trade_id)
            if not trade:
                return False

            trade.bitget_order_id = bitget_order_id
            trade.status = status
            trade.filled_quantity = filled_quantity
            trade.avg_price = avg_price
            trade.total_amount = total_amount
            trade.fee = fee
            trade.error_message = error_message

            if status in ["filled", "cancelled", "failed"]:
                trade.executed_at = datetime.utcnow()

            return True

    async def get_user_trades(self, user_id: int, limit: int = 50) -> list[Trade]:
        """獲取用戶交易歷史"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(Trade)
                .where(Trade.user_id == user_id)
                .order_by(Trade.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_daily_trades_count(self, user_id: int) -> int:
        """獲取用戶今日交易次數"""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.db.get_session() as session:
            result = await session.execute(
                select(func.count())
                .select_from(Trade)
                .where(Trade.user_id == user_id, Trade.created_at >= today)
            )
            return int(result.scalar_one())


class PendingOrderRepository:
    """Pending order persistence for restart-safe confirmations."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    async def create_pending_order(
        self,
        user_id: int,
        telegram_id: int,
        symbol: str,
        direction: str,
        quantity: float,
        stop_loss: float,
        position_value: float,
        current_price: float,
        expires_at: datetime,
    ) -> PendingOrder:
        """Create a pending order with a short callback token."""
        async with self.db.get_session() as session:
            for _ in range(5):
                token = secrets.token_urlsafe(8)
                existing = await session.execute(
                    select(PendingOrder.id).where(PendingOrder.token == token)
                )
                if existing.scalar_one_or_none() is None:
                    break
            else:
                raise RuntimeError("Failed to generate unique pending order token")

            pending_order = PendingOrder(
                token=token,
                user_id=user_id,
                telegram_id=telegram_id,
                symbol=symbol,
                direction=direction,
                quantity=quantity,
                stop_loss=stop_loss,
                position_value=position_value,
                current_price=current_price,
                expires_at=expires_at,
            )
            session.add(pending_order)
            await session.flush()
            return pending_order

    async def claim_pending_order(
        self, token: str, telegram_id: int
    ) -> tuple[Optional[PendingOrder], str]:
        """Atomically claim a pending order for execution."""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(PendingOrder)
                .where(
                    PendingOrder.token == token,
                    PendingOrder.telegram_id == telegram_id,
                )
                .with_for_update()
            )
            pending_order = result.scalar_one_or_none()
            if not pending_order:
                return None, "missing"

            if pending_order.status != "pending":
                return pending_order, pending_order.status

            if pending_order.expires_at <= datetime.utcnow():
                pending_order.status = "expired"
                return pending_order, "expired"

            pending_order.status = "processing"
            pending_order.updated_at = datetime.utcnow()
            await session.flush()
            return pending_order, "processing"

    async def mark_executed(self, token: str, trade_id: int) -> bool:
        """Mark a pending order as executed."""
        return await self._update_status(token, "executed", trade_id=trade_id)

    async def mark_failed(self, token: str, error_message: str) -> bool:
        """Mark a pending order as failed."""
        return await self._update_status(token, "failed", error_message=error_message)

    async def cancel_pending_order(self, token: str, telegram_id: int) -> str:
        """Cancel a pending order if it still can be cancelled."""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(PendingOrder)
                .where(
                    PendingOrder.token == token,
                    PendingOrder.telegram_id == telegram_id,
                )
                .with_for_update()
            )
            pending_order = result.scalar_one_or_none()
            if not pending_order:
                return "missing"
            if pending_order.status != "pending":
                return pending_order.status

            pending_order.status = "cancelled"
            pending_order.updated_at = datetime.utcnow()
            return "cancelled"

    async def _update_status(
        self,
        token: str,
        status: str,
        trade_id: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        async with self.db.get_session() as session:
            result = await session.execute(
                select(PendingOrder).where(PendingOrder.token == token)
            )
            pending_order = result.scalar_one_or_none()
            if not pending_order:
                return False

            pending_order.status = status
            pending_order.trade_id = trade_id
            pending_order.error_message = error_message
            pending_order.updated_at = datetime.utcnow()
            return True


class NotificationRepository:
    """通知數據操作"""

    def __init__(self, db_manager: DatabaseManager):
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
            notification = NotificationLog(
                user_id=user_id, message_type=message_type, title=title, message=message
            )

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
                select(NotificationLog)
                .where(NotificationLog.is_sent == False)
                .order_by(NotificationLog.created_at)
            )
            return list(result.scalars().all())


class SystemLogRepository:
    """系統日誌操作"""

    def __init__(self, db_manager: DatabaseManager):
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


class ChannelRepository:
    """頻道數據操作"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    async def create_channel(
        self,
        chat_id: str,
        chat_type: str,
        title: str,
        username: Optional[str],
        added_by_user_id: int,
        description: Optional[str] = None,
    ) -> ChannelGroup:
        """創建頻道記錄"""
        async with self.db.get_session() as session:
            channel = ChannelGroup(
                chat_id=chat_id,
                chat_type=chat_type,
                title=title,
                username=username,
                added_by_user_id=added_by_user_id,
                description=description,
            )
            session.add(channel)
            await session.flush()
            return channel

    async def get_active_channels(self) -> list[dict]:
        """獲取活躍的頻道"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(ChannelGroup)
                .where(ChannelGroup.is_active == True)
                .order_by(ChannelGroup.created_at)
            )
            return [channel_to_dict(channel) for channel in result.scalars().all()]

    async def get_signal_channels(self) -> list[dict]:
        """獲取啟用交易信號轉發的頻道"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(ChannelGroup).where(
                    ChannelGroup.is_active == True,
                    ChannelGroup.auto_forward_signals == True,
                )
            )
            return [channel_to_dict(channel) for channel in result.scalars().all()]

    async def get_channel_by_chat_id(self, chat_id: str) -> Optional[ChannelGroup]:
        """根據聊天ID獲取頻道"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(ChannelGroup).where(ChannelGroup.chat_id == chat_id)
            )
            return result.scalar_one_or_none()

    async def update_channel_settings(
        self, chat_id: str, auto_forward: bool = None, forward_with_buttons: bool = None
    ) -> bool:
        """更新頻道設置"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(ChannelGroup).where(ChannelGroup.chat_id == chat_id)
            )
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
            result = await session.execute(
                select(ChannelGroup).where(ChannelGroup.chat_id == chat_id)
            )
            channel = result.scalar_one_or_none()
            if not channel:
                return False

            channel.is_active = False
            return True

    async def count_active_channels(self) -> int:
        """Count active channels."""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(func.count())
                .select_from(ChannelGroup)
                .where(ChannelGroup.is_active == True)
            )
            return int(result.scalar_one())


def user_to_dict(user: User) -> dict:
    """Convert a user model to a detached dictionary."""
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_api_connected": user.is_api_connected,
        "encrypted_api_key": user.encrypted_api_key,
        "encrypted_secret_key": user.encrypted_secret_key,
        "encrypted_passphrase": user.encrypted_passphrase,
        "daily_trade_limit": user.daily_trade_limit,
        "max_position_size": user.max_position_size,
        "default_stop_loss_percent": user.default_stop_loss_percent,
        "default_trade_amount": user.default_trade_amount,
        "fixed_risk_amount": user.fixed_risk_amount,
        "is_trader": getattr(user, "is_trader", False),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def channel_to_dict(channel: ChannelGroup) -> dict:
    """Convert a channel model to a detached dictionary."""
    return {
        "id": channel.id,
        "chat_id": channel.chat_id,
        "chat_type": channel.chat_type,
        "title": channel.title,
        "username": channel.username,
        "is_active": channel.is_active,
        "auto_forward_signals": channel.auto_forward_signals,
        "forward_with_buttons": channel.forward_with_buttons,
        "added_by_user_id": channel.added_by_user_id,
        "description": channel.description,
        "created_at": channel.created_at,
        "updated_at": channel.updated_at,
    }


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
