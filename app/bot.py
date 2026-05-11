import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import uuid
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from telegram.error import TelegramError

from .config import Config
from .database import (
    get_user_repo,
    get_trade_repo,
    get_pending_order_repo,
    get_notification_repo,
    get_system_log_repo,
    get_channel_repo,
)
from .bitget_api import (
    BitgetTradeManager,
    BitgetAPIError,
    validate_order_params,
    format_symbol,
)
from .encryption import create_encryption_manager
from .models import User

# 對話狀態
WAITING_API_KEY, WAITING_SECRET_KEY, WAITING_PASSPHRASE = range(3)
WAITING_TRADE_SYMBOL, WAITING_TRADE_AMOUNT, WAITING_TRADE_PRICE = range(10, 13)
WAITING_RISK_AMOUNT = 20

logger = logging.getLogger(__name__)
UTC_PLUS_8 = timezone(timedelta(hours=8))


class TelegramBot:
    """Telegram 机器人主类"""

    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        # 移除單一管理員ID，改用多管理員檢查

        # 初始化服務
        self.user_repo = get_user_repo()
        self.trade_repo = get_trade_repo()
        self.pending_order_repo = get_pending_order_repo()
        self.notification_repo = get_notification_repo()
        self.system_log_repo = get_system_log_repo()
        self.channel_repo = get_channel_repo()

        # 加密管理器
        self.encryption_manager = create_encryption_manager(Config.ENCRYPTION_KEY)

        # Bitget 交易管理器
        self.trade_manager = BitgetTradeManager(self.encryption_manager)

        # 用戶會話數據
        self.user_sessions: Dict[int, Dict] = {}

        # 創建應用
        self.application = Application.builder().token(self.token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        """设置处理器"""
        # 基本命令
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("balance", self.balance_command))
        self.application.add_handler(CommandHandler("settings", self.settings_command))

        # API 設置對話
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

        # 1R 設置對話
        risk_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.set_risk_start, pattern="^set_risk_amount$")
            ],
            states={
                WAITING_RISK_AMOUNT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.set_risk_amount
                    )
                ],
            },
            fallbacks=[],
        )
        self.application.add_handler(risk_conv_handler)

        # 管理員命令
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

        # 回調查詢處理器
        self.application.add_handler(CallbackQueryHandler(self.button_callback))

        # 全局消息處理器（用於處理 API 設置）
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, self.handle_global_message, block=False
            )
        )

        # 錯誤處理器
        self.application.add_error_handler(self.error_handler)

        # 設置機器人命令菜單
        asyncio.create_task(self.setup_commands())

    async def setup_commands(self):
        """设置机器人命令菜单"""
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
        """获取或创建用户"""
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

    def _escape_markdown(self, text: str) -> str:
        """转义 Markdown 特殊字符"""
        if not text:
            return text

        # Telegram Markdown 需要轉義的字符
        escape_chars = [
            "_",
            "*",
            "[",
            "]",
            "(",
            ")",
            "~",
            "`",
            ">",
            "#",
            "+",
            "-",
            "=",
            "|",
            "{",
            "}",
            ".",
            "!",
        ]
        for char in escape_chars:
            text = text.replace(char, f"\\{char}")
        return text

    async def _is_trader_or_admin(self, telegram_id: int) -> bool:
        """检查是否为管理员或发单员"""
        if Config.is_admin(telegram_id):
            return True

        try:
            return await self.user_repo.is_active_trader(telegram_id)
        except Exception as e:
            logger.error(f"Check trader status error: {e}")
            return False

    def _get_sender_username(self, update: Update) -> str:
        """获取发送者的 username"""
        if update.effective_user and update.effective_user.username:
            return update.effective_user.username
        elif update.effective_user:
            return update.effective_user.first_name or "Unknown"
        return "Unknown"

    async def _log_user_action(
        self, user: User, action: str, details: Optional[Dict] = None
    ):
        """记录用户操作"""
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
            # 使用基本信息記錄
            await self.system_log_repo.log(
                level="INFO",
                message=f"User action: {action}",
                module="telegram_bot",
                telegram_id=user.telegram_id,
                extra_data=details or {},
            )

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """开始命令处理器"""
        user = await self._get_or_create_user(update)
        await self._log_user_action(user, "start_command")

        welcome_message = """
🚀 **欢迎使用 Kaiyn Trading Bot！**

这个机器人可以帮助您：
• 针对 Bitget 专属群的交易信号实现一键定损下单

💡加入 Bitget 专属群方法：
1. 使用邀请码 **"5nmb"** 注册[Bitget交易所](https://partner.bitget.com/bg/JZQT5S)
2. KYC 完成并入金后，私信群主或管理员处理

📚 Resources:

• 👁️‍🗨️ [Kaiyn Capital 公开讨论群](https://t.me/kaiyncapital)
• 🌏 [Kaiyn Capital 官方网站](https://kaiyn.org)

输入 `/help` 查看完整命令列表。
        """

        keyboard = [
            [InlineKeyboardButton("🔗 设置 API", callback_data="setup_api")],
            [InlineKeyboardButton("📊 查看状态", callback_data="check_status")],
            [InlineKeyboardButton("💰 查看余额", callback_data="check_balance")],
            [InlineKeyboardButton("⚙️ 交易设置", callback_data="trading_settings")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            welcome_message, reply_markup=reply_markup, parse_mode="Markdown"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """帮助命令处理器"""
        help_text = """
📖 **命令说明**

**基本命令：**
• `/start` - 开始使用机器人
• `/help` - 查看此帮助信息
• `/status` - 查看 API 连接状态

**API 管理：**
• `/setapi` - 设置 Bitget API 密钥
• 机器人会引导您依序输入，输入后会自动删除消息保护隐私

**交易功能：**
• `/settings` - 设置交易参数（1R 愿意承受止损金额）
• `/balance` - 查看账户余额
• 📊 **信号交易** - 当管理员发送交易信号时可一键下单

**管理员功能：**（仅管理员可用）
• `/admin` - 管理员面板


**安全须知：**
🔒 所有 API 信息都会加密存储
🔒 输入的 API 密钥会自动删除保护隐私
🔒 只给予交易权限，不要给予提币权限
        """

        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """状态命令处理器"""
        user = await self._get_or_create_user(update)
        await self._log_user_action(user, "status_command")

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
            # 測試 API 連接
            credentials = (
                user.encrypted_api_key,
                user.encrypted_secret_key,
                user.encrypted_passphrase,
            )
            is_connected, message = await self.trade_manager.test_api_connection(
                credentials
            )

            if is_connected:
                # 獲取 Bitget UID
                bitget_uid = await self.trade_manager.get_user_uid(credentials)

                status_text = f"""Bitget UID: {bitget_uid}\n✅ **API 连接状态：正常**"""

                keyboard = [
                    [
                        InlineKeyboardButton(
                            "💰 查看余额", callback_data="check_balance"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⚙️ 交易设置", callback_data="trading_settings"
                        )
                    ],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(
                    status_text, reply_markup=reply_markup, parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"❌ **API 连接失败**\n\n错误信息: {message}\n\n请检查您的 API 设置或重新配置。",
                    parse_mode="Markdown",
                )

        except Exception as e:
            logger.error(f"Status check failed: {e}")
            await update.message.reply_text("❌ 检查状态时发生错误，请稍后再试。")

    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """余额命令处理器"""
        user = await self._get_or_create_user(update)
        await self._log_user_action(user, "balance_command")

        if not user.is_api_connected:
            await update.message.reply_text(
                "❌ 请先设置 API 连接。使用 `/setapi` 命令。"
            )
            return

        try:
            credentials = (
                user.encrypted_api_key,
                user.encrypted_secret_key,
                user.encrypted_passphrase,
            )

            logger.info(f"Getting balance for user ID: {user.id}")
            balance_data = await self.trade_manager.get_account_balance(
                user.id, credentials
            )

            # 添加日誌查看返回的數據格式
            logger.info(f"Balance API response: {balance_data}")

            if balance_data.get("code") == "00000" and balance_data.get("data"):
                assets = balance_data["data"]
                logger.info(f"Assets data: {assets}")

                # 只顯示USDT資產（U本位合約）
                balance_text = "💰 **U本位合约账户余额**\n\n"

                found_assets = False

                # 合約API返回格式可能不同，嘗試多種格式
                if isinstance(assets, list):
                    # 如果是列表格式
                    for asset in assets:
                        logger.info(f"Processing asset: {asset}")

                        # 嘗試不同的字段名稱
                        coin = (
                            asset.get("coin")
                            or asset.get("marginCoin")
                            or asset.get("currency", "")
                        )
                        if coin == "USDT":
                            # 嘗試不同的餘額字段
                            available = float(
                                asset.get("available")
                                or asset.get("availableBalance")
                                or asset.get("equity", 0)
                            )
                            frozen = float(
                                asset.get("frozen")
                                or asset.get("locked")
                                or asset.get("freezeBalance", 0)
                            )
                            total = available + frozen

                            if total > 0:
                                balance_text += f"**USDT:**\n"
                                balance_text += f"  可用: {available:.4f}\n"
                                balance_text += f"  冻结: {frozen:.4f}\n"
                                balance_text += f"  总计: {total:.4f}\n\n"
                                found_assets = True
                                break
                elif isinstance(assets, dict):
                    # 如果是字典格式，可能直接包含USDT信息
                    logger.info(f"Assets is dict: {assets}")
                    if "USDT" in assets:
                        usdt_data = assets["USDT"]
                        available = float(
                            usdt_data.get("available")
                            or usdt_data.get("availableBalance")
                            or usdt_data.get("equity", 0)
                        )
                        frozen = float(
                            usdt_data.get("frozen")
                            or usdt_data.get("locked")
                            or usdt_data.get("freezeBalance", 0)
                        )
                        total = available + frozen

                        if total > 0:
                            balance_text += f"**USDT:**\n"
                            balance_text += f"  可用: {available:.4f}\n"
                            balance_text += f"  冻结: {frozen:.4f}\n"
                            balance_text += f"  总计: {total:.4f}\n\n"
                            found_assets = True

                if not found_assets:
                    balance_text += "暂无USDT资产或余额为零\n\n"
                    balance_text += (
                        f"📊 **原始API数据：**\n```\n{str(assets)[:500]}...\n```\n\n"
                    )

                balance_text += "ℹ️ **说明：** 仅显示U本位合约账户的USDT余额"

                keyboard = [
                    [
                        InlineKeyboardButton(
                            "🔄 刷新余额", callback_data="refresh_balance"
                        )
                    ],
                    [InlineKeyboardButton("🏠 返回", callback_data="return_start")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(
                    balance_text, reply_markup=reply_markup, parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ 获取余额失败，请检查 API 设置。")

        except BitgetAPIError as e:
            logger.error(f"Bitget API error: {e}")
            await update.message.reply_text(f"❌ API 错误: {e.message}")
        except Exception as e:
            logger.error(f"Balance check failed: {e}")
            await update.message.reply_text("❌ 查询余额时发生错误，请稍后再试。")

    async def add_trader_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """管理员添加发单员"""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        # 獲取 Telegram ID
        if not context.args:
            await update.message.reply_text(
                "👥 **添加发单员**\n\n"
                "使用方法：\n"
                "`/add_trader Telegram_ID`\n\n"
                "例如：\n"
                "`/add_trader 123456789`",
                parse_mode="Markdown",
            )
            return

        try:
            telegram_id = int(context.args[0])

            # 設置發單員狀態
            success = await self.user_repo.set_trader_status(telegram_id, True)

            if success:
                await update.message.reply_text(
                    f"✅ **发单员添加成功**\n\n"
                    f"Telegram ID：{telegram_id}\n"
                    f"现在该用户可以使用 `/send_signal` 命令发送交易信号。",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("❌ 设置发单员失败，请稍后重试")

        except ValueError:
            await update.message.reply_text("❌ Telegram ID 必须是数字")
        except Exception as e:
            logger.error(f"Add trader error: {e}")
            await update.message.reply_text("❌ 添加发单员失败")

    # API 設置相關方法
    async def set_api_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """开始 API 设置"""
        user = await self._get_or_create_user(update)
        await self._log_user_action(user, "set_api_start")

        # 檢查是否已設置 API
        if user.is_api_connected and user.encrypted_api_key:
            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ 确认修改", callback_data="confirm_modify_api"
                    )
                ],
                [InlineKeyboardButton("❌ 取消", callback_data="cancel_modify_api")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "🔐 **API 设置**\n\n"
                "您已经设置完成 Bitget API 连接。\n\n"
                "是否要修改现有的 API 设置？",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        # 清除可能存在的舊數據
        if user.telegram_id in self.user_sessions:
            del self.user_sessions[user.telegram_id]

        self.user_sessions[user.telegram_id] = {"step": "api_key"}

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
        """设置 API Key"""
        user = await self._get_or_create_user(update)
        api_key = update.message.text.strip()

        # 立即刪除用戶輸入的 API Key 消息
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete API key message: {e}")

        if not api_key or len(api_key) < 10:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ API Key 格式不正确，请重新输入：",
            )
            return WAITING_API_KEY

        self.user_sessions[user.telegram_id]["api_key"] = api_key

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ API Key 已保存\n\n"
            "**第 2 步：Secret Key**\n"
            "请发送您的 Secret Key",
        )

        return WAITING_SECRET_KEY

    async def set_secret_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """设置 Secret Key"""
        user = await self._get_or_create_user(update)
        secret_key = update.message.text.strip()

        # 立即刪除用戶輸入的 Secret Key 消息
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete secret key message: {e}")

        if not secret_key or len(secret_key) < 10:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Secret Key 格式不正确，请重新输入：",
            )
            return WAITING_SECRET_KEY

        self.user_sessions[user.telegram_id]["secret_key"] = secret_key

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Secret Key 已保存\n\n"
            "**第 3 步：Passphrase**\n"
            "请发送您的 Passphrase",
        )

        return WAITING_PASSPHRASE

    async def set_passphrase(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """设置 Passphrase 并完成 API 设置"""
        user = await self._get_or_create_user(update)
        passphrase = update.message.text.strip()

        # 立即刪除用戶輸入的 Passphrase 消息
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete passphrase message: {e}")

        if not passphrase:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Passphrase 不能为空，请重新输入：",
            )
            return WAITING_PASSPHRASE

        session = self.user_sessions.get(user.telegram_id, {})
        api_key = session.get("api_key")
        secret_key = session.get("secret_key")

        if not all([api_key, secret_key]):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ 设置过程中出现错误，请重新开始。",
            )
            return ConversationHandler.END

        try:
            # 測試 API 連接
            test_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id, text="🔄 正在测试 API 连接..."
            )

            credentials = self.encryption_manager.encrypt_api_credentials(
                api_key, secret_key, passphrase
            )
            is_connected, message = await self.trade_manager.test_api_connection(
                credentials
            )

            if is_connected:
                # 保存加密的 API 憑證
                await self.user_repo.update_user_api_credentials(
                    user.id, credentials[0], credentials[1], credentials[2]
                )

                await self._log_user_action(user, "api_setup_success")

                await test_msg.edit_text(
                    "✅ **API 设置成功！**\n\n"
                    "您的 API 密钥已加密保存，现在可以开始使用交易功能。\n\n"
                    "使用 `/status` 检查连接状态\n"
                    "使用 `/settings` 设置交易参数（1R愿意承受止损金额）",
                    parse_mode="Markdown",
                )
            else:
                await test_msg.edit_text(
                    f"❌ **API 连接测试失败**\n\n"
                    f"错误信息: {message}\n\n"
                    "请检查您的 API 凭证是否正确，然后重新设置。",
                    parse_mode="Markdown",
                )

        except Exception as e:
            logger.error(f"API setup failed: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ 设置过程中发生错误，请稍后重试。",
            )

        finally:
            # 清除會話數據
            if user.telegram_id in self.user_sessions:
                del self.user_sessions[user.telegram_id]

        return ConversationHandler.END

    async def settings_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """交易设置命令处理器"""
        user = await self._get_or_create_user(update)
        await self._log_user_action(user, "settings_command")

        # 獲取用戶的 1R 設置
        risk_amount = getattr(user, "fixed_risk_amount", None)
        risk_text = f"{risk_amount} USDT" if risk_amount else "未设置"

        settings_text = f"""
⚙️ **交易设置**

**当前设置：**
• 固定风险金额(1R)：{risk_text}

**风险管理：**
固定风险金额(1R)用于计算每笔交易的开仓金额
        """

        keyboard = [
            [
                InlineKeyboardButton(
                    "💰 设置固定风险金额(1R)", callback_data="set_risk_amount"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            settings_text, reply_markup=reply_markup, parse_mode="Markdown"
        )

    async def set_risk_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """开始设置 1R 风险金额"""
        query = update.callback_query
        await query.answer()

        user = await self._get_or_create_user(update)
        current_risk = getattr(user, "fixed_risk_amount", None)

        if current_risk is None:
            # 從未設置
            # 設置 session 狀態
            self.user_sessions[user.telegram_id] = {"step": "risk_amount"}

            await query.edit_message_text(
                "💰 **设置每单固定止损金额，以进行定R开仓。**\n\n"
                "请输入定R金额u（数字）：",
                parse_mode="Markdown",
            )
        else:
            # 已設置過
            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ 确认更改", callback_data="confirm_change_risk"
                    )
                ],
                [InlineKeyboardButton("❌ 取消", callback_data="cancel_change_risk")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"💰 **设置每单固定止损金额，以进行定R开仓。**\n\n"
                f"您目前已设置定损为 {current_risk} USDT，要更改吗？",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return ConversationHandler.END

    async def set_risk_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """设置风险金额"""
        user = await self._get_or_create_user(update)
        amount_text = update.message.text.strip()

        try:
            # 驗證輸入格式
            amount = float(amount_text)
            if amount <= 0:
                raise ValueError("金额必须大于 0")

            # 更新用戶設置
            success = await self.user_repo.update_user_risk_amount(user.id, amount)

            if success:
                await update.message.reply_text(
                    f"✅ **已设置定R止损为 {amount} USDT**", parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ 设置失败，请重试")

            # 清除 session
            if user.telegram_id in self.user_sessions:
                del self.user_sessions[user.telegram_id]

            return ConversationHandler.END

        except ValueError:
            await update.message.reply_text(
                "❌ 输入格式不正确，请输入有效数字：\n\n" "例如：50 或 100.5"
            )
            # 保持 session 狀態，繼續等待輸入
            return

    async def handle_global_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """处理全局消息（主要用于 API 设置）"""
        user = await self._get_or_create_user(update)

        # 檢查是否在 API 設置流程中
        if user.telegram_id in self.user_sessions:
            session = self.user_sessions[user.telegram_id]
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
                await self.delete_channel_by_number(update, context)
                return

        # 如果不在任何設置流程中，不處理此消息

    async def delete_channel_by_number(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """根据编号删除频道"""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        try:
            channel_number = int(update.message.text.strip())

            # 獲取儲存的頻道數據
            session_data = self.user_sessions.get(user.telegram_id, {})
            channels_data = session_data.get("channels_data", [])

            if (
                not channels_data
                or channel_number < 1
                or channel_number > len(channels_data)
            ):
                await update.message.reply_text("❌ 无效的频道编号")
                return

            # 獲取要刪除的頻道
            channel_to_delete = channels_data[channel_number - 1]

            deleted = await self.channel_repo.deactivate_channel(
                channel_to_delete["chat_id"]
            )
            if deleted:
                await update.message.reply_text(
                    f"✅ **频道已删除**\n\n"
                    f"频道名称：{channel_to_delete['title']}\n"
                    f"已从管理列表中移除。",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("❌ 找不到指定的频道")

            # 清除 session
            if user.telegram_id in self.user_sessions:
                del self.user_sessions[user.telegram_id]

        except ValueError:
            await update.message.reply_text("❌ 请输入有效的数字")
        except Exception as e:
            logger.error(f"Delete channel error: {e}")
            await update.message.reply_text("❌ 删除频道失败")

    async def admin_users_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """管理员查看用户列表"""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        try:
            users_data = await self.user_repo.get_active_users()

            users_text = "👥 **用户列表**\n\n"
            for u in users_data[:20]:  # 限制顯示數量
                api_status = "✅" if u.get("is_api_connected") else "❌"
                first_name = u.get("first_name") or "Unknown"
                username = u.get("username") or "N/A"
                telegram_id = u.get("telegram_id")
                created_at = u.get("created_at")

                users_text += f"{api_status} {first_name} (@{username})\n"
                users_text += f"   ID: {telegram_id} | 注册: {created_at.strftime('%m-%d') if created_at else 'N/A'}\n\n"

            if len(users_data) > 20:
                users_text += f"... 还有 {len(users_data) - 20} 位用户"

            # 使用 HTML 模式而非 Markdown 以避免特殊字符問題
            import re

            users_text_html = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", users_text)
            await update.message.reply_text(users_text_html, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Admin users command error: {e}")
            await update.message.reply_text("❌ 获取用户列表时发生错误")

    async def admin_broadcast_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """管理员广播消息"""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        # 獲取廣播消息
        message_text = " ".join(context.args)
        if not message_text:
            await update.message.reply_text(
                "📢 **广播消息**\n\n"
                "使用方法：`/admin_broadcast 您的消息内容`\n\n"
                "例如：`/admin_broadcast 系统将于今晚进行维护`",
                parse_mode="Markdown",
            )
            return

        try:
            channels = await self.channel_repo.get_active_channels()
            sent_to_channels = 0
            failed_channels = 0
            status_msg = await update.message.reply_text(
                f"📤 开始广播给 {len(channels)} 个频道/群组..."
            )

            # 獲取發送者的 username
            sender_username = self._get_sender_username(update)

            for channel in channels:
                try:
                    await context.bot.send_message(
                        chat_id=channel["chat_id"],
                        text=f"📢 **管理员广播** by @{sender_username}\n\n{message_text}",
                        parse_mode="Markdown",
                    )
                    sent_to_channels += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to send broadcast to channel {channel['chat_id']}: {e}"
                    )
                    failed_channels += 1

            await status_msg.edit_text(
                f"✅ **广播完成**\n\n"
                f"成功发送：{sent_to_channels} 个频道/群组\n"
                f"发送失败：{failed_channels} 个频道/群组",
                parse_mode="Markdown",
            )

        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            await update.message.reply_text("❌ 广播时发生错误")

    async def admin_channels_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """管理员查看频道/群组列表"""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        try:
            channels = await self.channel_repo.get_active_channels()

            if not channels:
                await update.message.reply_text(
                    "📺 **频道/群组管理**\n\n"
                    "目前没有管理的频道或群组。\n\n"
                    "使用 `/add_channel` 添加频道或群组。",
                    parse_mode="Markdown",
                )
                return

            channels_text = "📺 **已管理的频道/群组**\n\n"
            for channel in channels:
                status = "✅" if channel["auto_forward_signals"] else "❌"

                title = channel["title"] or "Unknown"
                chat_type = channel["chat_type"]
                username = channel["username"]

                channels_text += f"{status} **{title}**\n"
                channels_text += f"   类型: {chat_type}\n"
                channels_text += f"   ID: `{channel['chat_id']}`\n"
                if username:
                    channels_text += f"   用户名: @{username}\n"
                channels_text += f"   自动转发: {'开启' if channel['auto_forward_signals'] else '关闭'}\n\n"

            keyboard = [
                [InlineKeyboardButton("➕ 添加频道", callback_data="add_new_channel")],
                [InlineKeyboardButton("⚙️ 管理设置", callback_data="manage_channels")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # 使用 HTML 模式避免 Markdown 解析錯誤
            channels_text_html = channels_text.replace(
                "**已管理的频道/群组**", "<b>已管理的频道/群组</b>"
            )
            # 處理其他 ** 標記
            import re

            channels_text_html = re.sub(
                r"\*\*(.*?)\*\*", r"<b>\1</b>", channels_text_html
            )
            channels_text_html = re.sub(
                r"`(.*?)`", r"<code>\1</code>", channels_text_html
            )

            await update.message.reply_text(
                channels_text_html, reply_markup=reply_markup, parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Admin channels command error: {e}")
            import traceback

            traceback.print_exc()
            await update.message.reply_text(f"❌ 获取频道列表时发生错误: {str(e)}")

    async def add_channel_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """管理员添加频道/群组"""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        args = context.args
        if not args:
            await update.message.reply_text(
                "📺 **添加频道/群组**\n\n"
                "使用方法：\n"
                "`/add_channel @username 描述`\n"
                "`/add_channel -1001234567890 私人群组`\n\n"
                "**注意：**\n"
                "• 机器人必须是频道/群组的管理员\n"
                "• 对于私人群组，请使用群组的数字 ID\n"
                "• 对于公开频道，可使用 @username",
                parse_mode="Markdown",
            )
            return

        chat_identifier = args[0]
        description = " ".join(args[1:]) if len(args) > 1 else "管理员添加的频道"

        try:
            # 測試是否可以訪問該頻道/群組
            chat_info = await context.bot.get_chat(chat_identifier)

            # 檢查機器人權限
            bot_member = await context.bot.get_chat_member(
                chat_identifier, context.bot.id
            )
            if bot_member.status not in ["administrator", "creator"]:
                await update.message.reply_text(
                    "❌ 机器人在该频道/群组中不是管理员\n\n"
                    "请确保机器人有管理员权限后再试。"
                )
                return

            existing = await self.channel_repo.get_channel_by_chat_id(str(chat_info.id))
            if existing:
                await update.message.reply_text(
                    f"⚠️ 频道/群组 **{chat_info.title}** 已经在管理列表中"
                )
                return

            await self.channel_repo.create_channel(
                chat_id=str(chat_info.id),
                chat_type=chat_info.type.value,
                title=chat_info.title,
                username=chat_info.username,
                added_by_user_id=user.telegram_id,
                description=description,
            )

            await update.message.reply_text(
                f"✅ **频道/群组添加成功**\n\n"
                f"**名称：** {chat_info.title}\n"
                f"**类型：** {chat_info.type.value}\n"
                f"**ID：** `{chat_info.id}`\n"
                f"**描述：** {description}\n\n"
                "现在可以向此频道发送交易信号了！",
                parse_mode="Markdown",
            )

        except Exception as e:
            logger.error(f"Add channel error: {e}")
            await update.message.reply_text(
                f"❌ 添加频道失败\n\n"
                f"可能的原因：\n"
                f"• 频道/群组不存在\n"
                f"• 机器人没有访问权限\n"
                f"• ID 格式错误\n\n"
                f"错误详情：{str(e)}"
            )

    async def send_to_channel_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """管理员向指定频道发送消息"""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "📤 **发送到频道**\n\n"
                "使用方法：\n"
                "`/send_to_channel @channel_username 消息内容`\n"
                "`/send_to_channel -1001234567890 消息内容`\n\n"
                "例如：\n"
                "`/send_to_channel @my_signals 今日重要公告`",
                parse_mode="Markdown",
            )
            return

        chat_identifier = args[0]
        message_text = " ".join(args[1:])

        try:
            # 發送消息到指定頻道
            sent_message = await context.bot.send_message(
                chat_id=chat_identifier, text=message_text, parse_mode="Markdown"
            )

            await update.message.reply_text(
                f"✅ **消息已发送**\n\n"
                f"目标频道：{chat_identifier}\n"
                f"消息 ID：{sent_message.message_id}",
                parse_mode="Markdown",
            )

        except Exception as e:
            logger.error(f"Send to channel error: {e}")
            await update.message.reply_text(f"❌ 发送失败\n\n" f"错误：{str(e)}")

    async def send_signal_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """管理员或发单员发送交易信号 - JSON 格式"""
        user = await self._get_or_create_user(update)

        # 檢查是否為管理員或發單員
        if not await self._is_trader_or_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有发送交易信号的权限")
            return

        # 解析信號參數
        args = context.args
        if len(args) < 6:
            await update.message.reply_text(
                "📊 **发送交易信号 - 格式**\n\n"
                "使用方法：\n"
                "`/send_signal 交易对 方向 低进场价 高进场价 止损价 止盈价1 [止盈价2] [止盈价3] [止盈价4] [备注文字]`\n\n"
                "例如：\n"
                "`/send_signal BTCUSDT long 115000 115500 114200 117500 110500 123500 130000`\n"
                "`/send_signal ETHUSDT short 3200 3250 3300 3100 3000 2900 等待回踩后执行`",
                parse_mode="Markdown",
            )
            return

        try:
            symbol = args[0].upper()
            direction = args[1].lower()
            entry_lower = float(args[2])
            entry_upper = float(args[3])
            stop_loss = float(args[4])

            # 收集止盈價格
            take_profits = []
            remark_start_index = None
            for i in range(5, len(args)):
                try:
                    take_profits.append(float(args[i]))
                except ValueError:
                    remark_start_index = i
                    break
            remark_text = (
                " ".join(args[remark_start_index:]).strip()
                if remark_start_index is not None
                else ""
            )

            if direction not in ["long", "short"]:
                await update.message.reply_text("❌ 交易方向必须是 long 或 short")
                return

            # 創建信號 JSON
            signal_data = {
                "symbol": symbol,
                "direction": direction,
                "entry_range": {"lower": entry_lower, "upper": entry_upper},
                "take_profit_levels": take_profits,
                "stop_loss": stop_loss,
                "remark": remark_text,
            }

            # 格式化顯示文本
            direction_text = "多 Long" if direction == "long" else "空 Short"
            tp_text = "/".join([str(int(tp)) for tp in take_profits])

            # 獲取發送者的 username
            sender_username = self._get_sender_username(update)

            signal_text = f"🚨 **交易信号** by @{sender_username}\n\n"
            signal_text += f"**Symbol：** {symbol}\n"
            signal_text += f"**Direction：** {direction_text}\n"
            signal_text += f"**Entry：** {int(entry_upper)}-{int(entry_lower)}\n"
            signal_text += f"**TP：** {tp_text}\n"
            signal_text += f"**SL：** {int(stop_loss)}\n"
            if remark_text:
                signal_text += f"{self._escape_markdown(remark_text)}\n"
            signal_text += "\n"
            signal_time = datetime.now(UTC_PLUS_8).strftime("%Y-%m-%d %H:%M:%S")
            signal_text += f"⏰ {signal_time} UTC+8"

            # 創建下單按鈕
            keyboard = [
                [
                    InlineKeyboardButton(
                        "💰 市价下单",
                        callback_data=f"place_order_market_{symbol}_{direction}_{entry_lower:g}_{entry_upper:g}_{stop_loss:g}",
                    ),
                    InlineKeyboardButton(
                        "📌 挂单",
                        callback_data=f"place_order_limit_{symbol}_{direction}_{entry_lower:g}_{entry_upper:g}_{stop_loss:g}",
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # # 發送給用戶
            # active_users = self.user_repo.get_active_users()
            # sent_to_users = 0

            # for user_data in active_users:
            #     try:
            #         await context.bot.send_message(
            #             chat_id=user_data.get("telegram_id"),
            #             text=signal_text,
            #             reply_markup=reply_markup,
            #             parse_mode="Markdown",
            #         )
            #         sent_to_users += 1
            #     except Exception as e:
            #         logger.warning(
            #             f"Failed to send signal to user {user_data.get('telegram_id')}: {e}"
            #         )

            # 發送到頻道/群組
            sent_to_channels = 0
            try:
                channels_data = await self.channel_repo.get_signal_channels()

                # 在 Session 外部發送消息
                for channel_data in channels_data:
                    try:
                        # 決定是否包含按鈕
                        channel_markup = (
                            reply_markup
                            if channel_data["forward_with_buttons"]
                            else None
                        )

                        await context.bot.send_message(
                            chat_id=channel_data["chat_id"],
                            text=signal_text,
                            reply_markup=channel_markup,
                            parse_mode="Markdown",
                        )
                        sent_to_channels += 1
                    except Exception as e:
                        logger.warning(
                            f"Failed to send signal to channel {channel_data['chat_id']}: {e}"
                        )

            except Exception as e:
                logger.error(f"Error getting channels: {e}")

            # 發送確認消息
            confirm_text = f"✅ **交易信号已发送**\n\n"
            # confirm_text += f"👥 發送給用戶：{sent_to_users} 位\n"
            confirm_text += f"📺 发送到频道：{sent_to_channels} 个\n\n"
            confirm_text += f"**信号详情：**\n{signal_text}"

            await update.message.reply_text(confirm_text, parse_mode="Markdown")

        except ValueError:
            await update.message.reply_text("❌ 价格格式错误，请输入有效数字")
        except Exception as e:
            logger.error(f"Send signal error: {e}")
            await update.message.reply_text(
                "❌ 发送信号时发生错误", parse_mode="Markdown"
            )

    # 按鈕回調處理器
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理所有按钮回调"""
        query = update.callback_query
        await query.answer()

        user = await self._get_or_create_user(update)
        data = query.data

        try:
            if data == "setup_api":
                result = await self._handle_setup_api_callback(query, user)
                if result == WAITING_API_KEY:
                    # 這是一個特殊情況，我們需要啟動 API 設置對話
                    # 但是 callback 不能直接啟動 ConversationHandler
                    # 所以我們只是顯示指示
                    pass
            elif data == "check_status":
                await self._handle_status_callback(query, user)
            elif data == "check_balance" or data == "refresh_balance":
                await self._handle_balance_callback(query, user)
            elif data == "trading_settings":
                await self._handle_trading_settings_callback(query, user)
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
                await query.edit_message_text("✅ 已取消更改风险设置")
            elif data == "return_start":
                await self._handle_return_start_callback(query, user)
            elif data.startswith("confirm_order_"):
                await self._handle_confirm_pending_order_callback(query, user, data)
            elif data.startswith("cancel_order_"):
                await self._handle_cancel_pending_order_callback(query, user, data)
            elif data.startswith("trade_side_"):
                await self._handle_trade_side_callback(query, user, data)
            elif data.startswith("trade_type_"):
                await self._handle_trade_type_callback(query, user, data)
            elif data.startswith("amount_"):
                await self._handle_amount_callback(query, user, data)
            elif data.startswith("confirm_trade_"):
                await self._handle_confirm_trade_callback(query, user, data)
            elif data == "cancel_trade":
                await self._handle_cancel_trade_callback(query, user)
            elif data == "cancel_order":
                await query.answer("已取消下单")
                await self._send_private_message(query, user, "✅ 已取消下单")
            elif data == "add_new_channel":
                await query.edit_message_text(
                    "📺 **添加频道/群组**\n\n"
                    "请使用 `/add_channel` 命令添加新的频道或群组。\n\n"
                    "使用方法：\n"
                    "`/add_channel @username 描述`\n"
                    "`/add_channel -1001234567890 私人群组`",
                    parse_mode="Markdown",
                )
            elif data == "manage_channels":
                # 查詢所有頻道以供選擇刪除
                try:
                    channels = await self.channel_repo.get_active_channels()

                    if not channels:
                        await query.edit_message_text(
                            "📺 **管理频道**\n\n"
                            "目前没有任何频道。\n\n"
                            "使用 `/add_channel` 添加频道。",
                            parse_mode="Markdown",
                        )
                        return

                    channels_data = [
                        {
                            "id": i,
                            "chat_id": channel["chat_id"],
                            "title": channel["title"] or "Unknown",
                            "username": channel["username"],
                        }
                        for i, channel in enumerate(channels, 1)
                    ]

                    # 顯示頻道列表 - 使用HTML模式避免Markdown解析問題
                    manage_text = "📺 <b>管理频道</b>\n\n"
                    for ch in channels_data:
                        # 轉義HTML特殊字符
                        title_escaped = (
                            str(ch["title"])
                            .replace("&", "&amp;")
                            .replace("<", "&lt;")
                            .replace(">", "&gt;")
                        )
                        username_text = f"(@{ch['username']})" if ch["username"] else ""
                        manage_text += f"{ch['id']}. {title_escaped} {username_text}\n"

                    manage_text += "\n请选择操作："

                    keyboard = [
                        [
                            InlineKeyboardButton(
                                "🗑️ 删除频道", callback_data="delete_channel_start"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🔙 返回", callback_data="return_admin_channels"
                            )
                        ],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    # 在 user_sessions 中儲存頻道數據
                    self.user_sessions[user.telegram_id] = {
                        "channels_data": channels_data
                    }

                    await query.edit_message_text(
                        manage_text, reply_markup=reply_markup, parse_mode="HTML"
                    )

                except Exception as e:
                    logger.error(f"Manage channels error: {e}")
                    await query.edit_message_text(
                        "❌ 获取频道列表失败\n\n"
                        f"错误详情: {str(e)}\n\n"
                        "请检查数据库连接状态。"
                    )
            elif data == "delete_channel_start":
                await query.edit_message_text(
                    "🗑️ **删除频道**\n\n" "请输入要删除的频道编号：",
                    parse_mode="Markdown",
                )
                # 設置 session 狀態
                if user.telegram_id in self.user_sessions:
                    self.user_sessions[user.telegram_id]["step"] = "delete_channel"
                else:
                    self.user_sessions[user.telegram_id] = {"step": "delete_channel"}
            elif data == "return_admin_channels":
                # 直接重新顯示頻道列表
                try:
                    channels = await self.channel_repo.get_active_channels()

                    if not channels:
                        await query.edit_message_text(
                            "📺 **频道/群组管理**\n\n"
                            "目前没有管理的频道或群组。\n\n"
                            "使用 `/add_channel` 添加频道或群组。",
                            parse_mode="Markdown",
                        )
                        return

                    channels_text = "📺 **已管理的频道/群组**\n\n"
                    for channel in channels:
                        status = "✅" if channel["auto_forward_signals"] else "❌"

                        title = channel["title"] or "Unknown"
                        chat_type = channel["chat_type"]
                        username = channel["username"]

                        channels_text += f"{status} **{title}**\n"
                        channels_text += f"   类型: {chat_type}\n"
                        channels_text += f"   ID: `{channel['chat_id']}`\n"
                        if username:
                            channels_text += f"   用户名: @{username}\n"
                        channels_text += f"   自动转发: {'开启' if channel['auto_forward_signals'] else '关闭'}\n\n"

                    keyboard = [
                        [
                            InlineKeyboardButton(
                                "➕ 添加频道", callback_data="add_new_channel"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "⚙️ 管理设置", callback_data="manage_channels"
                            )
                        ],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    # 使用 HTML 模式避免 Markdown 解析錯誤
                    import re

                    channels_text_html = re.sub(
                        r"\*\*(.*?)\*\*", r"<b>\1</b>", channels_text
                    )
                    channels_text_html = re.sub(
                        r"`(.*?)`", r"<code>\1</code>", channels_text_html
                    )

                    await query.edit_message_text(
                        channels_text_html,
                        reply_markup=reply_markup,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(f"Return admin channels error: {e}")
                    await query.edit_message_text("❌ 获取频道列表失败")
            else:
                await query.edit_message_text("❓ 未知操作")

        except Exception as e:
            logger.error(f"Button callback error: {e}")
            await query.edit_message_text("❌ 操作失败，请重试")

    async def _handle_setup_api_callback(self, query, user):
        """处理设置 API 按钮"""
        # 檢查是否已設置 API
        if user.is_api_connected and user.encrypted_api_key:
            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ 确认修改", callback_data="confirm_modify_api"
                    )
                ],
                [InlineKeyboardButton("❌ 取消", callback_data="cancel_modify_api")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "🔐 **API 设置**\n\n"
                "您已经设置完成 Bitget API 连接。\n\n"
                "是否要修改现有的 API 设置？",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return

        # 直接開始 API 設置流程
        # 清除可能存在的舊數據
        if user.telegram_id in self.user_sessions:
            del self.user_sessions[user.telegram_id]

        self.user_sessions[user.telegram_id] = {"step": "api_key"}

        await query.edit_message_text(
            "🔐 **设置 Bitget API**\n\n"
            "请按顺序提供您的 API 信息。\n\n"
            "**第 1 步：API Key**\n"
            "请发送您的 Bitget API Key\n\n"
            "💡 提示：您可以在 Bitget 官网的 API 管理页面获取",
            parse_mode="Markdown",
        )

        # callback 中不能直接啟動對話，所以我們等待用戶的下一個消息

    async def _handle_status_callback(self, query, user):
        """处理状态检查按钮"""
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
            is_connected, message = await self.trade_manager.test_api_connection(
                credentials
            )

            if is_connected:
                # 獲取 Bitget UID
                bitget_uid = await self.trade_manager.get_user_uid(credentials)
                status_text = f"Bitget UID: {bitget_uid}\n✅ **API 连接状态：正常**"
                await query.edit_message_text(status_text, parse_mode="Markdown")
            else:
                await query.edit_message_text(
                    f"❌ **API 连接失败**\n\n{message}", parse_mode="Markdown"
                )

        except Exception as e:
            await query.edit_message_text("❌ 检查状态时发生错误")

    async def _handle_balance_callback(self, query, user):
        """处理余额查询按钮"""
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
            balance_data = await self.trade_manager.get_account_balance(
                user.id, credentials
            )

            if balance_data.get("code") == "00000" and balance_data.get("data"):
                assets = balance_data["data"]
                logger.info(f"Balance callback - Assets data: {assets}")

                # 只顯示USDT資產（U本位合約）
                balance_text = "💰 **U本位合约账户余额**\n\n"

                found_assets = False

                # 合約API返回格式可能不同，嘗試多種格式
                if isinstance(assets, list):
                    # 如果是列表格式
                    for asset in assets:
                        logger.info(f"Processing callback asset: {asset}")

                        # 嘗試不同的字段名稱
                        coin = (
                            asset.get("coin")
                            or asset.get("marginCoin")
                            or asset.get("currency", "")
                        )
                        if coin == "USDT":
                            # 嘗試不同的餘額字段
                            available = float(
                                asset.get("available")
                                or asset.get("availableBalance")
                                or asset.get("equity", 0)
                            )
                            frozen = float(
                                asset.get("frozen")
                                or asset.get("locked")
                                or asset.get("freezeBalance", 0)
                            )
                            total = available + frozen

                            if total > 0:
                                balance_text += f"**USDT:**\n"
                                balance_text += f"  可用: {available:.4f}\n"
                                balance_text += f"  冻结: {frozen:.4f}\n"
                                balance_text += f"  总计: {total:.4f}\n\n"
                                found_assets = True
                                break
                elif isinstance(assets, dict):
                    # 如果是字典格式，可能直接包含USDT信息
                    logger.info(f"Callback assets is dict: {assets}")
                    if "USDT" in assets:
                        usdt_data = assets["USDT"]
                        available = float(
                            usdt_data.get("available")
                            or usdt_data.get("availableBalance")
                            or usdt_data.get("equity", 0)
                        )
                        frozen = float(
                            usdt_data.get("frozen")
                            or usdt_data.get("locked")
                            or usdt_data.get("freezeBalance", 0)
                        )
                        total = available + frozen

                        if total > 0:
                            balance_text += f"**USDT:**\n"
                            balance_text += f"  可用: {available:.4f}\n"
                            balance_text += f"  冻结: {frozen:.4f}\n"
                            balance_text += f"  总计: {total:.4f}\n\n"
                            found_assets = True

                if not found_assets:
                    balance_text += "暂无 USDT 资产或余额为零\n\n"
                    balance_text += (
                        f"📊 **原始API数据：**\n```\n{str(assets)[:300]}...\n```\n\n"
                    )

                balance_text += "ℹ️ **说明：** 仅显示 U 本位合约账户的 USDT 余额"

                keyboard = [
                    [InlineKeyboardButton("🔄 刷新", callback_data="refresh_balance")],
                    [InlineKeyboardButton("🏠 返回", callback_data="return_start")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    balance_text, reply_markup=reply_markup, parse_mode="Markdown"
                )
            else:
                await query.edit_message_text("❌ 获取余额失败")

        except Exception as e:
            await query.edit_message_text("❌ 查询余额时发生错误")

    async def _handle_return_start_callback(self, query, user):
        """处理返回开始按钮"""
        welcome_message = """
🚀 **欢迎使用 Kaiyn Trading Bot！**

这个机器人可以帮助您：
• 针对 Bitget 专属群的交易信号实现一键定损下单

💡加入 Bitget 专属群方法：
1. 使用邀请码 **"5nmb"** 注册[Bitget交易所](https://partner.bitget.com/bg/JZQT5S)
2. KYC 完成并入金后，私信群主或管理员处理

📚 Resources:

• 👁️‍🗨️ [Kaiyn Capital 公开讨论群](https://t.me/kaiyncapital)
• 🌏 [Kaiyn Capital 官方网站](https://kaiyn.org)

输入 `/help` 查看完整命令列表。
        """

        keyboard = [
            [InlineKeyboardButton("🔗 设置 API", callback_data="setup_api")],
            [InlineKeyboardButton("📊 查看状态", callback_data="check_status")],
            [InlineKeyboardButton("💰 查看余额", callback_data="check_balance")],
            [InlineKeyboardButton("⚙️ 交易设置", callback_data="trading_settings")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            welcome_message, reply_markup=reply_markup, parse_mode="Markdown"
        )

    async def _handle_trading_settings_callback(self, query, user):
        """处理交易设置按钮"""
        # 獲取用戶的 1R 設置
        risk_amount = getattr(user, "fixed_risk_amount", None)
        risk_text = f"{risk_amount} USDT" if risk_amount else "未设置"

        settings_text = f"""
⚙️ **交易设置**

**当前设置：**
• 固定风险金额(1R)：{risk_text}

**风险管理：**
固定风险金额(1R)用于计算每笔交易的开仓金额
        """

        keyboard = [
            [
                InlineKeyboardButton(
                    "💰 设置固定风险金额(1R)", callback_data="set_risk_amount"
                )
            ],
            [InlineKeyboardButton("🏠 返回", callback_data="return_start")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            settings_text, reply_markup=reply_markup, parse_mode="Markdown"
        )

    async def _handle_place_order_callback(self, query, user, data):
        """处理下单按钮 - 发送私人消息流程"""
        # 先回應按鈕點擊
        await query.answer("正在处理下单请求...")

        # 解析信號數據
        try:
            parts = data.split("_")
            if len(parts) >= 8 and parts[2] in {"market", "limit"}:
                order_mode = parts[2]
                symbol = parts[3]
                direction = parts[4]
                entry_lower = float(parts[5])
                entry_upper = float(parts[6])
                stop_loss = float(parts[7])
            elif len(parts) >= 7:
                order_mode = "market"
                symbol = parts[2]
                direction = parts[3]
                entry_lower = float(parts[4])
                entry_upper = float(parts[5])
                stop_loss = float(parts[6])
            else:
                await self._send_private_message(query, user, "❌ 交易信号数据格式错误")
                return

            if order_mode not in {"market", "limit"} or direction not in {"long", "short"}:
                await self._send_private_message(query, user, "❌ 交易信号数据格式错误")
                return
        except (ValueError, IndexError) as e:
            await self._send_private_message(query, user, "❌ 交易信号数据解析失败")
            return

        # 檢查用戶設置
        user_data = await self.user_repo.get_user_by_telegram_id(user.telegram_id)

        # 檢查 1：API 連接
        if not user_data or not user_data.is_api_connected:
            await self._send_private_message(
                query,
                user,
                "❌ **无法下单**\n\n"
                "您尚未连接 Bitget API。\n\n"
                "请使用 `/setapi` 命令设置您的 API 密钥。",
            )
            return

        # 檢查 2：1R 設置
        if not getattr(user_data, "fixed_risk_amount", None):
            await self._send_private_message(
                query,
                user,
                "❌ **无法下单**\n\n"
                "您尚未设定固定风险金额(1R)。\n\n"
                "请使用 `/settings` 命令设置您的风险管理参数。",
            )
            return

        try:
            # 發送處理中消息到私人聊天
            await self._send_private_message(query, user, "🔄 正在获取当前市价...")

            current_price = await self.trade_manager.get_market_price(symbol)

            # 計算風險參數
            risk_amount = user_data.fixed_risk_amount
            entry_low = min(entry_lower, entry_upper)
            entry_high = max(entry_lower, entry_upper)
            requested_order_mode = order_mode
            limit_price = None
            calculation_price = current_price
            switch_notice = None

            if order_mode == "limit":
                limit_price = entry_high if direction == "long" else entry_low
                can_fill_immediately = (
                    direction == "long" and limit_price >= current_price
                ) or (direction == "short" and limit_price <= current_price)

                if can_fill_immediately:
                    order_mode = "market"
                    limit_price = None
                    calculation_price = current_price
                    switch_notice = (
                        "⚠️ 此挂单价已可能立即成交，已切换为市价下单确认。\n\n"
                    )
                else:
                    calculation_price = limit_price

            if calculation_price <= 0:
                await self._send_private_message(
                    query, user, "❌ 进场价格错误，无法计算仓位"
                )
                return

            # 計算止損距離百分比與開倉名義價值
            stop_distance_pct = abs((calculation_price - stop_loss) / calculation_price)
            if stop_distance_pct <= 0:
                await self._send_private_message(
                    query, user, "❌ 止损价格设置错误，无法计算仓位"
                )
                return

            position_value = risk_amount / stop_distance_pct
            quantity = position_value / calculation_price

            # 顯示確認信息
            direction_text = "做多" if direction == "long" else "做空"
            order_mode_text = "市价下单" if order_mode == "market" else "挂单"

            confirm_text = f"💰 **交易确认**\n\n"
            if switch_notice:
                confirm_text += switch_notice
            confirm_text += f"**交易对：** {symbol}\n"
            confirm_text += f"**方向：** {direction_text}\n"
            confirm_text += f"**下单方式：** {order_mode_text}\n"
            confirm_text += f"**当前价格：** ${current_price:,.4f}\n"
            if order_mode == "limit":
                confirm_text += f"**挂单价格：** ${limit_price:,.4f}\n"
            confirm_text += f"**止损价格：** ${stop_loss:,.4f}\n"
            confirm_text += f"**交易数量：** {quantity:.6f}\n"
            confirm_text += f"**名义价值：** ${position_value:.2f}\n"
            confirm_text += f"**风险金额(1R)：** ${risk_amount:.2f}\n"
            confirm_text += f"**止损距离：** {stop_distance_pct*100:.2f}%\n\n"
            if order_mode == "limit":
                confirm_text += "⚠️ 将送出 GTC 限价挂单，订单送出不代表已成交"
            else:
                confirm_text += "⚠️ 将使用市价单进场"

            pending_order = await self.pending_order_repo.create_pending_order(
                user_id=user_data.id,
                telegram_id=user.telegram_id,
                symbol=symbol,
                direction=direction,
                order_mode=order_mode,
                limit_price=limit_price,
                entry_lower=entry_low,
                entry_upper=entry_high,
                quantity=quantity,
                stop_loss=stop_loss,
                position_value=position_value,
                current_price=current_price,
                expires_at=datetime.utcnow() + timedelta(minutes=10),
            )
            logger.info(
                f"Stored {order_mode} pending order {pending_order.token} for user "
                f"{user.telegram_id}; requested_mode={requested_order_mode}"
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ 确认下单",
                        callback_data=f"confirm_order_{pending_order.token}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ 取消",
                        callback_data=f"cancel_order_{pending_order.token}",
                    )
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self._send_private_message(query, user, confirm_text, reply_markup)

        except Exception as e:
            logger.error(f"Place order callback error: {e}")
            await self._send_private_message(
                query, user, f"❌ 无法获取 {symbol} 当前价格：{str(e)}"
            )

    async def _send_private_message(self, query, user, text, reply_markup=None):
        """发送私人消息到用户"""
        try:
            await self.application.bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Failed to send private message to {user.telegram_id}: {e}")
            # 如果發送私人消息失敗，回退到原來的方式
            try:
                await query.answer(f"请查看私人聊天: {text[:50]}...")
            except:
                pass

    async def _handle_confirm_pending_order_callback(self, query, user, data):
        """处理确认待处理订单"""
        try:
            token = data.removeprefix("confirm_order_")
            pending_order, status = await self.pending_order_repo.claim_pending_order(
                token, user.telegram_id
            )

            if not pending_order:
                await self._send_private_message(
                    query, user, "❌ 找不到这笔待确认订单，请重新点击最新信号下单。"
                )
                return

            if status == "expired":
                await self._send_private_message(
                    query, user, "❌ 这笔待确认订单已过期，请重新点击信号下单。"
                )
                return

            if status != "processing":
                await self._send_private_message(
                    query, user, f"⚠️ 这笔待确认订单目前状态为 {status}，无法重复执行。"
                )
                return

            await self._execute_order(
                query,
                user,
                pending_order.symbol,
                pending_order.direction,
                pending_order.quantity,
                pending_order.stop_loss,
                pending_order.position_value,
                pending_order.current_price,
                order_mode=pending_order.order_mode,
                limit_price=pending_order.limit_price,
                pending_order_token=token,
            )

        except Exception as e:
            logger.error(f"Confirm pending order error: {e}")
            await self._send_private_message(query, user, "❌ 确认下单时发生错误")

    async def _handle_cancel_pending_order_callback(self, query, user, data):
        """处理取消待确认订单"""
        token = data.removeprefix("cancel_order_")
        status = await self.pending_order_repo.cancel_pending_order(
            token, user.telegram_id
        )

        if status == "cancelled":
            await query.answer("已取消下单")
            await self._send_private_message(query, user, "✅ 已取消下单")
        elif status == "missing":
            await self._send_private_message(query, user, "❌ 找不到这笔待确认订单")
        else:
            await self._send_private_message(
                query, user, f"⚠️ 这笔待确认订单目前状态为 {status}，无法取消。"
            )

    async def _execute_order(
        self,
        query,
        user,
        symbol,
        direction,
        quantity,
        stop_loss,
        position_value,
        current_price,
        order_mode="market",
        limit_price=None,
        pending_order_token=None,
    ):
        """执行订单的核心逻辑"""
        await query.answer("正在执行下单...")
        await self._send_private_message(query, user, "🔄 **正在执行下单...**")
        trade_record_id = None

        try:
            # 獲取用戶數據（重新獲取以確保最新信息）
            user_data = await self.user_repo.get_user_by_telegram_id(user.telegram_id)
            if (
                not user_data
                or not user_data.is_api_connected
                or not all(
                    [
                        user_data.encrypted_api_key,
                        user_data.encrypted_secret_key,
                        user_data.encrypted_passphrase,
                    ]
                )
            ):
                raise RuntimeError("User API credentials are not configured")

            # 生成客戶端訂單 ID
            client_order_id = (
                f"TG_{user.telegram_id}_{int(datetime.timestamp(datetime.now()))}"
            )

            # 獲取用戶 API 憑證
            credentials = (
                user_data.encrypted_api_key,
                user_data.encrypted_secret_key,
                user_data.encrypted_passphrase,
            )

            order_mode = order_mode if order_mode in {"market", "limit"} else "market"
            is_limit_order = order_mode == "limit"
            order_type = "limit" if is_limit_order else "market"
            order_price = limit_price if is_limit_order else None

            if is_limit_order and not order_price:
                raise RuntimeError("Limit order is missing limit_price")

            side = "buy" if direction == "long" else "sell"

            # 限制數量精度到6位小數以符合Bitget要求
            quantity = round(quantity, 6)

            logger.info(
                f"Executing {order_type} order for {symbol}, side: {side}, "
                f"quantity: {quantity}, limit_price: {order_price}"
            )

            # 先創建交易記錄
            trade_record = await self.trade_repo.create_trade(
                user_id=user_data.id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=order_price,
                client_order_id=client_order_id,
            )
            trade_record_id = trade_record.id

            # 執行下單，添加必要的tradeSide參數
            logger.info(
                f"Placing {order_type} order: symbol={symbol}, side={side}, "
                f"quantity={quantity}, stop_loss={stop_loss}, limit_price={order_price}"
            )
            if is_limit_order:
                result = await self.trade_manager.place_limit_order(
                    user_data.id,
                    credentials,
                    symbol,
                    side,
                    str(quantity),
                    str(order_price),
                    client_order_id,
                    "USDT",
                    "open",
                    stop_loss,
                    force="gtc",
                )
            else:
                result = await self.trade_manager.place_market_order(
                    user_data.id,
                    credentials,
                    symbol,
                    side,
                    str(quantity),
                    client_order_id,
                    "USDT",
                    "open",
                    stop_loss,
                )
            logger.info(f"place_{order_type}_order result: {result}")

            if not result or result.get("code") != "00000":
                error_msg = f"Order failed for {symbol}: {result.get('msg', 'Unknown error') if result else 'No response'}"
                logger.error(error_msg)
                raise Exception(error_msg)

            if result.get("code") == "00000":
                order_data = result.get("data", {})
                bitget_order_id = order_data.get("orderId", "")

                # 更新交易記錄
                await self.trade_repo.update_trade_result(
                    trade_record_id,
                    bitget_order_id=bitget_order_id,
                    status="pending" if is_limit_order else "filled",
                )
                if pending_order_token:
                    await self.pending_order_repo.mark_executed(
                        pending_order_token, trade_record_id
                    )

                # 發送成功通知
                success_text = (
                    "✅ **挂单已送出**\n\n"
                    if is_limit_order
                    else "✅ **下单成功**\n\n"
                )
                success_text += f"**币种：** {symbol}\n"
                success_text += (
                    f"**方向：** {'做多' if direction == 'long' else '做空'}\n"
                )
                success_text += f"**下单方式：** {'挂单' if is_limit_order else '市价'}\n"
                success_text += f"**仓位名义价值：** ${position_value:.2f}\n"
                success_text += f"**止损：** ${stop_loss:,.4f}\n"
                if is_limit_order:
                    success_text += f"**挂单价格：** ${order_price:,.4f}\n"
                    success_text += f"**当前价格：** ${current_price:,.4f}\n"
                else:
                    success_text += f"**进场价格：** ${current_price:,.4f}\n"
                success_text += (
                    f"**当前 1R 设置：** ${user_data.fixed_risk_amount:.2f}\n"
                )
                success_text += f"**订单 ID：** {bitget_order_id[:16]}...\n\n"
                success_text += "✅ 止损已同时设置"
                if is_limit_order:
                    success_text += "\n⚠️ 挂单成功代表订单已送出，不代表已成交"

                await self._send_private_message(query, user, success_text)

                # 記錄用戶操作
                await self._log_user_action(
                    user,
                    "order_executed",
                    {
                        "symbol": symbol,
                        "direction": direction,
                        "quantity": quantity,
                        "position_value": position_value,
                        "bitget_order_id": bitget_order_id,
                        "stop_loss": stop_loss,
                        "order_mode": order_mode,
                        "limit_price": order_price,
                    },
                )
                return True

            else:
                error_msg = result.get("msg", "未知错误")
                # 更新交易記錄為失敗
                await self.trade_repo.update_trade_result(
                    trade_record_id,
                    bitget_order_id=None,  # 使用 None 而不是空字符串
                    status="failed",
                    error_message=error_msg,
                )

                await self._send_private_message(
                    query,
                    user,
                    f"❌ **下单失败**\n\n错误信息：{error_msg}\n\n请检查交易对是否支持或API权限设置。",
                )

        except Exception as e:
            logger.error(f"Order execution error: {e}")
            if trade_record_id is not None:
                # 更新交易記錄為失敗
                await self.trade_repo.update_trade_result(
                    trade_record_id,
                    bitget_order_id=None,  # 使用 None 而不是空字符串
                    status="failed",
                    error_message=str(e),
                )
            if pending_order_token:
                await self.pending_order_repo.mark_failed(pending_order_token, str(e))

            await self._send_private_message(
                query,
                user,
                f"❌ **执行下单时发生错误**\n\n错误详情：{str(e)}\n\n请检查API设置或联系支持。",
            )
            return False

    async def _handle_confirm_modify_api(self, query, user):
        """处理确认修改 API"""
        # 清除可能存在的舊數據
        if user.telegram_id in self.user_sessions:
            del self.user_sessions[user.telegram_id]

        self.user_sessions[user.telegram_id] = {"step": "api_key"}

        await query.edit_message_text(
            "🔐 **修改 Bitget API**\n\n"
            "请按顺序提供您的新 API 信息。\n\n"
            "**第 1 步：API Key**\n"
            "请发送您的 Bitget API Key",
            parse_mode="Markdown",
        )
        return WAITING_API_KEY

    async def _handle_confirm_change_risk(self, query, user):
        """处理确认更改风险设置"""
        # 設置 session 狀態
        self.user_sessions[user.telegram_id] = {"step": "risk_amount"}

        await query.edit_message_text(
            "💰 **设置每单固定止损金额，以进行定 R 开仓。**\n\n"
            "请输入定 R 金额 u（数字）：",
            parse_mode="Markdown",
        )

    async def _handle_confirm_trade_callback(self, query, user, data):
        """处理交易确认执行"""
        parts = data.split("_")
        symbol = parts[2]
        side = parts[3]
        order_type = parts[4]
        amount = parts[5]
        price = parts[6] if parts[6] != "market" else None

        if not user.is_api_connected:
            await query.edit_message_text("❌ API 未连接，无法执行交易")
            return

        try:
            await query.edit_message_text("🔄 **正在执行交易...**")

            # 生成客戶端訂單 ID
            client_order_id = (
                f"TG_{user.telegram_id}_{int(datetime.timestamp(datetime.now()))}"
            )

            # 創建交易記錄
            trade_record = await self.trade_repo.create_trade(
                user_id=user.id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=float(amount),
                price=float(price) if price else None,
                client_order_id=client_order_id,
            )

            # 執行交易
            credentials = (
                user.encrypted_api_key,
                user.encrypted_secret_key,
                user.encrypted_passphrase,
            )

            if order_type == "market":
                result = await self.trade_manager.place_market_order(
                    user.id, credentials, symbol, side, amount, client_order_id
                )
            else:
                result = await self.trade_manager.place_limit_order(
                    user.id, credentials, symbol, side, amount, price, client_order_id
                )

            # 更新交易記錄
            if result.get("code") == "00000":
                order_data = result.get("data", {})
                bitget_order_id = order_data.get("orderId", "")

                await self.trade_repo.update_trade_result(
                    trade_record.id, bitget_order_id=bitget_order_id, status="pending"
                )

                # 記錄成功日誌
                await self._log_user_action(
                    user,
                    "trade_executed",
                    {
                        "symbol": symbol,
                        "side": side,
                        "order_type": order_type,
                        "amount": amount,
                        "bitget_order_id": bitget_order_id,
                    },
                )

                success_text = f"✅ **交易已提交成功！**\n\n"
                success_text += f"交易对：{symbol}\n"
                success_text += f"方向：{'买入' if side == 'buy' else '卖出'}\n"
                success_text += f"数量：{amount}\n"
                success_text += f"订单 ID：{bitget_order_id[:16]}...\n\n"

                await query.edit_message_text(success_text, parse_mode="Markdown")

                # 發送通知
                await self.notification_repo.create_notification(
                    user_id=user.id,
                    message_type="trade",
                    title="交易执行成功",
                    message=f"{symbol} {side.upper()} {amount} 订单已提交",
                    extra_data={"order_id": bitget_order_id},
                )

            else:
                error_msg = result.get("msg", "未知错误")
                await self.trade_repo.update_trade_result(
                    trade_record.id,
                    bitget_order_id="",
                    status="failed",
                    error_message=error_msg,
                )

                await query.edit_message_text(
                    f"❌ **交易执行失败**\n\n错误信息：{error_msg}",
                    parse_mode="Markdown",
                )

        except BitgetAPIError as e:
            logger.error(f"Bitget API error during trade: {e}")
            await query.edit_message_text(
                f"❌ **API 错误**\n\n{e.message}", parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            await query.edit_message_text(
                "❌ **执行交易时发生错误**\n\n请稍后重试或联系支持。",
                parse_mode="Markdown",
            )
        finally:
            # 清除會話數據
            if user.telegram_id in self.user_sessions:
                del self.user_sessions[user.telegram_id]

    async def _handle_cancel_trade_callback(self, query, user):
        """处理取消交易"""
        if user.telegram_id in self.user_sessions:
            del self.user_sessions[user.telegram_id]

        await query.edit_message_text("✅ 交易已取消")

    # 管理員功能
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """管理员命令处理器"""
        user = await self._get_or_create_user(update)

        if not Config.is_admin(user.telegram_id):
            await update.message.reply_text("❌ 您没有管理员权限")
            return

        try:
            # 獲取系統統計
            users_data = await self.user_repo.get_active_users()
            active_users = len(users_data)

            channel_count = await self.channel_repo.count_active_channels()

            admin_text = f"👑 **管理员面板**\n\n"
            admin_text += f"📊 **系统统计**\n"
            admin_text += f"• 活跃用户：{active_users}\n"
            admin_text += f"• 管理频道：{channel_count}\n"
            db_ok = await self.user_repo.db.health_check()
            admin_text += f"• 系统状态：{'正常' if db_ok else '异常'}\n\n"
            admin_text += f"🛠️ **管理功能**\n"
            admin_text += f"• `/admin_users` - 查看用户列表\n"
            admin_text += f"• `/admin_channels` - 管理频道/群组\n"
            admin_text += f"• `/add_channel` - 添加频道/群组\n"
            admin_text += f"• `/admin_broadcast` - 广播消息\n"
            admin_text += f"• `/send_signal` - 发送交易信号\n"
            admin_text += f"• `/send_to_channel` - 发送到指定频道\n"
            admin_text += f"• `/add_trader` - 添加交易员"

            await update.message.reply_text(admin_text, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Admin command error: {e}")
            import traceback

            traceback.print_exc()
            await update.message.reply_text(f"❌ 获取管理信息时发生错误: {str(e)}")

    # 錯誤處理器
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """全局错误处理器"""
        logger.error(f"Update {update} caused error {context.error}")

        # 記錄錯誤
        user_id = None
        telegram_id = None

        try:
            if update.effective_user:
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

        # 向用戶發送錯誤消息
        if update.effective_chat:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ 系统发生错误，请稍后重试。如问题持续，请联系管理员。",
                )
            except Exception:
                pass  # 忽略發送錯誤消息時的錯誤

    # 啟動和停止方法
    async def start(self):
        """启动机器人"""
        try:
            # 驗證配置
            Config.validate()

            logger.info("Starting Telegram bot...")

            # 啟動應用
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
        """停止机器人"""
        try:
            logger.info("Stopping Telegram bot...")

            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

            # 清理資源
            await self.trade_manager.cleanup()
            await self.user_repo.db.close()

            logger.info("Telegram bot stopped successfully")

        except Exception as e:
            logger.error(f"Error stopping bot: {e}")


# 便捷函數
def create_bot() -> TelegramBot:
    """创建机器人实例"""
    return TelegramBot()


async def run_bot():
    """运行机器人"""
    bot = create_bot()
    try:
        await bot.start()
        # 保持運行
        import signal
        import asyncio

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
