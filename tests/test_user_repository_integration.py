import os
import subprocess
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import UserRepository
from app.models import User


class IntegrationDatabaseManager:
    def __init__(self, database_url):
        self.database_url = database_url
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

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url

    # Run Alembic migrations via subprocess
    subprocess.run(  # noqa: ASYNC221
        ["alembic", "upgrade", "head"],  # noqa: S607
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    db = IntegrationDatabaseManager(database_url)
    try:
        yield db
    finally:
        await db.close()
        subprocess.run(  # noqa: ASYNC221
            ["alembic", "downgrade", "base"],  # noqa: S607
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_active_users_security_filter():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set, skipping integration test")

    async with integration_database() as db:
        # Seed an active user with sensitive credentials
        async with db.get_session() as session:
            user = User(
                telegram_id=123456789,
                username="test_user",
                first_name="Test",
                last_name="User",
                is_active=True,
                is_api_connected=True,
                is_trader=True,
                fixed_risk_amount=Decimal("100.5"),
                encrypted_api_key="sensitive_api_key",
                encrypted_secret_key="sensitive_secret_key",
                encrypted_passphrase="sensitive_passphrase",
            )
            session.add(user)

        user_repo = UserRepository(db)
        active_users = await user_repo.get_active_users()

        assert len(active_users) >= 1
        test_u = next(u for u in active_users if u["telegram_id"] == 123456789)

        # Verify non-sensitive fields are correct
        assert test_u["username"] == "test_user"
        assert test_u["first_name"] == "Test"
        assert test_u["last_name"] == "User"
        assert test_u["is_api_connected"] is True
        assert test_u["is_trader"] is True
        assert test_u["fixed_risk_amount"] == Decimal("100.5")

        # Verify sensitive fields are completely omitted
        assert "encrypted_api_key" not in test_u
        assert "encrypted_secret_key" not in test_u
        assert "encrypted_passphrase" not in test_u
