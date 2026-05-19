import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.bot_api_setup_service import TelegramApiSetupService
from app.bot_sessions import SESSION_EXPIRED_MESSAGE, UserSessionMixin
from app.bot_states import WAITING_PASSPHRASE, WAITING_SECRET_KEY


class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.deleted = False
        self.replies = []

    async def delete(self):
        self.deleted = True

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        message = FakeSentMessage(chat_id, text, kwargs)
        self.messages.append(message)
        return message


class FakeSentMessage:
    def __init__(self, chat_id, text, kwargs):
        self.chat_id = chat_id
        self.text = text
        self.kwargs = kwargs
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append({"text": text, "kwargs": kwargs})


class FakeSessionOwner(UserSessionMixin):
    def __init__(self):
        self.now = datetime(2026, 5, 18, 12, 0, 0)
        self.user_sessions = {}

    def _session_now(self):
        return self.now


class FakeUserRepo:
    def __init__(self):
        self.api_updates = []

    async def update_user_api_credentials(self, user_id, encrypted_api_key, encrypted_secret_key, encrypted_passphrase):
        self.api_updates.append(
            {
                "user_id": user_id,
                "encrypted_api_key": encrypted_api_key,
                "encrypted_secret_key": encrypted_secret_key,
                "encrypted_passphrase": encrypted_passphrase,
            }
        )
        return True


class FakeEncryptionManager:
    def encrypt_api_credentials(self, api_key, secret_key, passphrase):
        return (
            f"encrypted:{api_key}",
            f"encrypted:{secret_key}",
            f"encrypted:{passphrase}",
        )


class FakeTradeManager:
    def __init__(self, *, is_connected=True):
        self.is_connected = is_connected
        self.connection_tests = []
        self.invalidated_user_ids = []

    async def test_api_connection(self, credentials):
        self.connection_tests.append(credentials)
        if self.is_connected:
            return True, "API 連接成功"
        return False, "invalid credentials"

    async def invalidate_user_client(self, user_id):
        self.invalidated_user_ids.append(user_id)
        return True


class ApiSetupHarness:
    def __init__(self, *, is_connected=True):
        self.user = SimpleNamespace(id=1, telegram_id=123)
        self.session_owner = FakeSessionOwner()
        self.user_repo = FakeUserRepo()
        self.trade_manager = FakeTradeManager(is_connected=is_connected)
        self.encryption_manager = FakeEncryptionManager()
        self.logged_actions = []
        self.alerts = []
        self.service = TelegramApiSetupService(
            user_repo=self.user_repo,
            trade_manager=self.trade_manager,
            encryption_manager=self.encryption_manager,
            session_owner=self.session_owner,
            get_or_create_user=self.get_or_create_user,
            log_user_action=self.log_user_action,
            record_bitget_failure_alert=self.record_bitget_failure_alert,
        )

    async def get_or_create_user(self, update):
        return self.user

    async def log_user_action(self, user, action):
        self.logged_actions.append({"user_id": user.id, "action": action})

    async def record_bitget_failure_alert(self, classified, source, details):
        self.alerts.append({"classified": classified, "source": source, "details": details})


def make_update(text):
    return SimpleNamespace(
        message=FakeMessage(text),
        effective_chat=SimpleNamespace(id=456, type="private"),
    )


def make_context():
    return SimpleNamespace(bot=FakeBot())


def test_api_setup_service_advances_key_and_secret_steps_with_refreshed_ttl():
    harness = ApiSetupHarness()
    harness.session_owner.set_user_session(123, {"step": "api_key"})
    harness.session_owner.now += timedelta(seconds=30)

    key_update = make_update("valid-api-key-123")
    key_context = make_context()
    key_result = asyncio.run(harness.service.set_api_key(key_update, key_context))

    assert key_result == WAITING_SECRET_KEY
    assert harness.session_owner.user_sessions[123]["api_key"] == "valid-api-key-123"
    assert harness.session_owner.user_sessions[123]["expires_at"] == harness.session_owner.now + timedelta(seconds=300)

    harness.session_owner.now += timedelta(seconds=30)
    secret_update = make_update("valid-secret-key-123")
    secret_context = make_context()
    secret_result = asyncio.run(harness.service.set_secret_key(secret_update, secret_context))

    assert secret_result == WAITING_PASSPHRASE
    assert harness.session_owner.user_sessions[123]["secret_key"] == "valid-secret-key-123"
    assert harness.session_owner.user_sessions[123]["expires_at"] == harness.session_owner.now + timedelta(seconds=300)


def test_api_setup_service_expired_passphrase_does_not_use_partial_credentials():
    harness = ApiSetupHarness()
    harness.session_owner.set_user_session(
        123,
        {
            "step": "passphrase",
            "api_key": "valid-api-key-123",
            "secret_key": "valid-secret-key-123",
        },
    )
    harness.session_owner.now += timedelta(seconds=301)
    update = make_update("valid-passphrase")
    context = make_context()

    result = asyncio.run(harness.service.set_passphrase(update, context))

    assert result == -1
    assert harness.session_owner.user_sessions == {}
    assert update.message.deleted is False
    assert update.message.replies == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]
    assert harness.trade_manager.connection_tests == []


def test_api_setup_service_successful_passphrase_saves_credentials_and_invalidates_client():
    harness = ApiSetupHarness()
    harness.session_owner.set_user_session(
        123,
        {
            "step": "passphrase",
            "api_key": "valid-api-key-123",
            "secret_key": "valid-secret-key-123",
        },
    )
    update = make_update("valid-passphrase")
    context = make_context()

    result = asyncio.run(harness.service.set_passphrase(update, context))

    assert result == -1
    assert harness.session_owner.user_sessions == {}
    assert harness.user_repo.api_updates == [
        {
            "user_id": 1,
            "encrypted_api_key": "encrypted:valid-api-key-123",
            "encrypted_secret_key": "encrypted:valid-secret-key-123",
            "encrypted_passphrase": "encrypted:valid-passphrase",
        }
    ]
    assert harness.trade_manager.invalidated_user_ids == [1]
    assert harness.logged_actions == [{"user_id": 1, "action": "api_setup_success"}]
    assert context.bot.messages[0].edits[-1]["text"].startswith("✅ **API 设置成功！**")
