import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .admin_alerts import AdminAlertManager
from .audit import record_audit_event
from .bitget_api import BitgetTradeManager
from .bot_account_handlers import AccountHandlersMixin
from .bot_admin_handlers import AdminHandlersMixin
from .bot_admin_permissions import ADMIN_PERMISSION_DENIED_MESSAGE
from .bot_order_handlers import OrderHandlersMixin
from .bot_states import WAITING_API_KEY, WAITING_PASSPHRASE, WAITING_SECRET_KEY
from .config import Config
from .database import (
    get_channel_repo,
    get_notification_repo,
    get_pending_order_repo,
    get_signal_record_repo,
    get_system_log_repo,
    get_trade_repo,
    get_user_repo,
)
from .encryption import create_encryption_manager
from .health import read_backup_health, read_maintenance_health
from .log_sanitizer import summarize_telegram_update
from .models import User
from .order_reconciliation import PendingOrderReconciliationService

logger = logging.getLogger(__name__)


class TelegramBot(AccountHandlersMixin, AdminHandlersMixin, OrderHandlersMixin):
    """Telegram bot entry point and handler registry."""

    ADMIN_CALLBACKS = frozenset(
        {
            "add_new_channel",
            "manage_channels",
            "delete_channel_start",
            "return_admin_channels",
        }
    )

    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN

        self.user_repo = get_user_repo()
        self.trade_repo = get_trade_repo()
        self.pending_order_repo = get_pending_order_repo()
        self.notification_repo = get_notification_repo()
        self.system_log_repo = get_system_log_repo()
        self.channel_repo = get_channel_repo()
        self.signal_record_repo = get_signal_record_repo()

        self.encryption_manager = create_encryption_manager(Config.ENCRYPTION_KEY)
        self.trade_manager = BitgetTradeManager(self.encryption_manager)
        self.started_at: Optional[datetime] = None
        self.health_monitor_task: Optional[asyncio.Task] = None
        self.user_sessions: Dict[int, Dict] = {}

        self.application = Application.builder().token(self.token).build()
        self.alert_manager = AdminAlertManager(self.application.bot, self.system_log_repo)
        self.pending_order_reconciler = PendingOrderReconciliationService(
            bot=self.application.bot,
            user_repo=self.user_repo,
            pending_order_repo=self.pending_order_repo,
            trade_repo=self.trade_repo,
            trade_manager=self.trade_manager,
            system_log_repo=self.system_log_repo,
            alert_manager=self.alert_manager,
        )
        self._setup_handlers()

    def _setup_handlers(self):
        """Register Telegram handlers."""
        private_chat = filters.ChatType.PRIVATE
        private_text = private_chat & filters.TEXT & ~filters.COMMAND

        self.application.add_handler(CommandHandler("start", self.start_command, filters=private_chat))
        self.application.add_handler(CommandHandler("help", self.help_command, filters=private_chat))
        self.application.add_handler(CommandHandler("status", self.status_command, filters=private_chat))
        self.application.add_handler(CommandHandler("balance", self.balance_command, filters=private_chat))
        self.application.add_handler(CommandHandler("settings", self.settings_command, filters=private_chat))

        api_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("setapi", self.set_api_start, filters=private_chat)],
            states={
                WAITING_API_KEY: [MessageHandler(private_text, self.set_api_key)],
                WAITING_SECRET_KEY: [MessageHandler(private_text, self.set_secret_key)],
                WAITING_PASSPHRASE: [MessageHandler(private_text, self.set_passphrase)],
            },
            fallbacks=[],
        )
        self.application.add_handler(api_conv_handler)

        self.application.add_handler(CommandHandler("admin", self.admin_command, filters=private_chat))
        self.application.add_handler(CommandHandler("admin_health", self.admin_health_command, filters=private_chat))
        self.application.add_handler(CommandHandler("admin_audit", self.admin_audit_command, filters=private_chat))
        self.application.add_handler(CommandHandler("admin_users", self.admin_users_command, filters=private_chat))
        self.application.add_handler(
            CommandHandler("admin_broadcast", self.admin_broadcast_command, filters=private_chat)
        )
        self.application.add_handler(
            CommandHandler("admin_channels", self.admin_channels_command, filters=private_chat)
        )
        self.application.add_handler(CommandHandler("add_channel", self.add_channel_command, filters=private_chat))
        self.application.add_handler(CommandHandler("send_signal", self.send_signal_command, filters=private_chat))
        self.application.add_handler(CommandHandler("update_chart", self.update_chart_command, filters=private_chat))
        self.application.add_handler(
            CommandHandler("send_to_channel", self.send_to_channel_command, filters=private_chat)
        )
        self.application.add_handler(
            CommandHandler("set_channel_topic", self.set_channel_topic_command, filters=private_chat)
        )
        self.application.add_handler(
            CommandHandler("clear_channel_topic", self.clear_channel_topic_command, filters=private_chat)
        )
        self.application.add_handler(CommandHandler("add_trader", self.add_trader_command, filters=private_chat))

        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(MessageHandler(private_text, self.handle_global_message, block=False))
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
            await self.application.bot.delete_my_commands(scope=BotCommandScopeDefault())
            await self.application.bot.delete_my_commands(scope=BotCommandScopeAllGroupChats())
            await self.application.bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
            logger.info("Bot commands set for private chats")
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")

    def _is_private_chat_update(self, update: Update | None) -> bool:
        """Return whether the update came from a one-to-one private chat."""
        chat = getattr(update, "effective_chat", None)
        chat_type = getattr(chat, "type", None)
        return chat_type == "private" or getattr(chat_type, "value", None) == "private"

    def _is_group_order_callback(self, data: str | None) -> bool:
        """Return whether a group callback is allowed to start the order flow."""
        return isinstance(data, str) and data.startswith("place_order_")

    def _is_admin_callback(self, data: str | None) -> bool:
        """Return whether a callback is restricted to admins."""
        return isinstance(data, str) and data in self.ADMIN_CALLBACKS

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

    async def _log_user_action(self, user: User, action: str, details: Optional[Dict] = None):
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

    async def _audit_action(self, user: User, action: str, details: Optional[Dict] = None):
        """Persist an operator audit event."""
        try:
            await record_audit_event(self.system_log_repo, user, action, details or {})
        except Exception as e:
            logger.error(f"Failed to record audit event {action}: {e}")

    async def _record_bitget_failure_alert(self, classified_error, source: str, details: Optional[Dict] = None):
        """Record a classified Bitget failure and alert admins if needed."""
        try:
            await self.alert_manager.record_bitget_failure(
                classified_error,
                source=source,
                context=details or {},
            )
        except Exception as exc:
            logger.error(f"Failed to record Bitget alert: {exc}")

    def _exact_callback_handlers(self):
        return {
            "setup_api": self._handle_setup_api_callback,
            "check_status": self._handle_status_callback,
            "check_balance": self._handle_balance_callback,
            "refresh_balance": self._handle_balance_callback,
            "trading_settings": self._handle_trading_settings_callback,
            "set_risk_amount": self._handle_set_risk_start_callback,
            "confirm_modify_api": self._handle_confirm_modify_api,
            "cancel_modify_api": self._handle_cancel_modify_api_callback,
            "confirm_change_risk": self._handle_confirm_change_risk,
            "cancel_change_risk": self._handle_cancel_change_risk_callback,
            "return_start": self._handle_return_start_callback,
            "cancel_order": self._handle_cancel_order_callback,
            "add_new_channel": self._handle_add_new_channel_callback,
            "manage_channels": self._handle_manage_channels_callback,
            "delete_channel_start": self._handle_delete_channel_start_callback,
            "return_admin_channels": self._handle_return_admin_channels_callback,
        }

    def _prefix_callback_handlers(self):
        return (
            ("confirm_chart_update_", self._handle_confirm_chart_update_callback),
            ("cancel_chart_update_", self._handle_cancel_chart_update_callback),
            ("confirm_signal_", self._handle_confirm_signal_callback),
            ("cancel_signal_", self._handle_cancel_signal_callback),
            ("place_order_", self._handle_place_order_callback),
            ("confirm_order_", self._handle_confirm_pending_order_callback),
            ("cancel_order_", self._handle_cancel_pending_order_callback),
        )

    async def _dispatch_button_callback(self, query, user, data: str | None) -> bool:
        if not isinstance(data, str):
            return False

        exact_handler = self._exact_callback_handlers().get(data)
        if exact_handler:
            await exact_handler(query, user)
            return True

        for prefix, prefix_handler in self._prefix_callback_handlers():
            if data.startswith(prefix):
                await prefix_handler(query, user, data)
                return True

        return False

    async def _handle_cancel_modify_api_callback(self, query, user):
        await query.answer("已取消")
        await query.edit_message_text("✅ 已取消修改 API 设置")

    async def _handle_cancel_change_risk_callback(self, query, user):
        await query.answer("已取消")
        self.user_sessions.pop(user.telegram_id, None)
        await query.edit_message_text("✅ 已取消更改风险设置")

    async def _handle_cancel_order_callback(self, query, user):
        await query.answer("已取消下单")
        await self._send_private_message(query, user, "✅ 已取消下单")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route all inline keyboard callbacks."""
        query = update.callback_query
        data = query.data

        if not self._is_private_chat_update(update) and not self._is_group_order_callback(data):
            await query.answer("请到与机器人的私人聊天操作", show_alert=True)
            return

        user = await self._get_or_create_user(update)

        try:
            if self._is_admin_callback(data) and not self._is_admin_user(user):
                await query.answer(ADMIN_PERMISSION_DENIED_MESSAGE, show_alert=True)
                return

            await query.answer()
            handled = await self._dispatch_button_callback(query, user, data)
            if not handled:
                await query.edit_message_text("❓ 未知操作")

        except Exception as e:
            logger.error(f"Button callback error: {e}")
            if self._is_private_chat_update(update):
                await query.edit_message_text("❌ 操作失败，请重试")
            else:
                try:
                    await query.answer("操作失败，请到与机器人的私人聊天查看或重试", show_alert=True)
                except Exception:
                    pass

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle uncaught Telegram update errors."""
        logger.error(
            "Telegram update error: update_summary=%s error=%s",
            summarize_telegram_update(update),
            context.error,
        )

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
                stack_trace=(str(context.error.__traceback__) if context.error.__traceback__ else None),
            )
        except Exception as e:
            logger.error(f"Failed to log error: {e}")

        if update and update.effective_chat and self._is_private_chat_update(update):
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
            )

            logger.info("Telegram bot started successfully")
            self.started_at = datetime.utcnow()
            await self.alert_manager.alert_startup_success()
            self.health_monitor_task = asyncio.create_task(self._health_monitor_loop())

        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            await self.alert_manager.alert_startup_failure(e)
            raise

    async def stop(self):
        """Stop the Telegram bot."""
        try:
            logger.info("Stopping Telegram bot...")
            if self.health_monitor_task:
                self.health_monitor_task.cancel()
                try:
                    await self.health_monitor_task
                except asyncio.CancelledError:
                    pass

            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

            await self.trade_manager.cleanup()
            await self.user_repo.db.close()

            logger.info("Telegram bot stopped successfully")

        except Exception as e:
            logger.error(f"Error stopping bot: {e}")

    async def _health_monitor_loop(self):
        """Run lightweight periodic health checks."""
        while True:
            await asyncio.sleep(Config.HEALTHCHECK_INTERVAL_SECONDS)
            await self._run_health_monitor_once()

    async def _run_health_monitor_once(self):
        """Check service health and send admin alerts for important failures."""
        try:
            db_ok = await self.user_repo.db.health_check()
            if not db_ok:
                await self.alert_manager.alert_db_failure("health_monitor")
                return

            backup_health = read_backup_health()
            if backup_health.is_problem:
                await self.alert_manager.alert_backup_problem(backup_health.message)

            maintenance_health = await read_maintenance_health(self.system_log_repo)
            if maintenance_health.is_problem:
                await self.alert_manager.alert_maintenance_problem(maintenance_health.message)

            await self.pending_order_reconciler.reconcile_stale_processing_orders(
                stale_after_seconds=Config.PENDING_ORDER_RECONCILE_AFTER_SECONDS,
                limit=Config.PENDING_ORDER_RECONCILE_LIMIT,
            )
        except Exception as exc:
            logger.error(f"Health monitor failed: {exc}")
            await self.alert_manager.alert_db_failure("health_monitor", exc)


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
