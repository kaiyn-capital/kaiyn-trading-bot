import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram.ext import ConversationHandler

from .bitget_errors import classify_bitget_exception
from .bot_sessions import SESSION_EXPIRED_MESSAGE
from .bot_states import WAITING_API_KEY, WAITING_PASSPHRASE, WAITING_SECRET_KEY

logger = logging.getLogger(__name__)


class TelegramApiSetupService:
    """Handle the private-chat Bitget API setup conversation."""

    def __init__(
        self,
        bot: Any = None,
        *,
        user_repo: Any = None,
        trade_manager: Any = None,
        encryption_manager: Any = None,
        session_owner: Any = None,
        get_or_create_user: Callable[[Any], Awaitable[Any]] | None = None,
        log_user_action: Callable[[Any, str], Awaitable[Any]] | None = None,
        record_bitget_failure_alert: Callable[[Any, str, dict | None], Awaitable[Any]] | None = None,
    ):
        if bot is not None:
            self.user_repo = user_repo or getattr(bot, "user_repo", None)
            self.trade_manager = trade_manager or getattr(bot, "trade_manager", None)
            self.encryption_manager = encryption_manager or getattr(bot, "encryption_manager", None)
            self.session_owner = session_owner or bot
            self.get_or_create_user = get_or_create_user or getattr(bot, "_get_or_create_user", None)
            self.log_user_action = log_user_action or getattr(bot, "_log_user_action", None)
            self.record_bitget_failure_alert = record_bitget_failure_alert or getattr(
                bot, "_record_bitget_failure_alert", None
            )
        else:
            self.user_repo = user_repo
            self.trade_manager = trade_manager
            self.encryption_manager = encryption_manager
            self.session_owner = session_owner
            self.get_or_create_user = get_or_create_user
            self.log_user_action = log_user_action
            self.record_bitget_failure_alert = record_bitget_failure_alert

    async def set_api_key(self, update, context):
        """Store API key during setup."""
        user = await self.get_or_create_user(update)
        if await self.session_owner._reply_if_session_expired(update, user.telegram_id):
            return ConversationHandler.END

        session = self.session_owner.get_active_user_session(user.telegram_id)
        if not session:
            await update.message.reply_text(SESSION_EXPIRED_MESSAGE)
            return ConversationHandler.END

        api_key = update.message.text.strip()

        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete API key message: {e}")

        if not api_key or len(api_key) < 10:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ API Key 格式不正确，请重新输入：",
            )
            self.session_owner.update_user_session(user.telegram_id, {"step": "api_key"})
            return WAITING_API_KEY

        self.session_owner.update_user_session(user.telegram_id, {"api_key": api_key, "step": "secret_key"})

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ API Key 已保存\n\n**第 2 步：Secret Key**\n请发送您的 Secret Key",
        )

        return WAITING_SECRET_KEY

    async def set_secret_key(self, update, context):
        """Store secret key during setup."""
        user = await self.get_or_create_user(update)
        if await self.session_owner._reply_if_session_expired(update, user.telegram_id):
            return ConversationHandler.END

        session = self.session_owner.get_active_user_session(user.telegram_id)
        if not session:
            await update.message.reply_text(SESSION_EXPIRED_MESSAGE)
            return ConversationHandler.END

        secret_key = update.message.text.strip()

        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete secret key message: {e}")

        if not secret_key or len(secret_key) < 10:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Secret Key 格式不正确，请重新输入：",
            )
            self.session_owner.update_user_session(user.telegram_id, {"step": "secret_key"})
            return WAITING_SECRET_KEY

        self.session_owner.update_user_session(user.telegram_id, {"secret_key": secret_key, "step": "passphrase"})

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Secret Key 已保存\n\n**第 3 步：Passphrase**\n请发送您的 Passphrase",
        )

        return WAITING_PASSPHRASE

    async def set_passphrase(self, update, context):
        """Store passphrase and finish API setup."""
        user = await self.get_or_create_user(update)
        if await self.session_owner._reply_if_session_expired(update, user.telegram_id):
            return ConversationHandler.END

        session = self.session_owner.get_active_user_session(user.telegram_id)
        if not session:
            await update.message.reply_text(SESSION_EXPIRED_MESSAGE)
            return ConversationHandler.END

        passphrase = update.message.text.strip()

        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete passphrase message: {e}")

        if not passphrase:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Passphrase 不能为空，请重新输入：",
            )
            self.session_owner.update_user_session(user.telegram_id, {"step": "passphrase"})
            return WAITING_PASSPHRASE

        api_key = session.get("api_key")
        secret_key = session.get("secret_key")

        if not all([api_key, secret_key]):
            self.session_owner.delete_user_session(user.telegram_id)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ 设置过程中出现错误，请重新开始。",
            )
            return ConversationHandler.END

        try:
            test_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🔄 正在测试 API 连接...")

            credentials = self.encryption_manager.encrypt_api_credentials(api_key, secret_key, passphrase)
            is_connected, message = await self.trade_manager.test_api_connection(credentials)

            if is_connected:
                await self.user_repo.update_user_api_credentials(
                    user.id, credentials[0], credentials[1], credentials[2]
                )
                await self.trade_manager.invalidate_user_client(user.id)

                await self.log_user_action(user, "api_setup_success")

                await test_msg.edit_text(
                    "✅ **API 设置成功！**\n\n"
                    "您的 API 密钥已加密保存，现在可以开始使用交易功能。\n\n"
                    "使用 `/status` 检查连接状态\n"
                    "使用 `/settings` 设置交易参数（1R愿意承受止损金额）",
                    parse_mode="Markdown",
                )
            else:
                await test_msg.edit_text(
                    f"❌ **API 连接测试失败**\n\n错误信息: {message}\n\n请检查您的 API 凭证是否正确，然后重新设置。",
                    parse_mode="Markdown",
                )

        except Exception as e:
            logger.error(f"API setup failed: {e}")
            classified = classify_bitget_exception(e)
            await self.record_bitget_failure_alert(classified, "set_passphrase", {"telegram_id": user.telegram_id})
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ {classified.user_message}",
            )

        finally:
            self.session_owner.delete_user_session(user.telegram_id)

        return ConversationHandler.END
