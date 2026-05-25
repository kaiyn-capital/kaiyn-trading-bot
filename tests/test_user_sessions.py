from datetime import datetime, timedelta

import pytest

from app.bot_sessions import UserSessionMixin
from app.encryption import EncryptionManager, KeyGenerator
from app.repository_types import UserSessionRecord
from app.session_store import DatabaseSessionStore
from app.session_types import (
    MAX_SESSION_CHART_BYTES,
    ApiSetupSession,
    SignalPreviewSession,
    session_payload_from_json_data,
    session_payload_to_json_data,
)


class FakePersistentSessionRepo:
    def __init__(self):
        self.records = {}
        self.next_id = 1

    async def upsert_session(
        self,
        *,
        telegram_id,
        session_type,
        payload_encrypted,
        payload_version,
        expires_at,
        user_id=None,
        token=None,
    ):
        existing = self.records.get(telegram_id)
        record = UserSessionRecord(
            id=existing.id if existing else self.next_id,
            telegram_id=telegram_id,
            user_id=user_id,
            session_type=session_type,
            token=token,
            payload_encrypted=payload_encrypted,
            payload_version=payload_version,
            expires_at=expires_at,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        if telegram_id not in self.records:
            self.next_id += 1
        self.records[telegram_id] = record
        return record

    async def get_session(self, telegram_id):
        return self.records.get(telegram_id)

    async def delete_session(self, telegram_id):
        self.records.pop(telegram_id, None)

    async def pop_expired_session(self, telegram_id, now):
        record = self.records.get(telegram_id)
        if not record or record.expires_at > now:
            return None
        return self.records.pop(telegram_id)

    async def delete_expired_sessions(self, now):
        expired = [telegram_id for telegram_id, record in self.records.items() if record.expires_at <= now]
        for telegram_id in expired:
            self.records.pop(telegram_id, None)
        return len(expired)


class FakeSessionOwner(UserSessionMixin):
    def __init__(self):
        self.user_sessions = {}
        self.now = datetime(2026, 5, 18, 12, 0, 0)

    def _session_now(self):
        return self.now


@pytest.mark.asyncio
async def test_set_user_session_adds_expiry():
    owner = FakeSessionOwner()

    session = await owner.set_user_session(123, {"step": "risk_amount"})

    assert session["step"] == "risk_amount"
    assert session["expires_at"] == owner.now + timedelta(seconds=300)
    assert owner.user_sessions[123] == session


@pytest.mark.asyncio
async def test_get_active_user_session_returns_unexpired_session():
    owner = FakeSessionOwner()
    await owner.set_user_session(123, {"step": "risk_amount"})

    owner.now = owner.now + timedelta(seconds=299)

    session = await owner.get_active_user_session(123)
    assert session["step"] == "risk_amount"
    assert 123 in owner.user_sessions


@pytest.mark.asyncio
async def test_expire_user_session_if_needed_clears_expired_session_once():
    owner = FakeSessionOwner()
    await owner.set_user_session(123, {"step": "risk_amount"})
    owner.now = owner.now + timedelta(seconds=301)

    assert await owner.expire_user_session_if_needed(123) is True
    assert owner.user_sessions == {}
    assert await owner.expire_user_session_if_needed(123) is False


@pytest.mark.asyncio
async def test_pop_expired_user_session_returns_removed_session():
    owner = FakeSessionOwner()
    await owner.set_user_session(123, {"step": "risk_amount"})
    owner.now = owner.now + timedelta(seconds=301)

    expired = await owner.pop_expired_user_session(123)

    assert expired["step"] == "risk_amount"
    assert owner.user_sessions == {}
    assert await owner.pop_expired_user_session(123) is None


@pytest.mark.asyncio
async def test_delete_user_session_is_idempotent():
    owner = FakeSessionOwner()
    await owner.set_user_session(123, {"step": "risk_amount"})

    await owner.delete_user_session(123)
    await owner.delete_user_session(123)

    assert owner.user_sessions == {}


@pytest.mark.asyncio
async def test_peek_user_session_does_not_apply_expiry_side_effects():
    owner = FakeSessionOwner()
    await owner.set_user_session(123, {"step": "risk_amount"})
    owner.now = owner.now + timedelta(seconds=301)

    session = await owner.peek_user_session(123)

    assert session["step"] == "risk_amount"
    assert 123 in owner.user_sessions


@pytest.mark.asyncio
async def test_update_user_session_refreshes_expiry_and_preserves_data():
    owner = FakeSessionOwner()
    await owner.set_user_session(123, {"step": "api_key", "api_key": "old"})
    original_expiry = owner.user_sessions[123]["expires_at"]

    owner.now = owner.now + timedelta(seconds=60)
    session = await owner.update_user_session(123, {"step": "secret_key", "api_key": "old"})

    assert session["api_key"] == "old"
    assert session["step"] == "secret_key"
    assert session["expires_at"] > original_expiry


@pytest.mark.asyncio
async def test_set_user_session_overwrites_existing_session_for_same_user():
    owner = FakeSessionOwner()
    await owner.set_user_session(123, {"step": "api_key", "api_key": "old"})

    session = await owner.set_user_session(123, {"step": "risk_amount"})

    assert session["step"] == "risk_amount"
    assert "api_key" not in session
    assert len(owner.user_sessions) == 1


def test_signal_preview_session_json_round_trip_preserves_chart_bytes():
    payload = SignalPreviewSession(
        token="tok",
        signal_record_id=7,
        signal_public_id="sig123",
        chart_status="generated",
        chart_error=None,
        chart_bytes=b"fake-png",
    )

    data = session_payload_to_json_data(payload)
    restored = session_payload_from_json_data("signal_preview", data)

    assert data["chart_bytes"] != "fake-png"
    assert isinstance(restored, SignalPreviewSession)
    assert restored.chart_bytes == b"fake-png"
    assert restored.signal_record_id == 7


def test_signal_preview_session_rejects_oversized_chart_payload():
    payload = SignalPreviewSession(
        token="tok",
        signal_record_id=7,
        signal_public_id="sig123",
        chart_status="generated",
        chart_bytes=b"x" * (MAX_SESSION_CHART_BYTES + 1),
    )

    with pytest.raises(ValueError, match="too large"):
        session_payload_to_json_data(payload)


@pytest.mark.asyncio
async def test_database_session_store_encrypts_and_round_trips_api_setup_payload():
    repo = FakePersistentSessionRepo()
    now = datetime(2026, 5, 18, 12, 0, 0)
    store = DatabaseSessionStore(
        session_repo=repo,
        encryption_manager=EncryptionManager(KeyGenerator.generate_key()),
        ttl_seconds=300,
        now_func=lambda: now,
    )

    session = await store.set_session(
        123,
        ApiSetupSession(step="passphrase", api_key="plain-api-key", secret_key="plain-secret-key"),
        user_id=1,
    )

    raw_record = repo.records[123]
    restored = await store.get_session(123)

    assert session.expires_at == now + timedelta(seconds=300)
    assert raw_record.user_id == 1
    assert raw_record.session_type == "api_setup"
    assert raw_record.payload_encrypted
    assert "plain-api-key" not in raw_record.payload_encrypted
    assert "plain-secret-key" not in raw_record.payload_encrypted
    assert isinstance(restored, ApiSetupSession)
    assert restored.api_key == "plain-api-key"
    assert restored.secret_key == "plain-secret-key"
    assert restored.expires_at == now + timedelta(seconds=300)


@pytest.mark.asyncio
async def test_database_session_store_drops_expired_session_on_read():
    repo = FakePersistentSessionRepo()
    now = datetime(2026, 5, 18, 12, 0, 0)
    store = DatabaseSessionStore(
        session_repo=repo,
        encryption_manager=EncryptionManager(KeyGenerator.generate_key()),
        ttl_seconds=300,
        now_func=lambda: now,
    )
    await store.set_session(123, ApiSetupSession(step="api_key"))

    now = now + timedelta(seconds=301)

    assert await store.get_session(123) is None
    assert repo.records == {}
