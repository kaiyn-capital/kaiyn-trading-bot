from types import SimpleNamespace

import pytest
from telegram.error import TelegramError

from app.order_types import SignalDraft
from app.signal_delivery_service import TELEGRAM_PHOTO_CAPTION_LIMIT, SignalDeliveryService


class FakeBot:
    def __init__(self):
        self.sent_messages = []
        self.sent_photos = []
        self.fail_photo = False
        self.fail_reply_photo = False
        self.next_message_id = 100

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        self.next_message_id += 1
        return SimpleNamespace(message_id=self.next_message_id)

    async def send_photo(self, **kwargs):
        if self.fail_photo or (self.fail_reply_photo and kwargs.get("reply_to_message_id")):
            raise TelegramError("photo failed")
        self.sent_photos.append(kwargs)
        self.next_message_id += 1
        return SimpleNamespace(message_id=self.next_message_id)


class FakeChannelRepo:
    def __init__(self, channels=None):
        self.channels = channels or [
            {
                "chat_id": "-1001",
                "forward_with_buttons": True,
                "message_thread_id": 456,
            }
        ]

    async def get_signal_channels(self):
        return self.channels


class FakeSignalRecordRepo:
    def __init__(self):
        self.messages = []

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
            "signal_record_id": signal_record_id,
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
            "telegram_message_id": telegram_message_id,
            "sent_as": sent_as,
        }
        self.messages.append(message)
        return message


def make_signal():
    return SignalDraft(
        symbol="BTCUSDT",
        direction="long",
        entry_lower=100,
        entry_upper=102,
        stop_loss=95,
        take_profit_levels=[108, 110],
    )


def make_service(channel_repo=None, signal_record_repo=None):
    return SignalDeliveryService(channel_repo or FakeChannelRepo(), signal_record_repo or FakeSignalRecordRepo())


@pytest.mark.asyncio
async def test_forward_signal_to_channels_sends_photo_and_records_message_id():
    bot = FakeBot()
    record_repo = FakeSignalRecordRepo()
    service = make_service(signal_record_repo=record_repo)

    result = await service.forward_signal_to_channels(
        bot,
        make_signal(),
        "signal text",
        b"png",
        "generated",
        None,
        signal_record_id=9,
    )

    assert result["sent_count"] == 1
    assert result["chart_send_fallback_count"] == 0
    assert bot.sent_photos[0]["chat_id"] == "-1001"
    assert bot.sent_photos[0]["message_thread_id"] == 456
    assert bot.sent_photos[0]["parse_mode"] == "HTML"
    assert record_repo.messages == [
        {
            "signal_record_id": 9,
            "chat_id": "-1001",
            "message_thread_id": 456,
            "telegram_message_id": 101,
            "sent_as": "photo",
        }
    ]


@pytest.mark.asyncio
async def test_forward_signal_to_channels_falls_back_to_text_when_photo_fails():
    bot = FakeBot()
    bot.fail_photo = True
    service = make_service()

    result = await service.forward_signal_to_channels(
        bot,
        make_signal(),
        "signal text",
        b"png",
        "generated",
        None,
    )

    assert result["sent_count"] == 1
    assert result["chart_send_fallback_count"] == 1
    assert bot.sent_messages[0]["text"] == "signal text"
    assert bot.sent_messages[0]["message_thread_id"] == 456
    assert bot.sent_messages[0]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_forward_signal_to_channels_sends_short_caption_and_full_text_when_caption_is_too_long():
    bot = FakeBot()
    service = make_service()
    long_signal_text = "x" * (TELEGRAM_PHOTO_CAPTION_LIMIT + 10)

    result = await service.forward_signal_to_channels(
        bot,
        make_signal(),
        long_signal_text,
        b"png",
        "generated",
        None,
        signal_record_id=9,
    )

    assert result["sent_count"] == 1
    assert bot.sent_photos[0]["caption"].startswith("🚨 <b>交易信号</b>")
    assert bot.sent_photos[0]["parse_mode"] == "HTML"
    assert bot.sent_messages[0]["text"] == long_signal_text
    assert bot.sent_messages[0]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_forward_chart_update_replies_to_original_message():
    bot = FakeBot()
    service = make_service()

    result = await service.forward_chart_update_to_original_targets(
        bot,
        b"png",
        "update text",
        [
            {
                "chat_id": "-1001",
                "message_thread_id": 456,
                "telegram_message_id": 777,
            }
        ],
    )

    assert result["sent_count"] == 1
    assert result["reply_fallback_count"] == 0
    assert bot.sent_photos[0]["reply_to_message_id"] == 777
    assert bot.sent_photos[0]["message_thread_id"] == 456
    assert bot.sent_photos[0]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_forward_chart_update_falls_back_to_regular_topic_send_when_reply_fails():
    bot = FakeBot()
    bot.fail_reply_photo = True
    service = make_service()

    result = await service.forward_chart_update_to_original_targets(
        bot,
        b"png",
        "update text",
        [
            {
                "chat_id": "-1001",
                "message_thread_id": 456,
                "telegram_message_id": 777,
            }
        ],
    )

    assert result["sent_count"] == 1
    assert result["reply_fallback_count"] == 1
    assert "reply_to_message_id" not in bot.sent_photos[0]
    assert bot.sent_photos[0]["message_thread_id"] == 456
    assert bot.sent_photos[0]["parse_mode"] == "HTML"


def test_fit_photo_caption_truncates_to_telegram_limit():
    text = "x" * (TELEGRAM_PHOTO_CAPTION_LIMIT + 10)

    caption = SignalDeliveryService.fit_photo_caption(text)

    assert len(caption) <= TELEGRAM_PHOTO_CAPTION_LIMIT
    assert caption.endswith("…")


def test_fit_photo_caption_does_not_cut_inside_html_entity():
    text = "x" * (TELEGRAM_PHOTO_CAPTION_LIMIT - 2) + "&lt;tail"

    caption = SignalDeliveryService.fit_photo_caption(text)

    assert len(caption) <= TELEGRAM_PHOTO_CAPTION_LIMIT
    assert not caption.endswith("&…")
    assert caption.endswith("…")
