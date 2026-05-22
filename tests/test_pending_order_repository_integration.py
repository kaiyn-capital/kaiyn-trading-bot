import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import PendingOrderRepository, TradeRepository
from app.models import Base, PendingOrder, Trade, User
from app.risk_limits import RiskLimitExceeded


class IntegrationDatabaseManager:
    def __init__(self, database_url, schema):
        self.database_url = database_url
        self.schema = schema
        self.engine = create_async_engine(
            database_url,
            poolclass=NullPool,
        )
        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    @asynccontextmanager
    async def get_session(self):
        session = self.SessionLocal()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def close(self):
        await self.engine.dispose()


@asynccontextmanager
async def integration_database():
    database_url = os.environ["TEST_DATABASE_URL"]
    schema = f"test_pending_orders_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(database_url, poolclass=NullPool)
    original_schemas = {table: table.schema for table in Base.metadata.tables.values()}

    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin_engine.dispose()

    for table in Base.metadata.tables.values():
        table.schema = schema

    db = IntegrationDatabaseManager(database_url, schema)
    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield db
    finally:
        await db.close()
        for table, original_schema in original_schemas.items():
            table.schema = original_schema
        cleanup_engine = create_async_engine(database_url, poolclass=NullPool)
        async with cleanup_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await cleanup_engine.dispose()


async def seed_user(db, telegram_id=123456):
    async with db.get_session() as session:
        user = User(
            telegram_id=telegram_id,
            username=f"tester_{uuid.uuid4().hex[:8]}",
            is_api_connected=True,
            encrypted_api_key="api",
            encrypted_secret_key="secret",
            encrypted_passphrase="passphrase",
        )
        session.add(user)
        await session.flush()
        return user.id


async def seed_trade(db, user_id):
    async with db.get_session() as session:
        trade = Trade(
            user_id=user_id,
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            quantity=Decimal("0.01"),
            client_order_id=f"test_{uuid.uuid4().hex}",
            status="filled",
        )
        session.add(trade)
        await session.flush()
        return trade.id


async def seed_trade_with_status(db, user_id, status, created_at):
    async with db.get_session() as session:
        trade = Trade(
            user_id=user_id,
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            quantity=Decimal("0.01"),
            client_order_id=f"test_{uuid.uuid4().hex}",
            status=status,
            created_at=created_at,
        )
        session.add(trade)
        await session.flush()
        return trade.id


async def create_pending(repo, user_id, telegram_id=123456, **overrides):
    data = {
        "user_id": user_id,
        "telegram_id": telegram_id,
        "symbol": "BTCUSDT",
        "direction": "long",
        "order_mode": "market",
        "limit_price": None,
        "entry_lower": Decimal("80000"),
        "entry_upper": Decimal("81000"),
        "quantity": Decimal("0.01"),
        "stop_loss": Decimal("79000"),
        "position_value": Decimal("800"),
        "current_price": Decimal("80000"),
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
    }
    data.update(overrides)
    return await repo.create_pending_order(**data)


async def load_pending(db, token):
    async with db.get_session() as session:
        result = await session.execute(select(PendingOrder).where(PendingOrder.token == token))
        return result.scalar_one()


async def load_trade(db, trade_id):
    async with db.get_session() as session:
        result = await session.execute(select(Trade).where(Trade.id == trade_id))
        return result.scalar_one()


@pytest.mark.integration
def test_create_and_claim_pending_order_lifecycle():
    async def scenario():
        async with integration_database() as db:
            repo = PendingOrderRepository(db)
            user_id = await seed_user(db)

            pending = await create_pending(
                repo,
                user_id,
                order_mode="limit",
                limit_price=Decimal("81000.123456789123456789"),
                entry_lower=Decimal("80200.123456789123456789"),
                entry_upper=Decimal("81000.123456789123456789"),
            )

            assert pending.status == "pending"
            assert pending.symbol == "BTCUSDT"
            assert pending.order_mode == "limit"
            assert pending.limit_price == Decimal("81000.123456789123456789")

            claimed, status = await repo.claim_pending_order(pending.token, 123456)
            assert status == "processing"
            assert claimed.token == pending.token

            saved = await load_pending(db, pending.token)
            assert saved.status == "processing"
            assert saved.limit_price == Decimal("81000.123456789123456789")
            assert saved.entry_lower == Decimal("80200.123456789123456789")
            assert saved.quantity == Decimal("0.010000000000000000")
            assert isinstance(saved.quantity, Decimal)

            claimed_again, status_again = await repo.claim_pending_order(pending.token, 123456)
            assert claimed_again.token == pending.token
            assert status_again == "processing"

    asyncio.run(scenario())


@pytest.mark.integration
def test_claim_missing_and_expired_pending_order():
    async def scenario():
        async with integration_database() as db:
            repo = PendingOrderRepository(db)
            user_id = await seed_user(db)

            missing, missing_status = await repo.claim_pending_order("missing", 123456)
            assert missing is None
            assert missing_status == "missing"

            expired = await create_pending(
                repo,
                user_id,
                expires_at=datetime.utcnow() - timedelta(seconds=1),
            )
            claimed, status = await repo.claim_pending_order(expired.token, 123456)
            assert claimed.token == expired.token
            assert status == "expired"

            saved = await load_pending(db, expired.token)
            assert saved.status == "expired"

    asyncio.run(scenario())


@pytest.mark.integration
def test_cancel_pending_order_lifecycle():
    async def scenario():
        async with integration_database() as db:
            repo = PendingOrderRepository(db)
            user_id = await seed_user(db)

            assert await repo.cancel_pending_order("missing", 123456) == "missing"

            cancellable = await create_pending(repo, user_id)
            assert await repo.cancel_pending_order(cancellable.token, 123456) == "cancelled"
            saved = await load_pending(db, cancellable.token)
            assert saved.status == "cancelled"

            processing = await create_pending(repo, user_id)
            await repo.claim_pending_order(processing.token, 123456)
            assert await repo.cancel_pending_order(processing.token, 123456) == "processing"

            executed = await create_pending(repo, user_id)
            trade_id = await seed_trade(db, user_id)
            assert await repo.mark_executed(executed.token, trade_id) is True
            assert await repo.cancel_pending_order(executed.token, 123456) == "executed"

    asyncio.run(scenario())


@pytest.mark.integration
def test_mark_executed_and_failed_pending_order():
    async def scenario():
        async with integration_database() as db:
            repo = PendingOrderRepository(db)
            user_id = await seed_user(db)

            executed = await create_pending(repo, user_id)
            trade_id = await seed_trade(db, user_id)
            assert await repo.mark_executed(executed.token, trade_id) is True
            saved_executed = await load_pending(db, executed.token)
            assert saved_executed.status == "executed"
            assert saved_executed.trade_id == trade_id

            failed = await create_pending(repo, user_id)
            assert await repo.mark_failed(failed.token, "validation failed") is True
            saved_failed = await load_pending(db, failed.token)
            assert saved_failed.status == "failed"
            assert saved_failed.error_message == "validation failed"

            assert await repo.mark_failed("missing", "no row") is False
            assert await repo.mark_executed("missing", trade_id) is False

    asyncio.run(scenario())


@pytest.mark.integration
def test_trade_repository_daily_non_failed_count_and_limit_create():
    async def scenario():
        async with integration_database() as db:
            repo = TradeRepository(db)
            user_id = await seed_user(db)
            day_start = datetime(2026, 5, 21, 16, 0, 0)

            await seed_trade_with_status(db, user_id, "filled", day_start + timedelta(hours=1))
            await seed_trade_with_status(db, user_id, "pending", day_start + timedelta(hours=2))
            await seed_trade_with_status(db, user_id, "failed", day_start + timedelta(hours=3))
            await seed_trade_with_status(db, user_id, "filled", day_start - timedelta(seconds=1))

            assert await repo.count_daily_non_failed_trades(user_id, day_start) == 2

            trade = await repo.create_trade_with_daily_limit(
                user_id=user_id,
                symbol="ETHUSDT",
                side="buy",
                order_type="market",
                quantity=Decimal("0.1"),
                price=None,
                client_order_id=f"test_{uuid.uuid4().hex}",
                daily_trade_limit=3,
                day_start_utc=day_start,
            )
            assert trade.id
            saved_trade = await load_trade(db, trade.id)
            assert saved_trade.quantity == Decimal("0.100000000000000000")
            assert isinstance(saved_trade.quantity, Decimal)
            assert await repo.count_daily_non_failed_trades(user_id, day_start) == 3

            with pytest.raises(RiskLimitExceeded) as error:
                await repo.create_trade_with_daily_limit(
                    user_id=user_id,
                    symbol="SOLUSDT",
                    side="buy",
                    order_type="market",
                    quantity=Decimal("1"),
                    price=None,
                    client_order_id=f"test_{uuid.uuid4().hex}",
                    daily_trade_limit=3,
                    day_start_utc=day_start,
                )

            assert "今日下单次数已达上限" in str(error.value)

    asyncio.run(scenario())
