import secrets
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select

from ..models import PendingOrder


class PendingOrderRepository:
    """Pending order persistence for restart-safe confirmations."""

    def __init__(self, db_manager):
        self.db = db_manager

    async def create_pending_order(
        self,
        user_id: int,
        telegram_id: int,
        symbol: str,
        direction: str,
        order_mode: str,
        limit_price: Decimal | None,
        entry_lower: Decimal | None,
        entry_upper: Decimal | None,
        quantity: Decimal,
        stop_loss: Decimal,
        position_value: Decimal,
        current_price: Decimal,
        expires_at: datetime,
    ) -> PendingOrder:
        """Create a pending order with a short callback token."""
        async with self.db.get_session() as session:
            for _ in range(5):
                token = secrets.token_urlsafe(8)
                existing = await session.execute(select(PendingOrder.id).where(PendingOrder.token == token))
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
                order_mode=order_mode,
                limit_price=limit_price,
                entry_lower=entry_lower,
                entry_upper=entry_upper,
                quantity=quantity,
                stop_loss=stop_loss,
                position_value=position_value,
                current_price=current_price,
                expires_at=expires_at,
            )
            session.add(pending_order)
            await session.flush()
            return pending_order

    async def claim_pending_order(self, token: str, telegram_id: int) -> tuple[PendingOrder | None, str]:
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

    async def get_stale_processing_orders(self, cutoff: datetime, limit: int) -> list[PendingOrder]:
        """Return processing orders that have not changed since cutoff."""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(PendingOrder)
                .where(
                    PendingOrder.status == "processing",
                    PendingOrder.updated_at <= cutoff,
                )
                .order_by(PendingOrder.updated_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def count_stale_processing_orders(self, cutoff: datetime) -> int:
        """Count processing orders that have not changed since cutoff."""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(func.count())
                .select_from(PendingOrder)
                .where(
                    PendingOrder.status == "processing",
                    PendingOrder.updated_at <= cutoff,
                )
            )
            return int(result.scalar_one())

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
        trade_id: int | None = None,
        error_message: str | None = None,
    ) -> bool:
        async with self.db.get_session() as session:
            result = await session.execute(select(PendingOrder).where(PendingOrder.token == token))
            pending_order = result.scalar_one_or_none()
            if not pending_order:
                return False

            pending_order.status = status
            pending_order.trade_id = trade_id
            pending_order.error_message = error_message
            pending_order.updated_at = datetime.utcnow()
            return True
