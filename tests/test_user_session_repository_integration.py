import os
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import UserSessionRepository
from app.models import User


class IntegrationDatabaseManager:
    def __init__(self, database_url):
        self.database_url = database_url
        self.engine = create_async_engine(database_url, poolclass=NullPool)
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


async def seed_user(db):
    async with db.get_session() as session:
        user = User(
            telegram_id=123456789 + int(uuid.uuid4().hex[:6], 16),
            username=f"session_{uuid.uuid4().hex[:8]}",
        )
        session.add(user)
        await session.flush()
        return user.id, user.telegram_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_user_session_repository_lifecycle():
    async with integration_database() as db:
        user_id, telegram_id = await seed_user(db)
        repo = UserSessionRepository(db)
        now = datetime.utcnow()

        created = await repo.upsert_session(
            telegram_id=telegram_id,
            user_id=user_id,
            session_type="api_setup",
            token=None,
            payload_encrypted="encrypted-payload",
            payload_version=1,
            expires_at=now + timedelta(minutes=5),
        )

        loaded = await repo.get_session(telegram_id)
        assert loaded == created
        assert await repo.count_active_sessions(now) == 1
        assert await repo.count_expired_sessions(now) == 0

        updated = await repo.upsert_session(
            telegram_id=telegram_id,
            user_id=user_id,
            session_type="signal_preview",
            token="preview-token",
            payload_encrypted="new-encrypted-payload",
            payload_version=1,
            expires_at=now - timedelta(seconds=1),
        )

        assert updated.id == created.id
        assert updated.session_type == "signal_preview"
        assert updated.token == "preview-token"
        assert await repo.count_active_sessions(now) == 0
        assert await repo.count_expired_sessions(now) == 1

        expired = await repo.pop_expired_session(telegram_id, now)

        assert expired == updated
        assert await repo.get_session(telegram_id) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_user_session_repository_bulk_deletes_expired_sessions():
    async with integration_database() as db:
        user_id, telegram_id = await seed_user(db)
        repo = UserSessionRepository(db)
        now = datetime.utcnow()

        await repo.upsert_session(
            telegram_id=telegram_id,
            user_id=user_id,
            session_type="risk_amount",
            token=None,
            payload_encrypted="encrypted-payload",
            payload_version=1,
            expires_at=now - timedelta(seconds=1),
        )

        assert await repo.delete_expired_sessions(now) == 1
        assert await repo.get_session(telegram_id) is None
