import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.bot_account_handlers import AccountHandlersMixin
from app.bot_sessions import SESSION_EXPIRED_MESSAGE
from app.bot_states import WAITING_API_KEY, WAITING_PASSPHRASE, WAITING_SECRET_KEY


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
        self.messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class FakeUserRepo:
    def __init__(self):
        self.risk_updates = []

    async def update_user_risk_amount(self, user_id, amount):
        self.risk_updates.append({"user_id": user_id, "amount": amount})
        return True


class FakeAccountHandler(AccountHandlersMixin):
    def __init__(self):
        self.user_sessions = {}
        self.now = datetime(2026, 5, 18, 12, 0, 0)
        self.user = SimpleNamespace(id=1, telegram_id=123)
        self.user_repo = FakeUserRepo()

    def _session_now(self):
        return self.now

    async def _get_or_create_user(self, update):
        return self.user


def make_update(text):
    return SimpleNamespace(
        message=FakeMessage(text),
        effective_chat=SimpleNamespace(id=456, type="private"),
    )


def make_context():
    return SimpleNamespace(bot=FakeBot())


def test_callback_api_setup_advances_from_api_key_to_secret_key():
    handler = FakeAccountHandler()
    handler.set_user_session(123, {"step": "api_key"})
    update = make_update("valid-api-key-123")
    context = make_context()

    result = asyncio.run(handler.set_api_key(update, context))

    assert result == WAITING_SECRET_KEY
    assert update.message.deleted is True
    assert handler.user_sessions[123]["api_key"] == "valid-api-key-123"
    assert handler.user_sessions[123]["step"] == "secret_key"
    assert handler.user_sessions[123]["expires_at"] == handler.now + timedelta(seconds=300)
    assert context.bot.messages[-1]["text"].startswith("✅ API Key 已保存")


def test_callback_api_setup_advances_from_secret_key_to_passphrase():
    handler = FakeAccountHandler()
    handler.set_user_session(
        123,
        {
            "step": "secret_key",
            "api_key": "valid-api-key-123",
        },
    )
    update = make_update("valid-secret-key-123")
    context = make_context()

    result = asyncio.run(handler.set_secret_key(update, context))

    assert result == WAITING_PASSPHRASE
    assert update.message.deleted is True
    assert handler.user_sessions[123]["secret_key"] == "valid-secret-key-123"
    assert handler.user_sessions[123]["step"] == "passphrase"
    assert context.bot.messages[-1]["text"].startswith("✅ Secret Key 已保存")


def test_invalid_api_key_keeps_api_key_step():
    handler = FakeAccountHandler()
    handler.set_user_session(123, {"step": "api_key"})
    original_expiry = handler.user_sessions[123]["expires_at"]
    handler.now = handler.now + timedelta(seconds=30)
    update = make_update("short")
    context = make_context()

    result = asyncio.run(handler.set_api_key(update, context))

    assert result == WAITING_API_KEY
    assert handler.user_sessions[123]["step"] == "api_key"
    assert "api_key" not in handler.user_sessions[123]
    assert handler.user_sessions[123]["expires_at"] > original_expiry
    assert context.bot.messages[-1]["text"] == "❌ API Key 格式不正确，请重新输入："


def test_expired_api_key_session_does_not_store_input_and_ends_flow():
    handler = FakeAccountHandler()
    handler.set_user_session(123, {"step": "api_key"})
    handler.now = handler.now + timedelta(seconds=301)
    update = make_update("valid-api-key-123")
    context = make_context()

    result = asyncio.run(handler.set_api_key(update, context))

    assert result == -1
    assert handler.user_sessions == {}
    assert update.message.deleted is False
    assert update.message.replies == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]
    assert context.bot.messages == []


def test_expired_secret_key_session_does_not_use_partial_api_key():
    handler = FakeAccountHandler()
    handler.set_user_session(
        123,
        {
            "step": "secret_key",
            "api_key": "valid-api-key-123",
        },
    )
    handler.now = handler.now + timedelta(seconds=301)
    update = make_update("valid-secret-key-123")
    context = make_context()

    result = asyncio.run(handler.set_secret_key(update, context))

    assert result == -1
    assert handler.user_sessions == {}
    assert update.message.deleted is False
    assert update.message.replies == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]
    assert context.bot.messages == []


def test_expired_passphrase_session_does_not_use_partial_credentials():
    handler = FakeAccountHandler()
    handler.set_user_session(
        123,
        {
            "step": "passphrase",
            "api_key": "valid-api-key-123",
            "secret_key": "valid-secret-key-123",
        },
    )
    handler.now = handler.now + timedelta(seconds=301)
    update = make_update("valid-passphrase")
    context = make_context()

    result = asyncio.run(handler.set_passphrase(update, context))

    assert result == -1
    assert handler.user_sessions == {}
    assert update.message.deleted is False
    assert update.message.replies == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]
    assert context.bot.messages == []


def test_expired_risk_amount_session_does_not_update_amount_and_only_prompts_once():
    handler = FakeAccountHandler()
    handler.set_user_session(123, {"step": "risk_amount"})
    handler.now = handler.now + timedelta(seconds=301)
    first_update = make_update("100")

    asyncio.run(handler.handle_global_message(first_update, make_context()))

    assert handler.user_sessions == {}
    assert handler.user_repo.risk_updates == []
    assert first_update.message.replies == [{"text": SESSION_EXPIRED_MESSAGE, "kwargs": {}}]

    second_update = make_update("100")
    asyncio.run(handler.handle_global_message(second_update, make_context()))

    assert second_update.message.replies == []
