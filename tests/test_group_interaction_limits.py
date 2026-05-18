import asyncio
from types import SimpleNamespace

from telegram.ext import CommandHandler, ConversationHandler, MessageHandler

from app import bot as bot_module
from app.bot import TelegramBot
from app.bot_account_handlers import AccountHandlersMixin
from app.bot_states import WAITING_API_KEY, WAITING_PASSPHRASE, WAITING_SECRET_KEY


class FakeApplication:
    def __init__(self):
        self.handlers = []
        self.error_handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)

    def add_error_handler(self, handler):
        self.error_handlers.append(handler)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answers.append({"text": text, "kwargs": kwargs})

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({"text": text, "kwargs": kwargs})


class FakeCommandBot:
    def __init__(self):
        self.deleted = []
        self.set_commands = []

    async def delete_my_commands(self, **kwargs):
        self.deleted.append(kwargs)

    async def set_my_commands(self, commands, **kwargs):
        self.set_commands.append({"commands": commands, "kwargs": kwargs})


class FakeSystemLogRepo:
    def __init__(self):
        self.logs = []

    async def log(self, **kwargs):
        self.logs.append(kwargs)


class FakeUserRepo:
    async def get_user_by_telegram_id(self, telegram_id):
        return None


class FakeContextBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)


class FakeAccountHandler(AccountHandlersMixin):
    def __init__(self):
        self.user_sessions = {123: {"step": "risk_amount"}}
        self.get_user_called = False
        self.risk_amount_called = False
        self.user = SimpleNamespace(id=1, telegram_id=123)

    async def _get_or_create_user(self, update):
        self.get_user_called = True
        return self.user

    async def set_risk_amount(self, update, context):
        self.risk_amount_called = True


def _install_handlers(monkeypatch):
    bot = TelegramBot.__new__(TelegramBot)
    bot.application = FakeApplication()

    def fake_create_task(coro):
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(bot_module.asyncio, "create_task", fake_create_task)
    TelegramBot._setup_handlers(bot)
    return bot


def _filter_text(handler):
    return str(getattr(handler, "filters", ""))


def _command_handlers(bot):
    return [handler for handler in bot.application.handlers if isinstance(handler, CommandHandler)]


def _command_names(handler):
    return {str(command) for command in handler.commands}


def _make_update(chat_type, data=None):
    return SimpleNamespace(
        callback_query=FakeQuery(data),
        effective_chat=SimpleNamespace(id=-100123 if chat_type != "private" else 123, type=chat_type),
        effective_user=SimpleNamespace(id=123),
        effective_message=SimpleNamespace(message_id=10, text="/start"),
        update_id=1,
    )


def test_registered_command_handlers_are_private_only(monkeypatch):
    bot = _install_handlers(monkeypatch)
    expected_commands = {
        "start",
        "help",
        "status",
        "balance",
        "settings",
        "admin",
        "admin_health",
        "admin_audit",
        "admin_users",
        "admin_broadcast",
        "admin_channels",
        "add_channel",
        "send_signal",
        "send_to_channel",
        "set_channel_topic",
        "clear_channel_topic",
        "add_trader",
    }

    command_handlers = _command_handlers(bot)
    registered_commands = set().union(*(_command_names(handler) for handler in command_handlers))

    assert expected_commands <= registered_commands
    for handler in command_handlers:
        assert "PRIVATE" in _filter_text(handler)


def test_conversation_and_global_text_handlers_are_private_only(monkeypatch):
    bot = _install_handlers(monkeypatch)
    conversation = next(handler for handler in bot.application.handlers if isinstance(handler, ConversationHandler))
    global_message = next(
        handler
        for handler in bot.application.handlers
        if isinstance(handler, MessageHandler) and handler.callback == bot.handle_global_message
    )

    assert "PRIVATE" in _filter_text(conversation.entry_points[0])
    assert "PRIVATE" in _filter_text(global_message)

    for state in (WAITING_API_KEY, WAITING_SECRET_KEY, WAITING_PASSPHRASE):
        state_handler = conversation.states[state][0]
        assert "PRIVATE" in _filter_text(state_handler)


def test_setup_commands_only_sets_private_scope():
    bot = TelegramBot.__new__(TelegramBot)
    bot.application = SimpleNamespace(bot=FakeCommandBot())

    asyncio.run(TelegramBot.setup_commands(bot))

    deleted_scope_names = [type(call["scope"]).__name__ for call in bot.application.bot.deleted]
    set_scope_name = type(bot.application.bot.set_commands[0]["kwargs"]["scope"]).__name__

    assert deleted_scope_names == ["BotCommandScopeDefault", "BotCommandScopeAllGroupChats"]
    assert set_scope_name == "BotCommandScopeAllPrivateChats"
    assert [command.command for command in bot.application.bot.set_commands[0]["commands"]] == [
        "start",
        "help",
        "setapi",
        "status",
        "balance",
        "settings",
    ]


def test_group_non_order_callback_is_private_alert_only():
    bot = TelegramBot.__new__(TelegramBot)
    bot.user_sessions = {123: {"step": "risk_amount"}}

    async def fail_if_user_is_loaded(update):
        raise AssertionError("group non-order callback should not load or create users")

    bot._get_or_create_user = fail_if_user_is_loaded
    update = _make_update("supergroup", data="set_risk_amount")

    asyncio.run(TelegramBot.button_callback(bot, update, SimpleNamespace()))

    assert update.callback_query.answers == [{"text": "请到与机器人的私人聊天操作", "kwargs": {"show_alert": True}}]
    assert update.callback_query.edits == []
    assert bot.user_sessions == {123: {"step": "risk_amount"}}


def test_group_order_callback_still_routes_to_order_flow():
    bot = TelegramBot.__new__(TelegramBot)
    bot.user_sessions = {}
    routed = []
    user = SimpleNamespace(telegram_id=123)

    async def get_user(update):
        return user

    async def handle_order(query, callback_user, data):
        routed.append({"query": query, "user": callback_user, "data": data})

    bot._get_or_create_user = get_user
    bot._handle_place_order_callback = handle_order
    update = _make_update("supergroup", data="place_order_BTCUSDT_long_market_80000_81000_79000")

    asyncio.run(TelegramBot.button_callback(bot, update, SimpleNamespace()))

    assert update.callback_query.answers == [{"text": None, "kwargs": {}}]
    assert routed == [{"query": update.callback_query, "user": user, "data": update.callback_query.data}]


def test_group_global_message_does_not_continue_private_setup_session():
    handler = FakeAccountHandler()
    update = SimpleNamespace(
        message=SimpleNamespace(text="100"),
        effective_chat=SimpleNamespace(id=-100123, type="supergroup"),
    )

    asyncio.run(handler.handle_global_message(update, SimpleNamespace()))

    assert handler.get_user_called is False
    assert handler.risk_amount_called is False


def test_error_handler_does_not_send_public_group_message():
    bot = TelegramBot.__new__(TelegramBot)
    bot.user_repo = FakeUserRepo()
    bot.system_log_repo = FakeSystemLogRepo()
    context = SimpleNamespace(error=RuntimeError("boom"), bot=FakeContextBot())
    update = _make_update("supergroup", data=None)

    asyncio.run(TelegramBot.error_handler(bot, update, context))

    assert bot.system_log_repo.logs[-1]["message"] == "boom"
    assert context.bot.sent_messages == []


def test_error_handler_keeps_private_error_message():
    bot = TelegramBot.__new__(TelegramBot)
    bot.user_repo = FakeUserRepo()
    bot.system_log_repo = FakeSystemLogRepo()
    context = SimpleNamespace(error=RuntimeError("boom"), bot=FakeContextBot())
    update = _make_update("private", data=None)

    asyncio.run(TelegramBot.error_handler(bot, update, context))

    assert bot.system_log_repo.logs[-1]["message"] == "boom"
    assert context.bot.sent_messages == [
        {
            "chat_id": 123,
            "text": "❌ 系统发生错误，请稍后重试。如问题持续，请联系管理员。",
        }
    ]
