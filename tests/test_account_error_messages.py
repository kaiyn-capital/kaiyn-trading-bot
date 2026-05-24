from types import SimpleNamespace

import pytest

from app.bot_account_handlers import AccountHandlersMixin


class FakeBitgetAPIError(Exception):
    def __init__(self, code, message, http_status=None, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data or {}


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})


class FakeTradeManager:
    async def get_account_balance(self, user_id, credentials):
        raise FakeBitgetAPIError("40001", "invalid API key or permission")


class FakeAccountHandler(AccountHandlersMixin):
    def __init__(self):
        self.trade_manager = FakeTradeManager()
        self.user = SimpleNamespace(
            id=7,
            telegram_id=123,
            is_api_connected=True,
            encrypted_api_key="api",
            encrypted_secret_key="secret",
            encrypted_passphrase="passphrase",
        )

    async def _get_or_create_user(self, update):
        return self.user

    async def _log_user_action(self, user, action, metadata=None):
        return None


@pytest.mark.asyncio
async def test_balance_command_uses_classified_bitget_error_message():
    handler = FakeAccountHandler()
    update = SimpleNamespace(message=FakeMessage())
    context = SimpleNamespace()

    await handler.balance_command(update, context)

    assert update.message.replies[-1]["text"] == "❌ API 设置或权限异常，请检查 API Key 权限。"
