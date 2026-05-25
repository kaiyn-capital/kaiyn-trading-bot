from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.bot_account_handlers import AccountHandlersMixin
from app.bot_sessions import SESSION_EXPIRED_MESSAGE
from app.bot_states import WAITING_API_KEY, WAITING_PASSPHRASE, WAITING_SECRET_KEY
from app.session_types import ApiSetupSession, RiskAmountSession


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

    def __getitem__(self, key):
        return getattr(self, key)

    async def edit_text(self, text, **kwargs):
        self.edits.append({"text": text, "kwargs": kwargs})


class FakeUserRepo:
    def __init__(self):
        self.risk_updates = []
        self.api_updates = []

    async def update_user_risk_amount(self, user_id, amount):
        self.risk_updates.append({"user_id": user_id, "amount": amount})
        return True

    async def update_user_api_credentials(
        self,
        user_id,
        encrypted_api_key,
        encrypted_secret_key,
        encrypted_passphrase,
    ):
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


class FakeAccountHandler(AccountHandlersMixin):
    def __init__(self):
        self.user_sessions = {}
        self.now = datetime(2026, 5, 18, 12, 0, 0)
        self.user = SimpleNamespace(id=1, telegram_id=123)
        self.user_repo = FakeUserRepo()
        self.encryption_manager = FakeEncryptionManager()
        self.trade_manager = FakeTradeManager()
        self.logged_actions = []

    def _session_now(self):
        return self.now

    async def _get_or_create_user(self, update):
        return self.user

    async def _log_user_action(self, user, action):
        self.logged_actions.append({"user_id": user.id, "action": action})

    async def _record_bitget_failure_alert(self, classified, operation, context):
        pass


def make_update(text):
    return SimpleNamespace(
        message=FakeMessage(text),
        effective_chat=SimpleNamespace(id=456, type="private"),
    )


def make_context():
    return SimpleNamespace(bot=FakeBot())


@pytest.mark.asyncio
async def test_callback_api_setup_advances_from_api_key_to_secret_key():
    handler = FakeAccountHandler()
    await handler.set_user_session(123, ApiSetupSession(step="api_key"))
    update = make_update("valid-api-key-123")
    context = make_context()

    result = await handler.set_api_key(update, context)

    assert result == WAITING_SECRET_KEY
    assert update.message.deleted is True
    assert handler.user_sessions[123]["api_key"] == "valid-api-key-123"
    assert handler.user_sessions[123]["step"] == "secret_key"
    assert handler.user_sessions[123]["expires_at"] == handler.now + timedelta(seconds=300)
    assert context.bot.messages[-1]["text"].startswith("✅ API Key 已保存")


@pytest.mark.asyncio
async def test_callback_api_setup_advances_from_secret_key_to_passphrase():
    handler = FakeAccountHandler()
    await handler.set_user_session(
        123,
        ApiSetupSession(step="secret_key", api_key="valid-api-key-123"),
    )
    update = make_update("valid-secret-key-123")
    context = make_context()

    result = await handler.set_secret_key(update, context)

    assert result == WAITING_PASSPHRASE
    assert update.message.deleted is True
    assert handler.user_sessions[123]["secret_key"] == "valid-secret-key-123"
    assert handler.user_sessions[123]["step"] == "passphrase"
    assert context.bot.messages[-1]["text"].startswith("✅ Secret Key 已保存")


@pytest.mark.asyncio
async def test_invalid_api_key_keeps_api_key_step():
    handler = FakeAccountHandler()
    await handler.set_user_session(123, ApiSetupSession(step="api_key"))
    original_expiry = handler.user_sessions[123]["expires_at"]
    handler.now = handler.now + timedelta(seconds=30)
    update = make_update("short")
    context = make_context()

    result = await handler.set_api_key(update, context)

    assert result == WAITING_API_KEY
    assert handler.user_sessions[123]["step"] == "api_key"
    assert "api_key" not in handler.user_sessions[123]
    assert handler.user_sessions[123]["expires_at"] > original_expiry
    assert context.bot.messages[-1]["text"] == "❌ API Key 格式不正确，请重新输入："


@pytest.mark.asyncio
async def test_expired_api_key_session_does_not_store_input_and_ends_flow():
    handler = FakeAccountHandler()
    await handler.set_user_session(123, ApiSetupSession(step="api_key"))
    handler.now = handler.now + timedelta(seconds=301)
    update = make_update("valid-api-key-123")
    context = make_context()

    result = await handler.set_api_key(update, context)

    assert result == -1
    assert handler.user_sessions == {}
    assert update.message.deleted is False
    assert update.message.replies == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]
    assert context.bot.messages == []


@pytest.mark.asyncio
async def test_expired_secret_key_session_does_not_use_partial_api_key():
    handler = FakeAccountHandler()
    await handler.set_user_session(
        123,
        ApiSetupSession(step="secret_key", api_key="valid-api-key-123"),
    )
    handler.now = handler.now + timedelta(seconds=301)
    update = make_update("valid-secret-key-123")
    context = make_context()

    result = await handler.set_secret_key(update, context)

    assert result == -1
    assert handler.user_sessions == {}
    assert update.message.deleted is False
    assert update.message.replies == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]
    assert context.bot.messages == []


@pytest.mark.asyncio
async def test_expired_passphrase_session_does_not_use_partial_credentials():
    handler = FakeAccountHandler()
    await handler.set_user_session(
        123,
        ApiSetupSession(
            step="passphrase",
            api_key="valid-api-key-123",
            secret_key="valid-secret-key-123",
        ),
    )
    handler.now = handler.now + timedelta(seconds=301)
    update = make_update("valid-passphrase")
    context = make_context()

    result = await handler.set_passphrase(update, context)

    assert result == -1
    assert handler.user_sessions == {}
    assert update.message.deleted is False
    assert update.message.replies == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]
    assert context.bot.messages == []


@pytest.mark.asyncio
async def test_successful_api_setup_invalidates_cached_trade_client():
    handler = FakeAccountHandler()
    await handler.set_user_session(
        123,
        ApiSetupSession(
            step="passphrase",
            api_key="valid-api-key-123",
            secret_key="valid-secret-key-123",
        ),
    )
    update = make_update("valid-passphrase")
    context = make_context()

    result = await handler.set_passphrase(update, context)

    assert result == -1
    assert update.message.deleted is True
    assert handler.user_sessions == {}
    assert handler.trade_manager.connection_tests == [
        (
            "encrypted:valid-api-key-123",
            "encrypted:valid-secret-key-123",
            "encrypted:valid-passphrase",
        )
    ]
    assert handler.user_repo.api_updates == [
        {
            "user_id": 1,
            "encrypted_api_key": "encrypted:valid-api-key-123",
            "encrypted_secret_key": "encrypted:valid-secret-key-123",
            "encrypted_passphrase": "encrypted:valid-passphrase",
        }
    ]
    assert handler.trade_manager.invalidated_user_ids == [1]
    assert handler.logged_actions == [{"user_id": 1, "action": "api_setup_success"}]
    assert context.bot.messages[0].text == "🔄 正在测试 API 连接..."
    assert context.bot.messages[0].edits[-1]["text"].startswith("✅ <b>API 设置成功！</b>")
    assert context.bot.messages[0].edits[-1]["kwargs"]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_failed_api_setup_does_not_invalidate_cached_trade_client():
    handler = FakeAccountHandler()
    handler.trade_manager = FakeTradeManager(is_connected=False)
    await handler.set_user_session(
        123,
        ApiSetupSession(
            step="passphrase",
            api_key="valid-api-key-123",
            secret_key="valid-secret-key-123",
        ),
    )
    update = make_update("valid-passphrase")
    context = make_context()

    result = await handler.set_passphrase(update, context)

    assert result == -1
    assert update.message.deleted is True
    assert handler.user_sessions == {}
    assert handler.user_repo.api_updates == []
    assert handler.trade_manager.invalidated_user_ids == []
    assert handler.logged_actions == []
    assert context.bot.messages[0].edits[-1]["text"].startswith("❌ <b>API 连接测试失败</b>")
    assert context.bot.messages[0].edits[-1]["kwargs"]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_expired_risk_amount_session_does_not_update_amount_and_only_prompts_once():
    handler = FakeAccountHandler()
    await handler.set_user_session(123, RiskAmountSession())
    handler.now = handler.now + timedelta(seconds=301)
    first_update = make_update("100")

    await handler.handle_global_message(first_update, make_context())

    assert handler.user_sessions == {}
    assert handler.user_repo.risk_updates == []
    assert first_update.message.replies == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]

    second_update = make_update("100")
    await handler.handle_global_message(second_update, make_context())

    assert second_update.message.replies == []
