import logging

import pytest

from app.database import DatabaseManager


class FakeSession:
    def __init__(
        self,
        *,
        commit_error: Exception | None = None,
        rollback_error: Exception | None = None,
        close_error: Exception | None = None,
    ):
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.committed = False
        self.rolled_back = False
        self.closed = False

    async def commit(self):
        self.committed = True
        if self.commit_error:
            raise self.commit_error

    async def rollback(self):
        self.rolled_back = True
        if self.rollback_error:
            raise self.rollback_error

    async def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def make_database_manager(session: FakeSession) -> DatabaseManager:
    manager = object.__new__(DatabaseManager)
    manager.SessionLocal = lambda: session
    return manager


@pytest.mark.asyncio
async def test_get_session_preserves_caller_error_when_cleanup_fails(caplog):
    caller_error = ValueError("caller failed")
    session = FakeSession(
        rollback_error=RuntimeError("rollback failed"),
        close_error=RuntimeError("close failed"),
    )
    manager = make_database_manager(session)

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError) as exc_info:
        async with manager.get_session():
            raise caller_error

    assert exc_info.value is caller_error
    assert session.rolled_back is True
    assert session.closed is True
    assert "Database session rollback failed while handling ValueError" in caplog.text
    assert "Database session close failed while handling ValueError" in caplog.text


@pytest.mark.asyncio
async def test_get_session_preserves_commit_error_when_rollback_fails():
    commit_error = RuntimeError("commit failed")
    session = FakeSession(
        commit_error=commit_error,
        rollback_error=RuntimeError("rollback failed"),
    )
    manager = make_database_manager(session)

    with pytest.raises(RuntimeError) as exc_info:
        async with manager.get_session():
            pass

    assert exc_info.value is commit_error
    assert session.committed is True
    assert session.rolled_back is True
    assert session.closed is True


@pytest.mark.asyncio
async def test_get_session_propagates_close_error_after_success():
    close_error = RuntimeError("close failed")
    session = FakeSession(close_error=close_error)
    manager = make_database_manager(session)

    with pytest.raises(RuntimeError) as exc_info:
        async with manager.get_session():
            pass

    assert exc_info.value is close_error
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True
