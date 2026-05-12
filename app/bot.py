import asyncio
import logging
from typing import Dict, Optional

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .bitget_api import BitgetTradeManager
from .bot_account_handlers import AccountHandlersMixin
from .bot_admin_handlers import AdminHandlersMixin
from .bot_order_handlers import OrderHandlersMixin
from .bot_states import WAITING_API_KEY, WAITING_PASSPHRASE, WAITING_SECRET_KEY
from .config import Config
from .database import (
    get_channel_repo,
    get_notification_repo,
    get_pending_order_repo,
    get_system_log_repo,
    get_trade_repo,
    get_user_repo,
)
from .encryption import create_encryption_manager
from .models import User

logger = logging.getLogger(__name__)


class TelegramBot(AccountHandlersMixin, AdminHandlersMixin, OrderHandlersMixin):
    """Telegram bot entry point and handler registry."""

    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN

        self.user_repo = get_user_repo()
        self.trade_repo = get_trade_repo()
        self.pending_order_repo = get_pending_order_repo()
        self.notification_repo = get_notification_repo()
        self.system_log_repo = get_system_log_repo()
        self.channel_repo = get_channel_repo()

        self.encryption_manager = create_encryption_manager(Config.ENCRYPTION_KEY)
        self.trade_manager = BitgetTradeManager(self.encryption_manager)
        self.user_sessions: Dict[int, Dict] = {}

        self.application = Application.builder().token(self.token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        """Register Telegram handlers."""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("balance", self.balance_command))
        self.application.add_handler(CommandHandler("settings", self.settings_command))

        api_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("setapi", self.set_api_start)],
            states={
                WAITING_API_KEY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_api_key)
                ],
                WAITING_SECRET_KEY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_secret_key)
                ],
                WAITING_PASSPHRASE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_passphrase)
                ],
            },
            fallbacks=[],
        )
        self.application.add_handler(api_conv_handler)

        self.application.add_handler(CommandHandler("admin", self.admin_command))
        self.application.add_handler(
            CommandHandler("admin_users", self.admin_users_command)
        )
        self.application.add_handler(
            CommandHandler("admin_broadcast", self.admin_broadcast_command)
        )
        self.application.add_handler(
            CommandHandler("admin_channels", self.admin_channels_command)
        )
        self.application.add_handler(
            CommandHandler("add_channel", self.add_channel_command)
        )
        self.application.add_handler(
            CommandHandler("send_signal", self.send_signal_command)
        )
        self.application.add_handler(
            CommandHandler("send_to_channel", self.send_to_channel_command)
        )
        self.application.add_handler(
            CommandHandler("add_trader", self.add_trader_command)
        )

        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, self.handle_global_message, block=False
            )
        )
        self.application.add_error_handler(self.error_handler)

        asyncio.create_task(self.setup_commands())

    async def setup_commands(self):
        """Set Telegram command menu."""
        commands = [
            BotCommand("start", "开始使用机器人"),
            BotCommand("help", "查看帮助信息"),
            BotCommand("setapi", "设置 Bitget API"),
            BotCommand("status", "查看连接状态"),
            BotCommand("balance", "查看账户余额"),
            BotCommand("settings", "交易设置"),
        ]

        try:
            await self.application.bot.set_my_commands(commands)
            logger.info("Bot commands set successfully")
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")

    async def _get_or_create_user(self, update: Update) -> User:
        """Get or create the current Telegram user."""
        telegram_user = update.effective_user
        user = await self.user_repo.get_user_by_telegram_id(telegram_user.id)

        if not user:
            user = await self.user_repo.create_user(
                telegram_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
            )
            logger.info(f"New user created: {telegram_user.id}")

        return user

    async def _is_trader_or_admin(self, telegram_id: int) -> bool:
        """Check whether a user can send trading signals."""
        if Config.is_admin(telegram_id):
            return True

        try:
            return await self.user_repo.is_active_trader(telegram_id)
        except Exception as e:
            logger.error(f"Check trader status error: {e}")
            return False

    def _get_sender_username(self, update: Update) -> str:
        """Return a readable Telegram sender name."""
        if update.effective_user and update.effective_user.username:
            return update.effective_user.username
        elif update.effective_user:
            return update.effective_user.first_name or "Unknown"
        return "Unknown"

    async def _log_user_action(
        self, user: User, action: str, details: Optional[Dict] = None
    ):
        """Persist an audit-style user action log."""
        try:
            await self.system_log_repo.log(
                level="INFO",
                message=f"User action: {action}",
                module="telegram_bot",
                user_id=user.id if hasattr(user, "id") and user.id else None,
                telegram_id=user.telegram_id,
                extra_data=details or {},
            )
        except Exception as e:
            logger.error(f"Failed to log user action: {e}")
            await self.system_log_repo.log(
                level="INFO",
                message=f"User action: {action}",
                module="telegram_bot",
                telegram_id=user.telegram_id,
                extra_data=details or {},
            )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route all inline keyboard callbacks."""
        query = update.callback_query
        await query.answer()

        user = await self._get_or_create_user(update)
        data = query.data

        try:
            if data == "setup_api":
                await self._handle_setup_api_callback(query, user)
            elif data == "check_status":
                await self._handle_status_callback(query, user)
            elif data == "check_balance" or data == "refresh_balance":
                await self._handle_balance_callback(query, user)
            elif data == "trading_settings":
                await self._handle_trading_settings_callback(query, user)
            elif data == "set_risk_amount":
                await self._handle_set_risk_start_callback(query, user)
            elif data.startswith("place_order_"):
                await self._handle_place_order_callback(query, user, data)
            elif data == "confirm_modify_api":
                await self._handle_confirm_modify_api(query, user)
            elif data == "cancel_modify_api":
                await query.answer("已取消")
                await query.edit_message_text("✅ 已取消修改 API 设置")
            elif data == "confirm_change_risk":
                await self._handle_confirm_change_risk(query, user)
            elif data == "cancel_change_risk":
                await query.answer("已取消")
                self.user_sessions.pop(user.telegram_id, None)
                await query.edit_message_text("✅ 已取消更改风险设置")
            elif data == "return_start":
                await self._handle_return_start_callback(query, user)
            elif data.startswith("confirm_order_"):
                await self._handle_confirm_pending_order_callback(query, user, data)
            elif data.startswith("cancel_order_"):
                await self._handle_cancel_pending_order_callback(query, user, data)
            elif data == "cancel_order":
                await query.answer("已取消下单")
                await self._send_private_message(query, user, "✅ 已取消下单")
            elif data == "add_new_channel":
                await self._handle_add_new_channel_callback(query, user)
            elif data == "manage_channels":
                await self._handle_manage_channels_callback(query, user)
            elif data == "delete_channel_start":
                await self._handle_delete_channel_start_callback(query, user)
            elif data == "return_admin_channels":
                await self._handle_return_admin_channels_callback(query, user)
            else:
                await query.edit_message_text("❓ 未知操作")

        except Exception as e:
            logger.error(f"Button callback error: {e}")
            await query.edit_message_text("❌ 操作失败，请重试")

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle uncaught Telegram update errors."""
        logger.error(f"Update {update} caused error {context.error}")

        user_id = None
        telegram_id = None

        try:
            if update and update.effective_user:
                telegram_id = update.effective_user.id
                user = await self.user_repo.get_user_by_telegram_id(telegram_id)
                if user and hasattr(user, "id"):
                    user_id = user.id
        except Exception as e:
            logger.error(f"Error getting user info for error handler: {e}")

        try:
            await self.system_log_repo.log(
                level="ERROR",
                message=str(context.error),
                module="telegram_bot",
                function="error_handler",
                user_id=user_id,
                telegram_id=telegram_id,
                stack_trace=(
                    str(context.error.__traceback__)
                    if context.error.__traceback__
                    else None
                ),
            )
        except Exception as e:
            logger.error(f"Failed to log error: {e}")

        if update and update.effective_chat:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ 系统发生错误，请稍后重试。如问题持续，请联系管理员。",
                )
            except Exception:
                pass

    async def start(self):
        """Start the Telegram bot."""
        try:
            Config.validate()
            logger.info("Starting Telegram bot...")

            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(
                poll_interval=1.0,
                timeout=20,
                read_timeout=20,
                write_timeout=20,
                connect_timeout=20,
            )

            logger.info("Telegram bot started successfully")

        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            raise

    async def stop(self):
        """Stop the Telegram bot."""
        try:
            logger.info("Stopping Telegram bot...")

            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

            await self.trade_manager.cleanup()
            await self.user_repo.db.close()

            logger.info("Telegram bot stopped successfully")

        except Exception as e:
            logger.error(f"Error stopping bot: {e}")


def create_bot() -> TelegramBot:
    """Create a bot instance."""
    return TelegramBot()


async def run_bot():
    """Run the bot until SIGTERM or SIGINT."""
    bot = create_bot()
    try:
        await bot.start()
        import signal

        stop_event = asyncio.Event()

        def signal_handler():
            stop_event.set()

        for sig in [signal.SIGTERM, signal.SIGINT]:
            signal.signal(sig, lambda s, f: signal_handler())

        await stop_event.wait()

    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await bot.stop()
