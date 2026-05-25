from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from settings_factory import make_settings
from telegram.error import TelegramError

import app.bot_order_handlers as bot_order_handlers
from app.bot_order_handlers import OrderHandlersMixin
from app.bot_sessions import UserSessionMixin
from app.repository_types import ChannelRecord, SignalChannelMessageRecord, SignalRecordSnapshot


def make_channel_record(**overrides):
    data = {
        "id": 1,
        "chat_id": "-1001",
        "chat_type": "channel",
        "title": "signals",
        "username": None,
        "is_active": True,
        "auto_forward_signals": True,
        "forward_with_buttons": True,
        "message_thread_id": 456,
        "thread_title": None,
        "added_by_user_id": 123,
        "description": None,
        "created_at": None,
        "updated_at": None,
    }
    data.update(overrides)
    return ChannelRecord(**data)


def signal_record_snapshot_from_data(data: dict) -> SignalRecordSnapshot:
    now = data.get("created_at") or datetime.utcnow()
    return SignalRecordSnapshot(
        id=data["id"],
        public_id=data["public_id"],
        user_id=data["user_id"],
        sender_telegram_id=data["sender_telegram_id"],
        sender_username=data["sender_username"],
        symbol=data["symbol"],
        direction=data["direction"],
        entry_lower=data["entry_lower"],
        entry_upper=data["entry_upper"],
        stop_loss=data["stop_loss"],
        take_profit_levels=data["take_profit_levels"],
        remark=data["remark"],
        signal_text=data["signal_text"],
        granularity=data["granularity"],
        status=data["status"],
        chart_status=data["chart_status"],
        chart_error=data["chart_error"],
        created_at=now,
        updated_at=data.get("updated_at") or now,
        confirmed_at=data.get("confirmed_at"),
    )


def channel_message_record_from_data(data: dict) -> SignalChannelMessageRecord:
    return SignalChannelMessageRecord(
        id=data["id"],
        signal_record_id=data["signal_record_id"],
        chat_id=data["chat_id"],
        message_thread_id=data["message_thread_id"],
        telegram_message_id=data["telegram_message_id"],
        sent_as=data["sent_as"],
        created_at=data.get("created_at"),
    )


class FakeMessage:
    def __init__(self):
        self.replies = []
        self.photos = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})

    async def reply_photo(self, **kwargs):
        self.photos.append(kwargs)


class FakeQuery:
    def __init__(self):
        self.caption_edits = []
        self.text_edits = []
        self.fail_caption_edit = False

    async def edit_message_caption(self, caption, **kwargs):
        if self.fail_caption_edit:
            raise TelegramError("caption edit failed")
        self.caption_edits.append({"caption": caption, "kwargs": kwargs})

    async def edit_message_text(self, text, **kwargs):
        self.text_edits.append({"text": text, "kwargs": kwargs})


class FakeBot:
    def __init__(self):
        self.sent_messages = []
        self.sent_photos = []
        self.fail_photo = False
        self.next_message_id = 100

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        self.next_message_id += 1
        return SimpleNamespace(message_id=self.next_message_id)

    async def send_photo(self, **kwargs):
        if self.fail_photo:
            raise TelegramError("photo failed")
        self.sent_photos.append(kwargs)
        self.next_message_id += 1
        return SimpleNamespace(message_id=self.next_message_id)


class RecordingCandleTradeManager:
    def __init__(self):
        self.calls = []

    async def get_candles(self, symbol, granularity, limit, **kwargs):
        self.calls.append(
            {
                "symbol": symbol,
                "granularity": granularity,
                "limit": limit,
                "kwargs": kwargs,
            }
        )
        return []


class FakeChannelRepo:
    async def get_signal_channels(self):
        return [
            make_channel_record(id=1, chat_id="-1001", message_thread_id=456),
            make_channel_record(id=2, chat_id="-1002", message_thread_id=None),
        ]


class FakeSignalRecordRepo:
    def __init__(self):
        self.records = {}
        self.messages = []
        self.next_id = 1

    async def get_by_public_id(self, public_id):
        record = self.records.get(public_id)
        return signal_record_snapshot_from_data(record) if record else None

    async def get_by_id(self, record_id):
        for record in self.records.values():
            if record["id"] == record_id:
                return signal_record_snapshot_from_data(record)
        return None

    async def create_signal_record(
        self,
        *,
        public_id,
        user_id,
        sender_telegram_id,
        sender_username,
        signal,
        signal_text,
        granularity,
        chart_status,
        chart_error,
    ):
        record = {
            "id": self.next_id,
            "public_id": public_id,
            "user_id": user_id,
            "sender_telegram_id": sender_telegram_id,
            "sender_username": sender_username,
            "symbol": signal.symbol,
            "direction": signal.direction,
            "entry_lower": signal.entry_lower,
            "entry_upper": signal.entry_upper,
            "stop_loss": signal.stop_loss,
            "take_profit_levels": signal.take_profit_levels,
            "remark": signal.remark,
            "signal_text": signal_text,
            "granularity": granularity,
            "status": "preview_pending",
            "chart_status": chart_status,
            "chart_error": chart_error,
            "created_at": datetime.utcnow(),
        }
        self.records[public_id] = record
        self.next_id += 1
        return signal_record_snapshot_from_data(record)

    async def update_status(self, record_id, status):
        for record in self.records.values():
            if record["id"] == record_id:
                record["status"] = status
                return True
        return False

    async def add_channel_message(
        self,
        *,
        signal_record_id,
        chat_id,
        message_thread_id,
        telegram_message_id,
        sent_as,
    ):
        message = {
            "id": len(self.messages) + 1,
            "signal_record_id": signal_record_id,
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
            "telegram_message_id": telegram_message_id,
            "sent_as": sent_as,
            "created_at": datetime.utcnow(),
        }
        self.messages.append(message)
        return channel_message_record_from_data(message)

    async def get_channel_messages(self, signal_record_id):
        return [
            channel_message_record_from_data(message)
            for message in self.messages
            if message["signal_record_id"] == signal_record_id
        ]


class FakeOrderHandler(OrderHandlersMixin, UserSessionMixin):
    def __init__(self, settings=None):
        self.settings = settings or make_settings()
        self.channel_repo = FakeChannelRepo()
        self.signal_record_repo = FakeSignalRecordRepo()
        self.user = SimpleNamespace(id=1, telegram_id=123)
        self.audit_events = []
        self.user_sessions = {}
        self.application = SimpleNamespace(bot=FakeBot())

    async def _get_or_create_user(self, update):
        return self.user

    async def _is_trader_or_admin(self, telegram_id):
        return True

    def _get_sender_username(self, update):
        return "admin"

    async def _audit_action(self, user, action, details=None):
        self.audit_events.append({"action": action, "details": details or {}})

    async def _create_signal_chart(self, signal):
        return b"fake-png"


class FailingChartOrderHandler(FakeOrderHandler):
    async def _create_signal_chart(self, signal):
        raise RuntimeError("chart failed")


class UpdateChartOrderHandler(FakeOrderHandler):
    async def _create_signal_update_chart(self, signal, signal_time, granularity):
        return b"fake-update-png"


def make_update():
    return SimpleNamespace(message=FakeMessage())


def make_context():
    return SimpleNamespace(
        args=["BTCUSDT", "short", "entry[80200", "81000]", "sl[81700]", "tp[77777", "75000]", "等待回踩后执行"],
        bot=FakeBot(),
    )


@pytest.mark.asyncio
async def test_send_signal_creates_text_preview_without_forwarding():
    handler = FakeOrderHandler(settings=make_settings(signal_chart_enabled=False))
    update = make_update()
    context = make_context()

    await handler.send_signal_command(update, context)

    assert context.bot.sent_messages == []
    assert handler.application.bot.sent_messages == []
    assert update.message.replies[0]["text"].startswith("📋 <b>请确认是否转发以下交易信号</b>")
    assert update.message.replies[0]["kwargs"]["parse_mode"] == "HTML"
    session = handler.user_sessions[handler.user.telegram_id]
    assert session["step"] == "signal_preview"
    assert session["signal_public_id"]
    record = handler.signal_record_repo.records[session["signal_public_id"]]
    assert record["symbol"] == "BTCUSDT"
    assert "交易id:" in update.message.replies[0]["text"]
    keyboard = update.message.replies[0]["kwargs"]["reply_markup"].inline_keyboard
    assert keyboard[0][0].callback_data == f"confirm_signal_{session['token']}"
    assert keyboard[1][0].callback_data == f"cancel_signal_{session['token']}"


@pytest.mark.asyncio
async def test_send_signal_records_preview_audit():
    handler = FakeOrderHandler(settings=make_settings(signal_chart_enabled=False))
    update = make_update()
    context = make_context()

    await handler.send_signal_command(update, context)

    audit = handler.audit_events[-1]
    assert audit["action"] == "signal_preview_created"
    assert audit["details"]["status"] == "pending"
    assert audit["details"]["symbol"] == "BTCUSDT"
    assert audit["details"]["direction"] == "short"
    assert audit["details"]["remark"] == "等待回踩后执行"
    assert audit["details"]["chart_status"] == "disabled"


@pytest.mark.asyncio
async def test_send_signal_sends_chart_photo_preview():
    handler = FakeOrderHandler(settings=make_settings(signal_chart_enabled=True, signal_chart_timeout_seconds=1.0))
    update = make_update()
    context = make_context()

    await handler.send_signal_command(update, context)

    assert update.message.photos[0]["caption"].startswith("📋 <b>请确认是否转发以下交易信号</b>")
    assert update.message.photos[0]["parse_mode"] == "HTML"
    assert update.message.photos[0]["reply_markup"] is not None
    assert handler.audit_events[-1]["details"]["chart_status"] == "generated"


@pytest.mark.asyncio
async def test_send_signal_falls_back_to_text_preview_when_chart_generation_fails():
    handler = FailingChartOrderHandler(
        settings=make_settings(signal_chart_enabled=True, signal_chart_timeout_seconds=1.0)
    )
    update = make_update()
    context = make_context()

    await handler.send_signal_command(update, context)

    assert update.message.replies[0]["text"].startswith("📋 <b>请确认是否转发以下交易信号</b>")
    assert update.message.replies[0]["kwargs"]["parse_mode"] == "HTML"
    assert not update.message.photos
    audit = handler.audit_events[-1]
    assert audit["details"]["chart_status"] == "failed"
    assert audit["details"]["chart_error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_confirm_signal_forwards_to_configured_topic():
    handler = FakeOrderHandler(settings=make_settings(signal_chart_enabled=True, signal_chart_timeout_seconds=1.0))
    update = make_update()
    context = make_context()

    await handler.send_signal_command(update, context)
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    query = FakeQuery()
    await handler._handle_confirm_signal_callback(query, handler.user, f"confirm_signal_{token}")

    first_photo = handler.application.bot.sent_photos[0]
    assert first_photo["chat_id"] == "-1001"
    assert first_photo["message_thread_id"] == 456
    assert first_photo["caption"].startswith("🚨 <b>交易信号</b>")
    assert first_photo["parse_mode"] == "HTML"
    assert first_photo["reply_markup"] is not None
    second_photo = handler.application.bot.sent_photos[1]
    assert second_photo["chat_id"] == "-1002"
    assert "message_thread_id" not in second_photo
    assert handler.user_sessions == {}
    assert query.caption_edits[-1]["caption"].startswith("✅ <b>交易信号已转发</b>")
    assert query.caption_edits[-1]["kwargs"]["parse_mode"] == "HTML"
    assert handler.audit_events[-1]["action"] == "signal_sent"
    assert len(handler.signal_record_repo.messages) == 2
    assert handler.signal_record_repo.messages[0]["message_thread_id"] == 456


@pytest.mark.asyncio
async def test_confirm_signal_falls_back_to_text_when_photo_send_fails():
    handler = FakeOrderHandler(settings=make_settings(signal_chart_enabled=True, signal_chart_timeout_seconds=1.0))
    handler.application.bot.fail_photo = True
    update = make_update()
    context = make_context()

    await handler.send_signal_command(update, context)
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    await handler._handle_confirm_signal_callback(FakeQuery(), handler.user, f"confirm_signal_{token}")

    assert len(handler.application.bot.sent_messages) == 2
    assert handler.application.bot.sent_messages[0]["message_thread_id"] == 456
    assert handler.application.bot.sent_messages[0]["text"].startswith("🚨 <b>交易信号</b>")
    assert handler.application.bot.sent_messages[0]["parse_mode"] == "HTML"
    audit = handler.audit_events[-1]
    assert audit["details"]["sent_count"] == 2
    assert audit["details"]["chart_send_fallback_count"] == 2


@pytest.mark.asyncio
async def test_cancel_signal_clears_session_without_forwarding():
    handler = FakeOrderHandler(settings=make_settings(signal_chart_enabled=False))
    update = make_update()
    context = make_context()

    await handler.send_signal_command(update, context)
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    query = FakeQuery()
    query.fail_caption_edit = True
    await handler._handle_cancel_signal_callback(query, handler.user, f"cancel_signal_{token}")

    assert handler.user_sessions == {}
    assert handler.application.bot.sent_messages == []
    assert query.text_edits == [{"text": "✅ 已取消转发", "kwargs": {"reply_markup": None}}]
    assert handler.audit_events[-1]["action"] == "signal_preview_cancelled"
    assert next(iter(handler.signal_record_repo.records.values()))["status"] == "cancelled"


@pytest.mark.asyncio
async def test_expired_signal_preview_does_not_forward():
    handler = FakeOrderHandler(settings=make_settings(signal_chart_enabled=False))
    update = make_update()
    context = make_context()

    await handler.send_signal_command(update, context)
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    handler.user_sessions[handler.user.telegram_id] = replace(
        handler.user_sessions[handler.user.telegram_id],
        expires_at=datetime.utcnow() - timedelta(seconds=1),
    )
    query = FakeQuery()
    query.fail_caption_edit = True
    await handler._handle_confirm_signal_callback(query, handler.user, f"confirm_signal_{token}")

    assert handler.application.bot.sent_messages == []
    assert handler.user_sessions == {}
    assert query.text_edits[0]["text"].startswith("⏳ 预览已过期")
    assert handler.audit_events[-1]["action"] == "signal_preview_expired"
    assert next(iter(handler.signal_record_repo.records.values()))["status"] == "expired"


@pytest.mark.asyncio
async def test_new_signal_preview_replaces_old_token():
    handler = FakeOrderHandler(settings=make_settings(signal_chart_enabled=False))
    first_update = make_update()
    second_update = make_update()
    context = make_context()

    await handler.send_signal_command(first_update, context)
    old_token = handler.user_sessions[handler.user.telegram_id]["token"]
    await handler.send_signal_command(second_update, context)
    new_token = handler.user_sessions[handler.user.telegram_id]["token"]
    query = FakeQuery()
    query.fail_caption_edit = True
    await handler._handle_confirm_signal_callback(query, handler.user, f"confirm_signal_{old_token}")

    assert old_token != new_token
    assert handler.application.bot.sent_messages == []
    assert query.text_edits[0]["text"].startswith("⏳ 预览已过期")


@pytest.mark.asyncio
async def test_update_chart_creates_private_photo_preview():
    handler = UpdateChartOrderHandler(settings=make_settings(signal_chart_enabled=True))
    update = make_update()
    context = make_context()
    await handler.send_signal_command(update, context)
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    await handler._handle_confirm_signal_callback(FakeQuery(), handler.user, f"confirm_signal_{token}")
    signal_id = next(iter(handler.signal_record_repo.records))

    chart_update = make_update()
    await handler.update_chart_command(chart_update, SimpleNamespace(args=[signal_id, "TP1", "到达"]))

    assert chart_update.message.photos[0]["caption"].startswith("📋 <b>请确认是否转发以下图表更新</b>")
    assert chart_update.message.photos[0]["parse_mode"] == "HTML"
    assert f"交易id: <code>{signal_id}</code>" in chart_update.message.photos[0]["caption"]
    session = handler.user_sessions[handler.user.telegram_id]
    assert session["step"] == "chart_update_preview"
    keyboard = chart_update.message.photos[0]["reply_markup"].inline_keyboard
    assert keyboard[0][0].callback_data == f"confirm_chart_update_{session['token']}"


@pytest.mark.asyncio
async def test_confirm_update_chart_replies_to_original_signal_messages():
    handler = UpdateChartOrderHandler(settings=make_settings(signal_chart_enabled=True))
    update = make_update()
    context = make_context()
    await handler.send_signal_command(update, context)
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    await handler._handle_confirm_signal_callback(FakeQuery(), handler.user, f"confirm_signal_{token}")
    signal_id = next(iter(handler.signal_record_repo.records))

    chart_update = make_update()
    await handler.update_chart_command(chart_update, SimpleNamespace(args=[signal_id]))
    update_token = handler.user_sessions[handler.user.telegram_id]["token"]
    query = FakeQuery()
    await handler._handle_confirm_chart_update_callback(query, handler.user, f"confirm_chart_update_{update_token}")

    first_update_photo = handler.application.bot.sent_photos[2]
    assert first_update_photo["chat_id"] == "-1001"
    assert first_update_photo["message_thread_id"] == 456
    assert first_update_photo["reply_to_message_id"] == handler.signal_record_repo.messages[0]["telegram_message_id"]
    assert "交易id:" in first_update_photo["caption"]
    assert query.caption_edits[-1]["caption"].startswith("✅ <b>图表更新已转发</b>")
    assert query.caption_edits[-1]["kwargs"]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_update_chart_allows_admin_to_update_other_users_signal():
    handler = UpdateChartOrderHandler(settings=make_settings(signal_chart_enabled=True, admin_ids=(999,)))
    update = make_update()
    context = make_context()
    await handler.send_signal_command(update, context)
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    await handler._handle_confirm_signal_callback(FakeQuery(), handler.user, f"confirm_signal_{token}")
    signal_id = next(iter(handler.signal_record_repo.records))
    handler.user = SimpleNamespace(id=2, telegram_id=999)

    chart_update = make_update()
    await handler.update_chart_command(chart_update, SimpleNamespace(args=[signal_id]))

    assert chart_update.message.photos


@pytest.mark.asyncio
async def test_signal_update_chart_uses_configured_candle_limit(monkeypatch):
    monkeypatch.setattr(bot_order_handlers, "render_signal_update_chart", lambda *args: b"fake-update-png")
    handler = FakeOrderHandler(settings=make_settings(signal_update_candle_limit=200))
    handler.trade_manager = RecordingCandleTradeManager()
    signal = SimpleNamespace(symbol="BTCUSDT")

    image = await handler._create_signal_update_chart(signal, datetime(2026, 5, 22), "1H")

    assert image == b"fake-update-png"
    assert handler.trade_manager.calls[-1]["symbol"] == "BTCUSDT"
    assert handler.trade_manager.calls[-1]["granularity"] == "1H"
    assert handler.trade_manager.calls[-1]["limit"] == 200
    assert "end_time" in handler.trade_manager.calls[-1]["kwargs"]


@pytest.mark.asyncio
async def test_update_chart_rejects_non_owner_non_admin():
    handler = UpdateChartOrderHandler(settings=make_settings(signal_chart_enabled=True))
    update = make_update()
    context = make_context()
    await handler.send_signal_command(update, context)
    token = handler.user_sessions[handler.user.telegram_id]["token"]
    await handler._handle_confirm_signal_callback(FakeQuery(), handler.user, f"confirm_signal_{token}")
    signal_id = next(iter(handler.signal_record_repo.records))
    handler.user = SimpleNamespace(id=2, telegram_id=456)

    chart_update = make_update()
    await handler.update_chart_command(chart_update, SimpleNamespace(args=[signal_id]))

    assert chart_update.message.replies[0]["text"] == "❌ 只有原发单者或管理员可以更新这笔交易信号"
    assert not chart_update.message.photos
