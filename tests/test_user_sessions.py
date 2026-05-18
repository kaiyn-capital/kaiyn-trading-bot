from datetime import datetime, timedelta

from app.bot_sessions import UserSessionMixin


class FakeSessionOwner(UserSessionMixin):
    def __init__(self):
        self.user_sessions = {}
        self.now = datetime(2026, 5, 18, 12, 0, 0)

    def _session_now(self):
        return self.now


def test_set_user_session_adds_expiry():
    owner = FakeSessionOwner()

    session = owner.set_user_session(123, {"step": "risk_amount"})

    assert session == {
        "step": "risk_amount",
        "expires_at": owner.now + timedelta(seconds=300),
    }
    assert owner.user_sessions[123] == session


def test_get_active_user_session_returns_unexpired_session():
    owner = FakeSessionOwner()
    owner.set_user_session(123, {"step": "risk_amount"})

    owner.now = owner.now + timedelta(seconds=299)

    assert owner.get_active_user_session(123)["step"] == "risk_amount"
    assert 123 in owner.user_sessions


def test_expire_user_session_if_needed_clears_expired_session_once():
    owner = FakeSessionOwner()
    owner.set_user_session(123, {"step": "risk_amount"})
    owner.now = owner.now + timedelta(seconds=301)

    assert owner.expire_user_session_if_needed(123) is True
    assert owner.user_sessions == {}
    assert owner.expire_user_session_if_needed(123) is False


def test_update_user_session_refreshes_expiry_and_preserves_data():
    owner = FakeSessionOwner()
    owner.set_user_session(123, {"step": "api_key", "api_key": "old"})
    original_expiry = owner.user_sessions[123]["expires_at"]

    owner.now = owner.now + timedelta(seconds=60)
    session = owner.update_user_session(123, {"step": "secret_key"})

    assert session["api_key"] == "old"
    assert session["step"] == "secret_key"
    assert session["expires_at"] > original_expiry


def test_set_user_session_overwrites_existing_session_for_same_user():
    owner = FakeSessionOwner()
    owner.set_user_session(123, {"step": "api_key", "api_key": "old"})

    session = owner.set_user_session(123, {"step": "risk_amount"})

    assert session["step"] == "risk_amount"
    assert "api_key" not in session
    assert len(owner.user_sessions) == 1
