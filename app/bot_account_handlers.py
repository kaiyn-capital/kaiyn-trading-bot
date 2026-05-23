import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from .bitget_errors import classify_bitget_exception
from .bot_account_formatters import format_usdt_balance_text
from .bot_api_setup_service import TelegramApiSetupService
from .bot_keyboards import (
    main_menu_keyboard,
    status_actions_keyboard,
    trading_settings_keyboard,
)
from .bot_messages import help_message, settings_message, welcome_message
from .bot_sessions import SESSION_EXPIRED_MESSAGE, UserSessionMixin
from .bot_states import WAITING_API_KEY
from .decimal_utils import decimal_text, to_decimal
from .log_sanitizer import summarize_balance_response

logger = logging.getLogger(__name__)


class AccountHandlers:
    """Standalone use-case coordinator for user accounts."""

    def __init__(self, bot):
        self.bot = bot

    def _api_setup_service(self) -> TelegramApiSetupService:
        return TelegramApiSetupService(self.bot)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start."""
        user = await self.bot._get_or_create_user(update)
        await self.bot._log_user_action(user, "start_command")

        await update.message.reply_text(welcome_message(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help."""
        await update.message.reply_text(help_message(), parse_mode="Markdown")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status."""
        user = await self.bot._get_or_create_user(update)
        await self.bot._log_user_action(user, "status_command")

        if not user.is_api_connected or not all(
            [
                user.encrypted_api_key,
                user.encrypted_secret_key,
                user.encrypted_passphrase,
            ]
        ):
            await update.message.reply_text(
                "❌ API 未连接\n\n请先使用 `/setapi` 命令设置您的 Bitget API 密钥。",
                parse_mode="Markdown",
            )
            return

        try:
            credentials = (
                user.encrypted_api_key,
                user.encrypted_secret_key,
                user.encrypted_passphrase,
            )
            is_connected, message = await self.bot.trade_manager.test_api_connection(credentials)

            if is_connected:
                bitget_uid = await self.bot.trade_manager.get_user_uid(credentials)
                status_text = f"""Bitget UID: {bitget_uid}\n✅ **API 连接状态：正常**"""

                await update.message.reply_text(
                    status_text,
                    reply_markup=status_actions_keyboard(),
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    f"❌ **API 连接失败**\n\n错误信息: {message}\n\n请检查您的 API 设置或重新配置。",
                    parse_mode="Markdown",
                )

        except Exception as e:
            logger.error(f"Status check failed: {e}")
            classified = classify_bitget_exception(e)
            await self.bot._record_bitget_failure_alert(classified, "status_command", {"telegram_id": user.telegram_id})
            await update.message.reply_text(f"❌ {classified.user_message}")

    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balance."""
        user = await self.bot._get_or_create_user(update)
        await self.bot._log_user_action(user, "balance_command")

        if not user.is_api_connected:
            await update.message.reply_text("❌ 请先设置 API 连接。使用 `/setapi` 命令。")
            return

        try:
            credentials = (
                user.encrypted_api_key,
                user.encrypted_secret_key,
                user.encrypted_passphrase,
            )

            logger.info(
                "Getting balance for user_id=%s telegram_id=%s",
                user.id,
                user.telegram_id,
            )
            balance_data = await self.bot.trade_manager.get_account_balance(user.id, credentials)
            logger.info(
                "Account balance summary: user_id=%s telegram_id=%s summary=%s",
                user.id,
                user.telegram_id,
                summarize_balance_response(balance_data),
            )

            if balance_data.get("code") == "00000" and balance_data.get("data"):
                assets = balance_data["data"]
                balance_text = format_usdt_balance_text(assets, raw_limit=500, compact=True)

                keyboard = [
                    [InlineKeyboardButton("🔄 刷新余额", callback_data="refresh_balance")],
                    [InlineKeyboardButton("🏠 返回", callback_data="return_start")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(balance_text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ 获取余额失败，请检查 API 设置。")

        except Exception as e:
            logger.error(f"Balance check failed: {e}")
            classified = classify_bitget_exception(e)
            await self.bot._record_bitget_failure_alert(
                classified, "balance_command", {"telegram_id": user.telegram_id}
            )
            await update.message.reply_text(f"❌ {classified.user_message}")

    async def set_api_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start API setup."""
        user = await self.bot._get_or_create_user(update)
        await self.bot._log_user_action(user, "set_api_start")

        if user.is_api_connected and user.encrypted_api_key:
            keyboard = [
                [InlineKeyboardButton("✅ 确认修改", callback_data="confirm_modify_api")],
                [InlineKeyboardButton("❌ 取消", callback_data="cancel_modify_api")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "🔐 **API 设置**\n\n您已经设置完成 Bitget API 连接。\n\n是否要修改现有的 API 设置？",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        self.bot.set_user_session(user.telegram_id, {"step": "api_key"})

        await update.message.reply_text(
            "🔐 **设置 Bitget API**\n\n"
            "请按顺序提供您的 API 信息。\n\n"
            "**第 1 步：API Key**\n"
            "请发送您的 Bitget API Key\n\n"
            "💡 提示：您可以在 Bitget 官网的 API 管理页面获取",
            parse_mode="Markdown",
        )

        return WAITING_API_KEY

    async def set_api_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Store API key during setup."""
        return await self._api_setup_service().set_api_key(update, context)

    async def set_secret_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Store secret key during setup."""
        return await self._api_setup_service().set_secret_key(update, context)

    async def set_passphrase(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Store passphrase and finish API setup."""
        return await self._api_setup_service().set_passphrase(update, context)

    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings."""
        user = await self.bot._get_or_create_user(update)
        await self.bot._log_user_action(user, "settings_command")

        await update.message.reply_text(
            settings_message(getattr(user, "fixed_risk_amount", None)),
            reply_markup=trading_settings_keyboard(),
            parse_mode="Markdown",
        )

    async def _handle_set_risk_start_callback(self, query, user):
        """Start fixed risk amount setup from a callback."""
        current_risk = getattr(user, "fixed_risk_amount", None)

        if current_risk is None:
            self.bot.set_user_session(user.telegram_id, {"step": "risk_amount"})

            await query.edit_message_text(
                "💰 **设置每单固定止损金额，以进行定 R 开仓。**\n\n请输入定 R 金额 u（数字）：",
                parse_mode="Markdown",
            )
        else:
            keyboard = [
                [InlineKeyboardButton("✅ 确认更改", callback_data="confirm_change_risk")],
                [InlineKeyboardButton("❌ 取消", callback_data="cancel_change_risk")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"💰 **设置每单固定止损金额，以进行定 R 开仓。**\n\n您目前已设置定损为 {current_risk} USDT，要更改吗？",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )

    async def set_risk_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Store fixed risk amount."""
        user = await self.bot._get_or_create_user(update)
        if await self.bot._reply_if_session_expired(update, user.telegram_id):
            return

        if not self.bot.get_active_user_session(user.telegram_id):
            await update.message.reply_text(SESSION_EXPIRED_MESSAGE)
            return

        amount_text = update.message.text.strip()

        try:
            amount = to_decimal(amount_text)
            if amount <= 0:
                raise ValueError("金额必须大于 0")

            success = await self.bot.user_repo.update_user_risk_amount(user.id, amount)

            if success:
                await update.message.reply_text(
                    f"✅ **已设置定 R 止损为 {decimal_text(amount)} USDT**",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("❌ 设置失败，请重试")

            self.bot.delete_user_session(user.telegram_id)
            return

        except ValueError:
            await update.message.reply_text("❌ 输入格式不正确，请输入有效数字：\n\n例如：50 或 100.5")
            self.bot.update_user_session(user.telegram_id, {"step": "risk_amount"})
            return

    async def handle_global_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route plain text messages for active setup sessions."""
        chat = getattr(update, "effective_chat", None)
        chat_type = getattr(chat, "type", None)
        if not (chat_type == "private" or getattr(chat_type, "value", None) == "private"):
            return

        user = await self.bot._get_or_create_user(update)

        if await self.bot._reply_if_session_expired(update, user.telegram_id):
            return

        session = self.bot.get_active_user_session(user.telegram_id)
        if session:
            step = session.get("step")

            if step == "api_key":
                await self.set_api_key(update, context)
                return
            elif step == "secret_key":
                await self.set_secret_key(update, context)
                return
            elif step == "passphrase":
                await self.set_passphrase(update, context)
                return
            elif step == "risk_amount":
                await self.set_risk_amount(update, context)
                return
            elif step == "delete_channel":
                await self.bot.delete_channel_by_number(update, context)
                return

    async def _handle_setup_api_callback(self, query, user):
        """Handle setup API callback."""
        if user.is_api_connected and user.encrypted_api_key:
            keyboard = [
                [InlineKeyboardButton("✅ 确认修改", callback_data="confirm_modify_api")],
                [InlineKeyboardButton("❌ 取消", callback_data="cancel_modify_api")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "🔐 **API 设置**\n\n您已经设置完成 Bitget API 连接。\n\n是否要修改现有的 API 设置？",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return

        self.bot.set_user_session(user.telegram_id, {"step": "api_key"})

        await query.edit_message_text(
            "🔐 **设置 Bitget API**\n\n"
            "请按顺序提供您的 API 信息。\n\n"
            "**第 1 步：API Key**\n"
            "请发送您的 Bitget API Key\n\n"
            "💡 提示：您可以在 Bitget 官网的 API 管理页面获取",
            parse_mode="Markdown",
        )

    async def _handle_status_callback(self, query, user):
        """Handle status callback."""
        if not user.is_api_connected:
            await query.edit_message_text(
                "❌ API 未连接\n\n请先使用 `/setapi` 命令设置您的 API。",
                parse_mode="Markdown",
            )
            return

        try:
            credentials = (
                user.encrypted_api_key,
                user.encrypted_secret_key,
                user.encrypted_passphrase,
            )
            is_connected, message = await self.bot.trade_manager.test_api_connection(credentials)

            if is_connected:
                bitget_uid = await self.bot.trade_manager.get_user_uid(credentials)
                status_text = f"Bitget UID: {bitget_uid}\n✅ **API 连接状态：正常**"
                await query.edit_message_text(status_text, parse_mode="Markdown")
            else:
                await query.edit_message_text(f"❌ **API 连接失败**\n\n{message}", parse_mode="Markdown")

        except Exception as e:
            classified = classify_bitget_exception(e)
            await self.bot._record_bitget_failure_alert(
                classified, "status_callback", {"telegram_id": user.telegram_id}
            )
            await query.edit_message_text(f"❌ {classified.user_message}")

    async def _handle_balance_callback(self, query, user):
        """Handle balance callback."""
        if not user.is_api_connected:
            await query.edit_message_text("❌ 请先设置 API 连接")
            return

        try:
            await query.edit_message_text("🔄 正在查询余额...")

            credentials = (
                user.encrypted_api_key,
                user.encrypted_secret_key,
                user.encrypted_passphrase,
            )
            balance_data = await self.bot.trade_manager.get_account_balance(user.id, credentials)
            logger.info(
                "Account balance refresh summary: user_id=%s telegram_id=%s summary=%s",
                user.id,
                user.telegram_id,
                summarize_balance_response(balance_data),
            )

            if balance_data.get("code") == "00000" and balance_data.get("data"):
                assets = balance_data["data"]
                balance_text = format_usdt_balance_text(assets, raw_limit=300, compact=False)

                keyboard = [
                    [InlineKeyboardButton("🔄 刷新", callback_data="refresh_balance")],
                    [InlineKeyboardButton("🏠 返回", callback_data="return_start")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(balance_text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await query.edit_message_text("❌ 获取余额失败")

        except Exception as e:
            classified = classify_bitget_exception(e)
            await self.bot._record_bitget_failure_alert(
                classified, "balance_callback", {"telegram_id": user.telegram_id}
            )
            await query.edit_message_text(f"❌ {classified.user_message}")

    async def _handle_return_start_callback(self, query, user):
        """Handle return-to-start callback."""
        await query.edit_message_text(welcome_message(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    async def _handle_trading_settings_callback(self, query, user):
        """Handle trading settings callback."""
        await query.edit_message_text(
            settings_message(getattr(user, "fixed_risk_amount", None)),
            reply_markup=trading_settings_keyboard(include_return=True),
            parse_mode="Markdown",
        )

    async def _handle_confirm_modify_api(self, query, user):
        """Handle API modification confirmation."""
        self.bot.set_user_session(user.telegram_id, {"step": "api_key"})

        await query.edit_message_text(
            "🔐 **修改 Bitget API**\n\n"
            "请按顺序提供您的新 API 信息。\n\n"
            "**第 1 步：API Key**\n"
            "请发送您的 Bitget API Key",
            parse_mode="Markdown",
        )
        return WAITING_API_KEY

    async def _handle_confirm_change_risk(self, query, user):
        """Handle fixed risk amount change confirmation."""
        self.bot.set_user_session(user.telegram_id, {"step": "risk_amount"})

        await query.edit_message_text(
            "💰 **设置每单固定止损金额，以进行定 R 开仓。**\n\n请输入定 R 金额 u（数字）：",
            parse_mode="Markdown",
        )


class AccountHandlersMixin(UserSessionMixin):
    @property
    def account_handlers(self) -> AccountHandlers:
        if not hasattr(self, "_account_handlers_delegate"):
            self._account_handlers_delegate = AccountHandlers(self)
        return self._account_handlers_delegate

    @account_handlers.setter
    def account_handlers(self, value: AccountHandlers):
        self._account_handlers_delegate = value

    async def _record_bitget_failure_alert(self, classified_error, source: str, details: dict | None = None):
        return None

    def _api_setup_service(self) -> TelegramApiSetupService:
        return self.account_handlers._api_setup_service()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.account_handlers.start_command(update, context)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.account_handlers.help_command(update, context)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.account_handlers.status_command(update, context)

    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.account_handlers.balance_command(update, context)

    async def set_api_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        return await self.account_handlers.set_api_start(update, context)

    async def set_api_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        return await self.account_handlers.set_api_key(update, context)

    async def set_secret_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        return await self.account_handlers.set_secret_key(update, context)

    async def set_passphrase(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        return await self.account_handlers.set_passphrase(update, context)

    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.account_handlers.settings_command(update, context)

    async def _handle_set_risk_start_callback(self, query, user):
        await self.account_handlers._handle_set_risk_start_callback(query, user)

    async def set_risk_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.account_handlers.set_risk_amount(update, context)

    async def handle_global_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.account_handlers.handle_global_message(update, context)

    async def _handle_setup_api_callback(self, query, user):
        await self.account_handlers._handle_setup_api_callback(query, user)

    async def _handle_status_callback(self, query, user):
        await self.account_handlers._handle_status_callback(query, user)

    async def _handle_balance_callback(self, query, user):
        await self.account_handlers._handle_balance_callback(query, user)

    async def _handle_return_start_callback(self, query, user):
        await self.account_handlers._handle_return_start_callback(query, user)

    async def _handle_trading_settings_callback(self, query, user):
        await self.account_handlers._handle_trading_settings_callback(query, user)

    async def _handle_confirm_modify_api(self, query, user):
        return await self.account_handlers._handle_confirm_modify_api(query, user)

    async def _handle_confirm_change_risk(self, query, user):
        await self.account_handlers._handle_confirm_change_risk(query, user)
