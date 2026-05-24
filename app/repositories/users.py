from decimal import Decimal

from sqlalchemy import select

from ..decimal_utils import to_decimal
from ..models import User
from ..repository_types import UserAccountRecord, UserSummaryRecord


class UserRepository:
    """用戶數據操作"""

    def __init__(self, db_manager):
        self.db = db_manager

    async def create_user(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> UserAccountRecord:
        """創建新用戶"""
        async with self.db.get_session() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            existing_user = result.scalar_one_or_none()
            if existing_user:
                return user_account_record_from_model(existing_user)

            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            session.add(user)
            await session.flush()
            return user_account_record_from_model(user)

    async def get_user_by_telegram_id(self, telegram_id: int) -> UserAccountRecord | None:
        """根據 Telegram ID 獲取用戶"""
        async with self.db.get_session() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = result.scalar_one_or_none()
            return user_account_record_from_model(user) if user else None

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

    async def update_user_risk_amount(self, user_id: int, risk_amount: Decimal) -> bool:
        """更新用戶風險金額設置"""
        async with self.db.get_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return False

            user.fixed_risk_amount = to_decimal(risk_amount)
            return True

    async def set_trader_status(self, telegram_id: int, is_trader: bool = True) -> bool:
        """設置用戶發單員狀態"""
        async with self.db.get_session() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
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
                    User.is_trader.is_(True),
                    User.is_active.is_(True),
                )
            )
            return result.scalar_one_or_none() is not None

    async def get_active_users(self) -> list[UserSummaryRecord]:
        """獲取所有活躍用戶的概要資訊（不包含加密 API 金鑰等敏感資料）"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(
                    User.id,
                    User.telegram_id,
                    User.username,
                    User.first_name,
                    User.last_name,
                    User.is_api_connected,
                    User.daily_trade_limit,
                    User.max_position_size,
                    User.default_stop_loss_percent,
                    User.default_trade_amount,
                    User.fixed_risk_amount,
                    User.is_trader,
                    User.created_at,
                    User.updated_at,
                )
                .where(User.is_active.is_(True))
                .order_by(User.created_at)
            )
            users = result.all()
            return [
                UserSummaryRecord(
                    id=u.id,
                    telegram_id=u.telegram_id,
                    username=u.username,
                    first_name=u.first_name,
                    last_name=u.last_name,
                    is_api_connected=u.is_api_connected,
                    daily_trade_limit=u.daily_trade_limit,
                    max_position_size=u.max_position_size,
                    default_stop_loss_percent=u.default_stop_loss_percent,
                    default_trade_amount=u.default_trade_amount,
                    fixed_risk_amount=u.fixed_risk_amount,
                    is_trader=u.is_trader,
                    created_at=u.created_at,
                    updated_at=u.updated_at,
                )
                for u in users
            ]


def user_account_record_from_model(user: User) -> UserAccountRecord:
    return UserAccountRecord(
        id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        encrypted_api_key=user.encrypted_api_key,
        encrypted_secret_key=user.encrypted_secret_key,
        encrypted_passphrase=user.encrypted_passphrase,
        is_active=user.is_active,
        is_api_connected=user.is_api_connected,
        daily_trade_limit=user.daily_trade_limit,
        max_position_size=user.max_position_size,
        default_stop_loss_percent=user.default_stop_loss_percent,
        default_trade_amount=user.default_trade_amount,
        fixed_risk_amount=user.fixed_risk_amount,
        is_trader=user.is_trader,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login=user.last_login,
    )
