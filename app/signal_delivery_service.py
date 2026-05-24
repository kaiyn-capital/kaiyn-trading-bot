import logging
from io import BytesIO

from telegram.error import TelegramError

from .bot_keyboards import signal_order_keyboard
from .order_types import SignalDraft
from .telegram_formatting import HTML_PARSE_MODE, html_escape

logger = logging.getLogger(__name__)

TELEGRAM_PHOTO_CAPTION_LIMIT = 1024


class SignalDeliveryService:
    """Telegram delivery for signal broadcasts and chart updates."""

    def __init__(self, channel_repo, signal_record_repo):
        self.channel_repo = channel_repo
        self.signal_record_repo = signal_record_repo

    async def forward_signal_to_channels(
        self,
        bot,
        signal: SignalDraft,
        signal_text: str,
        chart_bytes: bytes | None,
        chart_status: str,
        chart_error: str | None,
        signal_record_id: int | None = None,
        signal_public_id: str | None = None,
    ) -> dict:
        reply_markup = signal_order_keyboard(signal_public_id or "unknown")

        sent_to_channels = 0
        failed_channels = 0
        chart_send_fallback_count = 0
        target_count = 0
        channel_error = None
        try:
            channels_data = await self.channel_repo.get_signal_channels()
            target_count = len(channels_data)

            for channel_data in channels_data:
                try:
                    channel_markup = reply_markup if channel_data["forward_with_buttons"] else None
                    send_kwargs = {}
                    if channel_data.get("message_thread_id"):
                        send_kwargs["message_thread_id"] = channel_data["message_thread_id"]

                    send_result = await self._send_channel_signal(
                        bot,
                        channel_data["chat_id"],
                        signal,
                        signal_text,
                        channel_markup,
                        chart_bytes,
                        send_kwargs,
                    )
                    if send_result["used_fallback"]:
                        chart_send_fallback_count += 1
                    if signal_record_id and send_result.get("message_id"):
                        await self.signal_record_repo.add_channel_message(
                            signal_record_id=signal_record_id,
                            chat_id=str(channel_data["chat_id"]),
                            message_thread_id=channel_data.get("message_thread_id"),
                            telegram_message_id=send_result["message_id"],
                            sent_as=send_result["sent_as"],
                        )
                    sent_to_channels += 1
                except TelegramError as e:
                    failed_channels += 1
                    logger.warning(
                        "Failed to send signal to channel "
                        f"{channel_data['chat_id']} "
                        f"thread={channel_data.get('message_thread_id')}: {e}"
                    )
                except Exception as e:
                    failed_channels += 1
                    logger.exception(
                        "Unexpected error while sending signal to channel "
                        f"{channel_data['chat_id']} "
                        f"thread={channel_data.get('message_thread_id')}: {e}"
                    )

        except Exception as e:
            channel_error = type(e).__name__
            logger.exception("Error getting channels: %s", e)

        return {
            "status": "completed" if channel_error is None else "completed_with_channel_lookup_error",
            "target_count": target_count,
            "sent_count": sent_to_channels,
            "failed_count": failed_channels,
            "chart_status": chart_status,
            "chart_error": chart_error,
            "chart_send_fallback_count": chart_send_fallback_count,
            "reason": channel_error,
        }

    async def forward_chart_update_to_original_targets(
        self,
        bot,
        chart_bytes: bytes,
        update_text: str,
        target_messages: list[dict],
    ) -> dict:
        sent_count = 0
        failed_count = 0
        reply_fallback_count = 0
        caption = self.fit_photo_caption(update_text)

        for target in target_messages:
            send_kwargs = {}
            if target.get("message_thread_id"):
                send_kwargs["message_thread_id"] = target["message_thread_id"]

            try:
                await self._send_chart_update_photo(
                    bot,
                    target["chat_id"],
                    chart_bytes,
                    caption,
                    reply_to_message_id=target["telegram_message_id"],
                    send_kwargs=send_kwargs,
                )
                sent_count += 1
            except TelegramError as e:
                logger.warning(
                    "Failed to send chart update as reply to channel %s message=%s: %s",
                    target["chat_id"],
                    target["telegram_message_id"],
                    e,
                )
                try:
                    await self._send_chart_update_photo(
                        bot,
                        target["chat_id"],
                        chart_bytes,
                        caption,
                        reply_to_message_id=None,
                        send_kwargs=send_kwargs,
                    )
                    reply_fallback_count += 1
                    sent_count += 1
                except TelegramError as fallback_error:
                    failed_count += 1
                    logger.warning(
                        "Failed to send chart update fallback to channel %s: %s",
                        target["chat_id"],
                        fallback_error,
                    )

        return {
            "status": "completed",
            "target_count": len(target_messages),
            "sent_count": sent_count,
            "failed_count": failed_count,
            "reply_fallback_count": reply_fallback_count,
        }

    async def _send_chart_update_photo(
        self,
        bot,
        chat_id,
        chart_bytes: bytes,
        caption: str,
        reply_to_message_id: int | None,
        send_kwargs: dict,
    ):
        kwargs = dict(send_kwargs)
        if reply_to_message_id is not None:
            kwargs["reply_to_message_id"] = reply_to_message_id

        return await bot.send_photo(
            chat_id=chat_id,
            photo=BytesIO(chart_bytes),
            caption=caption,
            parse_mode=HTML_PARSE_MODE,
            **kwargs,
        )

    async def _send_channel_signal(
        self,
        bot,
        chat_id,
        signal: SignalDraft,
        signal_text: str,
        reply_markup,
        chart_bytes: bytes | None,
        send_kwargs: dict,
    ) -> dict:
        if not chart_bytes:
            message = await bot.send_message(
                chat_id=chat_id,
                text=signal_text,
                reply_markup=reply_markup,
                parse_mode=HTML_PARSE_MODE,
                **send_kwargs,
            )
            return {"used_fallback": False, "message_id": self._extract_message_id(message), "sent_as": "text"}

        try:
            if len(signal_text) <= TELEGRAM_PHOTO_CAPTION_LIMIT:
                message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=BytesIO(chart_bytes),
                    caption=signal_text,
                    reply_markup=reply_markup,
                    parse_mode=HTML_PARSE_MODE,
                    **send_kwargs,
                )
                return {"used_fallback": False, "message_id": self._extract_message_id(message), "sent_as": "photo"}
            else:
                message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=BytesIO(chart_bytes),
                    caption=self._signal_chart_short_caption(signal),
                    reply_markup=reply_markup,
                    parse_mode=HTML_PARSE_MODE,
                    **send_kwargs,
                )
                await bot.send_message(
                    chat_id=chat_id,
                    text=signal_text,
                    parse_mode=HTML_PARSE_MODE,
                    **send_kwargs,
                )
                return {"used_fallback": False, "message_id": self._extract_message_id(message), "sent_as": "photo"}
        except TelegramError as e:
            logger.warning("Failed to send signal chart to channel %s, falling back to text: %s", chat_id, e)
            message = await bot.send_message(
                chat_id=chat_id,
                text=signal_text,
                reply_markup=reply_markup,
                parse_mode=HTML_PARSE_MODE,
                **send_kwargs,
            )
            return {"used_fallback": True, "message_id": self._extract_message_id(message), "sent_as": "text"}

    @staticmethod
    def _extract_message_id(message) -> int | None:
        if message is None:
            return None
        return getattr(message, "message_id", None)

    @staticmethod
    def fit_photo_caption(text: str) -> str:
        if len(text) <= TELEGRAM_PHOTO_CAPTION_LIMIT:
            return text
        truncated = text[: TELEGRAM_PHOTO_CAPTION_LIMIT - 1]
        last_amp = truncated.rfind("&")
        last_semicolon = truncated.rfind(";")
        if last_amp > last_semicolon:
            truncated = truncated[:last_amp]
        last_tag_start = truncated.rfind("<")
        last_tag_end = truncated.rfind(">")
        if last_tag_start > last_tag_end:
            truncated = truncated[:last_tag_start]
        return f"{truncated}…"

    @staticmethod
    def _signal_chart_short_caption(signal: SignalDraft) -> str:
        direction_text = "多 Long" if signal.direction == "long" else "空 Short"
        return (
            f"🚨 <b>交易信号</b>\n\n<b>Symbol：</b> {html_escape(signal.symbol)}\n<b>Direction：</b> {direction_text}"
        )
