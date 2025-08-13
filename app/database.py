from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from contextlib import contextmanager, asynccontextmanager
from typing import Generator, Optional, AsyncGenerator
from datetime import datetime
import logging

from .models import (
    Base,
    User,
    Trade,
    NotificationLog,
    TradingPair,
    SystemLog,
    ChannelGroup,
)
from .config import Config

logger = logging.getLogger(__name__)


class DatabaseManager:
    """資料庫管理器"""

    def __init__(self, database_url: str):
        self.database_url = database_url

        # 同步引擎
        self.engine = create_engine(
            database_url, echo=Config.DEBUG, pool_pre_ping=True, pool_recycle=3600
        )

        # 同步會話工廠
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        # 異步引擎（如果需要）
        if database_url.startswith("postgresql"):
            async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
            self.async_engine = create_async_engine(
                async_url, echo=Config.DEBUG, pool_pre_ping=True, pool_recycle=3600
            )
            self.AsyncSessionLocal = async_sessionmaker(
                autocommit=False, autoflush=False, bind=self.async_engine
            )
        else:
            self.async_engine = None
            self.AsyncSessionLocal = None

    def create_tables(self):
        """創建所有表"""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise

    def drop_tables(self):
        """刪除所有表"""
        try:
            Base.metadata.drop_all(bind=self.engine)
            logger.info("Database tables dropped successfully")
        except Exception as e:
            logger.error(f"Failed to drop tables: {e}")
            raise

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """獲取資料庫會話"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            session.close()

    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """獲取異步資料庫會話"""
        if not self.AsyncSessionLocal:
            raise RuntimeError("Async session not available for this database type")

        session = self.AsyncSessionLocal()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Async database session error: {e}")
            raise
        finally:
            await session.close()

    def health_check(self) -> bool:
        """資料庫健康檢查"""
        try:
            with self.get_session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False


class UserRepository:
    """用戶數據操作"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> User:
        """創建新用戶"""
        with self.db.get_session() as session:
            # 檢查用戶是否已存在
            existing_user = (
                session.query(User).filter(User.telegram_id == telegram_id).first()
            )
            if existing_user:
                # 刷新對象以確保 Session 綁定
                session.refresh(existing_user)
                # 創建分離的用戶對象
                detached_user = User()
                detached_user.id = existing_user.id
                detached_user.telegram_id = existing_user.telegram_id
                detached_user.username = existing_user.username
                detached_user.first_name = existing_user.first_name
                detached_user.last_name = existing_user.last_name
                detached_user.encrypted_api_key = existing_user.encrypted_api_key
                detached_user.encrypted_secret_key = existing_user.encrypted_secret_key
                detached_user.encrypted_passphrase = existing_user.encrypted_passphrase
                detached_user.is_active = existing_user.is_active
                detached_user.is_api_connected = existing_user.is_api_connected
                detached_user.daily_trade_limit = existing_user.daily_trade_limit
                detached_user.max_position_size = existing_user.max_position_size
                detached_user.enable_notifications = existing_user.enable_notifications
                detached_user.default_stop_loss_percent = (
                    existing_user.default_stop_loss_percent
                )
                detached_user.default_trade_amount = existing_user.default_trade_amount
                detached_user.auto_stop_loss = existing_user.auto_stop_loss
                detached_user.fixed_risk_amount = existing_user.fixed_risk_amount
                detached_user.is_trader = getattr(existing_user, "is_trader", False)
                detached_user.created_at = existing_user.created_at
                detached_user.updated_at = existing_user.updated_at
                detached_user.last_login = existing_user.last_login
                return detached_user

            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            session.add(user)
            session.commit()
            session.refresh(user)

            # 創建分離的用戶對象返回
            detached_user = User()
            detached_user.id = user.id
            detached_user.telegram_id = user.telegram_id
            detached_user.username = user.username
            detached_user.first_name = user.first_name
            detached_user.last_name = user.last_name
            detached_user.encrypted_api_key = user.encrypted_api_key
            detached_user.encrypted_secret_key = user.encrypted_secret_key
            detached_user.encrypted_passphrase = user.encrypted_passphrase
            detached_user.is_active = user.is_active
            detached_user.is_api_connected = user.is_api_connected
            detached_user.daily_trade_limit = user.daily_trade_limit
            detached_user.max_position_size = user.max_position_size
            detached_user.enable_notifications = user.enable_notifications
            detached_user.default_stop_loss_percent = user.default_stop_loss_percent
            detached_user.default_trade_amount = user.default_trade_amount
            detached_user.auto_stop_loss = user.auto_stop_loss
            detached_user.fixed_risk_amount = user.fixed_risk_amount
            detached_user.is_trader = getattr(user, "is_trader", False)
            detached_user.created_at = user.created_at
            detached_user.updated_at = user.updated_at
            detached_user.last_login = user.last_login
            return detached_user

    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """根據 Telegram ID 獲取用戶"""
        with self.db.get_session() as session:
            user = session.query(User).filter(User.telegram_id == telegram_id).first()
            if user:
                # 創建一個新的 User 對象以避免 Session 綁定問題
                detached_user = User()
                detached_user.id = user.id
                detached_user.telegram_id = user.telegram_id
                detached_user.username = user.username
                detached_user.first_name = user.first_name
                detached_user.last_name = user.last_name
                detached_user.encrypted_api_key = user.encrypted_api_key
                detached_user.encrypted_secret_key = user.encrypted_secret_key
                detached_user.encrypted_passphrase = user.encrypted_passphrase
                detached_user.is_active = user.is_active
                detached_user.is_api_connected = user.is_api_connected
                detached_user.daily_trade_limit = user.daily_trade_limit
                detached_user.max_position_size = user.max_position_size
                detached_user.enable_notifications = user.enable_notifications
                detached_user.default_stop_loss_percent = user.default_stop_loss_percent
                detached_user.default_trade_amount = user.default_trade_amount
                detached_user.auto_stop_loss = user.auto_stop_loss
                detached_user.fixed_risk_amount = user.fixed_risk_amount
                detached_user.is_trader = getattr(user, "is_trader", False)
                detached_user.created_at = user.created_at
                detached_user.updated_at = user.updated_at
                detached_user.last_login = user.last_login
                return detached_user
            return None

    def update_user_api_credentials(
        self,
        user_id: int,
        encrypted_api_key: str,
        encrypted_secret_key: str,
        encrypted_passphrase: str,
    ) -> bool:
        """更新用戶 API 憑證"""
        with self.db.get_session() as session:
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
                return False

            user.encrypted_api_key = encrypted_api_key
            user.encrypted_secret_key = encrypted_secret_key
            user.encrypted_passphrase = encrypted_passphrase
            user.is_api_connected = True
            session.commit()
            return True

    def update_user_risk_amount(self, user_id: int, risk_amount: float) -> bool:
        """更新用戶風險金額設置"""
        with self.db.get_session() as session:
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
                return False

            user.fixed_risk_amount = risk_amount
            session.commit()
            return True

    def set_trader_status(self, telegram_id: int, is_trader: bool = True) -> bool:
        """設置用戶發單員狀態"""
        with self.db.get_session() as session:
            user = session.query(User).filter(User.telegram_id == telegram_id).first()
            if not user:
                return False

            user.is_trader = is_trader
            session.commit()
            return True

    def get_active_users(self) -> list[dict]:
        """獲取所有活躍用戶（返回字典格式避免 Session 問題）"""
        with self.db.get_session() as session:
            users = session.query(User).filter(User.is_active == True).all()
            # 轉換為字典格式
            user_dicts = []
            for user in users:
                user_dict = {
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
                user_dicts.append(user_dict)
            return user_dicts


class TradeRepository:
    """交易數據操作"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def create_trade(
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
        with self.db.get_session() as session:
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
            session.commit()
            session.refresh(trade)

            # 創建分離的對象以避免會話綁定問題
            detached_trade = Trade()
            detached_trade.id = trade.id
            detached_trade.user_id = trade.user_id
            detached_trade.symbol = trade.symbol
            detached_trade.side = trade.side
            detached_trade.order_type = trade.order_type
            detached_trade.quantity = trade.quantity
            detached_trade.price = trade.price
            detached_trade.client_order_id = trade.client_order_id
            detached_trade.status = trade.status
            detached_trade.created_at = trade.created_at

            return detached_trade

    def update_trade_result(
        self,
        trade_id: int,
        bitget_order_id: str,
        status: str,
        filled_quantity: float = 0,
        avg_price: Optional[float] = None,
        total_amount: Optional[float] = None,
        fee: float = 0,
        error_message: Optional[str] = None,
    ) -> bool:
        """更新交易結果"""
        with self.db.get_session() as session:
            trade = session.query(Trade).filter(Trade.id == trade_id).first()
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

            session.commit()
            return True

    def get_user_trades(self, user_id: int, limit: int = 50) -> list[Trade]:
        """獲取用戶交易歷史"""
        with self.db.get_session() as session:
            return (
                session.query(Trade)
                .filter(Trade.user_id == user_id)
                .order_by(Trade.created_at.desc())
                .limit(limit)
                .all()
            )

    def get_daily_trades_count(self, user_id: int) -> int:
        """獲取用戶今日交易次數"""
        from datetime import datetime, timedelta

        today = datetime.utcnow().date()

        with self.db.get_session() as session:
            return (
                session.query(Trade)
                .filter(Trade.user_id == user_id)
                .filter(Trade.created_at >= today)
                .count()
            )


class NotificationRepository:
    """通知數據操作"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def create_notification(
        self,
        user_id: int,
        message_type: str,
        title: str,
        message: str,
        extra_data: Optional[dict] = None,
    ) -> NotificationLog:
        """創建通知記錄"""
        with self.db.get_session() as session:
            notification = NotificationLog(
                user_id=user_id, message_type=message_type, title=title, message=message
            )

            if extra_data:
                notification.set_extra_data(extra_data)

            session.add(notification)
            session.commit()
            session.refresh(notification)
            return notification

    def mark_as_sent(self, notification_id: int, telegram_message_id: int) -> bool:
        """標記通知已發送"""
        with self.db.get_session() as session:
            notification = (
                session.query(NotificationLog)
                .filter(NotificationLog.id == notification_id)
                .first()
            )
            if not notification:
                return False

            notification.is_sent = True
            notification.telegram_message_id = telegram_message_id
            notification.sent_at = datetime.utcnow()
            session.commit()
            return True

    def get_unsent_notifications(self) -> list[NotificationLog]:
        """獲取未發送的通知"""
        with self.db.get_session() as session:
            return (
                session.query(NotificationLog)
                .filter(NotificationLog.is_sent == False)
                .order_by(NotificationLog.created_at)
                .all()
            )


class SystemLogRepository:
    """系統日誌操作"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def log(
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
        with self.db.get_session() as session:
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
            session.commit()
            session.refresh(log_entry)
            return log_entry


class ChannelRepository:
    """頻道數據操作"""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def create_channel(
        self,
        chat_id: str,
        chat_type: str,
        title: str,
        username: Optional[str],
        added_by_user_id: int,
        description: Optional[str] = None,
    ) -> ChannelGroup:
        """創建頻道記錄"""
        with self.db.get_session() as session:
            channel = ChannelGroup(
                chat_id=chat_id,
                chat_type=chat_type,
                title=title,
                username=username,
                added_by_user_id=added_by_user_id,
                description=description,
            )
            session.add(channel)
            session.commit()
            session.refresh(channel)
            return channel

    def get_active_channels(self) -> list[ChannelGroup]:
        """獲取活躍的頻道"""
        with self.db.get_session() as session:
            return (
                session.query(ChannelGroup).filter(ChannelGroup.is_active == True).all()
            )

    def get_channel_by_chat_id(self, chat_id: str) -> Optional[ChannelGroup]:
        """根據聊天ID獲取頻道"""
        with self.db.get_session() as session:
            return (
                session.query(ChannelGroup)
                .filter(ChannelGroup.chat_id == chat_id)
                .first()
            )

    def update_channel_settings(
        self, chat_id: str, auto_forward: bool = None, forward_with_buttons: bool = None
    ) -> bool:
        """更新頻道設置"""
        with self.db.get_session() as session:
            channel = (
                session.query(ChannelGroup)
                .filter(ChannelGroup.chat_id == chat_id)
                .first()
            )
            if not channel:
                return False

            if auto_forward is not None:
                channel.auto_forward_signals = auto_forward
            if forward_with_buttons is not None:
                channel.forward_with_buttons = forward_with_buttons

            session.commit()
            return True


# 全局資料庫實例
db_manager = None
user_repo = None
trade_repo = None
notification_repo = None
system_log_repo = None
channel_repo = None


def init_database(database_url: str = None):
    """初始化資料庫"""
    global db_manager, user_repo, trade_repo, notification_repo, system_log_repo, channel_repo

    if database_url is None:
        database_url = Config.DATABASE_URL

    db_manager = DatabaseManager(database_url)
    user_repo = UserRepository(db_manager)
    trade_repo = TradeRepository(db_manager)
    notification_repo = NotificationRepository(db_manager)
    system_log_repo = SystemLogRepository(db_manager)
    channel_repo = ChannelRepository(db_manager)

    # 創建表
    db_manager.create_tables()

    logger.info("Database initialized successfully")


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


# 便捷函數
def create_tables():
    """創建資料庫表"""
    manager = get_db_manager()
    manager.create_tables()


def health_check() -> bool:
    """資料庫健康檢查"""
    try:
        manager = get_db_manager()
        return manager.health_check()
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
