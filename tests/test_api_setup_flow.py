import asyncio
import sys
from types import SimpleNamespace

# Keep this handler test independent from the local cryptography wheel.
class FakeBitgetAPIError(Exception):
    def __init__(self, message=""):
        super().__init__(message)
        self.message = message


sys.modules.setdefault(
    "app.bitget_api", SimpleNamespace(BitgetAPIError=FakeBitgetAPIError)
)

from app.bot_account_handlers import AccountHandlersMixin
from app.bot_states import WAITING_API_KEY, WAITING_PASSPHRASE, WAITING_SECRET_KEY


class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class FakeAccountHandler(AccountHandlersMixin):
    def __init__(self):
        self.user_sessions = {}
        self.user = SimpleNamespace(telegram_id=123)

    async def _get_or_create_user(self, update):
        return self.user


def make_update(text):
    return SimpleNamespace(
        message=FakeMessage(text),
        effective_chat=SimpleNamespace(id=456),
    )


def make_context():
    return SimpleNamespace(bot=FakeBot())


def test_callback_api_setup_advances_from_api_key_to_secret_key():
    handler = FakeAccountHandler()
    handler.user_sessions[123] = {"step": "api_key"}
    update = make_update("valid-api-key-123")
    context = make_context()

    result = asyncio.run(handler.set_api_key(update, context))

    assert result == WAITING_SECRET_KEY
    assert update.message.deleted is True
    assert handler.user_sessions[123]["api_key"] == "valid-api-key-123"
    assert handler.user_sessions[123]["step"] == "secret_key"
    assert context.bot.messages[-1]["text"].startswith("✅ API Key 已保存")


def test_callback_api_setup_advances_from_secret_key_to_passphrase():
    handler = FakeAccountHandler()
    handler.user_sessions[123] = {
        "step": "secret_key",
        "api_key": "valid-api-key-123",
    }
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
    handler.user_sessions[123] = {"step": "api_key"}
    update = make_update("short")
    context = make_context()

    result = asyncio.run(handler.set_api_key(update, context))

    assert result == WAITING_API_KEY
    assert handler.user_sessions[123]["step"] == "api_key"
    assert "api_key" not in handler.user_sessions[123]
    assert context.bot.messages[-1]["text"] == "❌ API Key 格式不正确，请重新输入："
