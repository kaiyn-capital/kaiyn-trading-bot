from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from ..models import Trade
from ..repository_types import TradeRecord
from ..risk_limits import build_daily_trade_limit_error
from ..time_utils import utc_now_naive

RISK_LIMIT_ADVISORY_LOCK_NAMESPACE = 724019


class TradeRepository:
    """交易數據操作"""

    def __init__(self, db_manager: Any) -> None:
        self.db = db_manager

    async def create_trade(
        self,
        user_id: int,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> TradeRecord:
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
            return trade_record_from_model(trade)

    async def create_trade_with_daily_limit(
        self,
        user_id: int,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        daily_trade_limit: int,
        day_start_utc: datetime,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> TradeRecord:
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
            return trade_record_from_model(trade)

    async def update_trade_result(
        self,
        trade_id: int,
        bitget_order_id: str | None,
        status: str,
        filled_quantity: Decimal = Decimal("0"),
        avg_price: Decimal | None = None,
        total_amount: Decimal | None = None,
        fee: Decimal = Decimal("0"),
        error_message: str | None = None,
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
                trade.executed_at = utc_now_naive()

            return True

    async def get_user_trades(self, user_id: int, limit: int = 50) -> list[TradeRecord]:
        """獲取用戶交易歷史"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(Trade).where(Trade.user_id == user_id).order_by(Trade.created_at.desc()).limit(limit)
            )
            return [trade_record_from_model(trade) for trade in result.scalars().all()]

    async def get_by_client_order_id(self, client_order_id: str) -> TradeRecord | None:
        """Return one trade by deterministic client order id."""
        async with self.db.get_session() as session:
            result = await session.execute(select(Trade).where(Trade.client_order_id == client_order_id))
            trade = result.scalar_one_or_none()
            return trade_record_from_model(trade) if trade else None

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
        today = utc_now_naive().replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.count_daily_non_failed_trades(user_id, today)


def trade_record_from_model(trade: Trade) -> TradeRecord:
    return TradeRecord(
        id=trade.id,
        user_id=trade.user_id,
        symbol=trade.symbol,
        side=trade.side,
        order_type=trade.order_type,
        quantity=trade.quantity,
        price=trade.price,
        bitget_order_id=trade.bitget_order_id,
        client_order_id=trade.client_order_id,
        status=trade.status,
        filled_quantity=trade.filled_quantity,
        avg_price=trade.avg_price,
        total_amount=trade.total_amount,
        fee=trade.fee,
        error_message=trade.error_message,
        created_at=trade.created_at,
        updated_at=trade.updated_at,
        executed_at=trade.executed_at,
    )
