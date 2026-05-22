from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, or_, select

from ..models import Trade
from ..risk_limits import build_daily_trade_limit_error

RISK_LIMIT_ADVISORY_LOCK_NAMESPACE = 724019


class TradeRepository:
    """交易數據操作"""

    def __init__(self, db_manager):
        self.db = db_manager

    async def create_trade(
        self,
        user_id: int,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None,
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

    async def create_trade_with_daily_limit(
        self,
        user_id: int,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        daily_trade_limit: int,
        day_start_utc: datetime,
        price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
    ) -> Trade:
        """Create a trade after a transaction-scoped per-user daily limit check."""
        async with self.db.get_session() as session:
            await session.execute(select(func.pg_advisory_xact_lock(RISK_LIMIT_ADVISORY_LOCK_NAMESPACE, int(user_id))))
            count_result = await session.execute(
                select(func.count())
                .select_from(Trade)
                .where(
                    Trade.user_id == user_id,
                    Trade.created_at >= day_start_utc,
                    or_(Trade.status.is_(None), Trade.status != "failed"),
                )
            )
            current_count = int(count_result.scalar_one())
            if current_count >= daily_trade_limit:
                raise build_daily_trade_limit_error(
                    current_count=current_count,
                    daily_trade_limit=daily_trade_limit,
                    day_start_utc=day_start_utc,
                )

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
        filled_quantity: Decimal = Decimal("0"),
        avg_price: Optional[Decimal] = None,
        total_amount: Optional[Decimal] = None,
        fee: Decimal = Decimal("0"),
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
                select(Trade).where(Trade.user_id == user_id).order_by(Trade.created_at.desc()).limit(limit)
            )
            return list(result.scalars().all())

    async def get_by_client_order_id(self, client_order_id: str) -> Optional[Trade]:
        """Return one trade by deterministic client order id."""
        async with self.db.get_session() as session:
            result = await session.execute(select(Trade).where(Trade.client_order_id == client_order_id))
            return result.scalar_one_or_none()

    async def count_daily_non_failed_trades(self, user_id: int, day_start_utc: datetime) -> int:
        """Count today's trades that still consume daily risk budget."""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(func.count())
                .select_from(Trade)
                .where(
                    Trade.user_id == user_id,
                    Trade.created_at >= day_start_utc,
                    or_(Trade.status.is_(None), Trade.status != "failed"),
                )
            )
            return int(result.scalar_one())

    async def get_daily_trades_count(self, user_id: int) -> int:
        """獲取用戶今日交易次數"""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.count_daily_non_failed_trades(user_id, today)
