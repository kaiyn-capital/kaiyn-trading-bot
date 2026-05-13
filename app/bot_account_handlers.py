import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from .bitget_errors import classify_bitget_exception
from .bot_keyboards import (
    main_menu_keyboard,
    status_actions_keyboard,
    trading_settings_keyboard,
)
from .bot_messages import help_message, settings_message, welcome_message
from .bot_states import WAITING_API_KEY, WAITING_PASSPHRASE, WAITING_SECRET_KEY
from .log_sanitizer import summarize_balance_response

logger = logging.getLogger(__name__)


class AccountHandlersMixin:
    async def _record_bitget_failure_alert(self, classified_error, source: str, details: dict | None = None):
        return None

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start."""
        user = await self._get_or_create_user(update)
        await self._log_user_action(user, "start_command")

        await update.message.reply_text(welcome_message(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help."""
        await update.message.reply_text(help_message(), parse_mode="Markdown")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status."""
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
            credentials = (
                user.encrypted_api_key,
                user.encrypted_secret_key,
                user.encrypted_passphrase,
            )
            is_connected, message = await self.trade_manager.test_api_connection(credentials)

            if is_connected:
                bitget_uid = await self.trade_manager.get_user_uid(credentials)
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
            await self._record_bitget_failure_alert(classified, "status_command", {"telegram_id": user.telegram_id})
            await update.message.reply_text(f"❌ {classified.user_message}")

    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balance."""
        user = await self._get_or_create_user(update)
        await self._log_user_action(user, "balance_command")

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
            balance_data = await self.trade_manager.get_account_balance(user.id, credentials)
            logger.info(
                "Account balance summary: user_id=%s telegram_id=%s summary=%s",
                user.id,
                user.telegram_id,
                summarize_balance_response(balance_data),
            )

            if balance_data.get("code") == "00000" and balance_data.get("data"):
                assets = balance_data["data"]
                balance_text = self._format_usdt_balance_text(assets, raw_limit=500, compact=True)

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
            await self._record_bitget_failure_alert(classified, "balance_command", {"telegram_id": user.telegram_id})
            await update.message.reply_text(f"❌ {classified.user_message}")

    async def set_api_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start API setup."""
        user = await self._get_or_create_user(update)
        await self._log_user_action(user, "set_api_start")

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

        self.user_sessions.pop(user.telegram_id, None)
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
        """Store API key during setup."""
        user = await self._get_or_create_user(update)
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
            return WAITING_API_KEY

        session = self.user_sessions.setdefault(user.telegram_id, {})
        session["api_key"] = api_key
        session["step"] = "secret_key"

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ API Key 已保存\n\n**第 2 步：Secret Key**\n请发送您的 Secret Key",
        )

        return WAITING_SECRET_KEY

    async def set_secret_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Store secret key during setup."""
        user = await self._get_or_create_user(update)
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
            return WAITING_SECRET_KEY

        session = self.user_sessions.setdefault(user.telegram_id, {})
        session["secret_key"] = secret_key
        session["step"] = "passphrase"

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Secret Key 已保存\n\n**第 3 步：Passphrase**\n请发送您的 Passphrase",
        )

        return WAITING_PASSPHRASE

    async def set_passphrase(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Store passphrase and finish API setup."""
        user = await self._get_or_create_user(update)
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
            test_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🔄 正在测试 API 连接...")

            credentials = self.encryption_manager.encrypt_api_credentials(api_key, secret_key, passphrase)
            is_connected, message = await self.trade_manager.test_api_connection(credentials)

            if is_connected:
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
                    f"❌ **API 连接测试失败**\n\n错误信息: {message}\n\n请检查您的 API 凭证是否正确，然后重新设置。",
                    parse_mode="Markdown",
                )

        except Exception as e:
            logger.error(f"API setup failed: {e}")
            classified = classify_bitget_exception(e)
            await self._record_bitget_failure_alert(classified, "set_passphrase", {"telegram_id": user.telegram_id})
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ {classified.user_message}",
            )

        finally:
            self.user_sessions.pop(user.telegram_id, None)

        return ConversationHandler.END

    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings."""
        user = await self._get_or_create_user(update)
        await self._log_user_action(user, "settings_command")

        await update.message.reply_text(
            settings_message(getattr(user, "fixed_risk_amount", None)),
            reply_markup=trading_settings_keyboard(),
            parse_mode="Markdown",
        )

    async def _handle_set_risk_start_callback(self, query, user):
        """Start fixed risk amount setup from a callback."""
        current_risk = getattr(user, "fixed_risk_amount", None)

        if current_risk is None:
            self.user_sessions[user.telegram_id] = {"step": "risk_amount"}

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
        user = await self._get_or_create_user(update)
        amount_text = update.message.text.strip()

        try:
            amount = float(amount_text)
            if amount <= 0:
                raise ValueError("金额必须大于 0")

            success = await self.user_repo.update_user_risk_amount(user.id, amount)

            if success:
                await update.message.reply_text(f"✅ **已设置定 R 止损为 {amount} USDT**", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ 设置失败，请重试")

            self.user_sessions.pop(user.telegram_id, None)
            return

        except ValueError:
            await update.message.reply_text("❌ 输入格式不正确，请输入有效数字：\n\n例如：50 或 100.5")
            return

    async def handle_global_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route plain text messages for active setup sessions."""
        user = await self._get_or_create_user(update)

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

        self.user_sessions.pop(user.telegram_id, None)
        self.user_sessions[user.telegram_id] = {"step": "api_key"}

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
            is_connected, message = await self.trade_manager.test_api_connection(credentials)

            if is_connected:
                bitget_uid = await self.trade_manager.get_user_uid(credentials)
                status_text = f"Bitget UID: {bitget_uid}\n✅ **API 连接状态：正常**"
                await query.edit_message_text(status_text, parse_mode="Markdown")
            else:
                await query.edit_message_text(f"❌ **API 连接失败**\n\n{message}", parse_mode="Markdown")

        except Exception as e:
            classified = classify_bitget_exception(e)
            await self._record_bitget_failure_alert(classified, "status_callback", {"telegram_id": user.telegram_id})
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
            balance_data = await self.trade_manager.get_account_balance(user.id, credentials)
            logger.info(
                "Account balance refresh summary: user_id=%s telegram_id=%s summary=%s",
                user.id,
                user.telegram_id,
                summarize_balance_response(balance_data),
            )

            if balance_data.get("code") == "00000" and balance_data.get("data"):
                assets = balance_data["data"]
                balance_text = self._format_usdt_balance_text(assets, raw_limit=300, compact=False)

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
            await self._record_bitget_failure_alert(classified, "balance_callback", {"telegram_id": user.telegram_id})
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
        self.user_sessions.pop(user.telegram_id, None)
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
        """Handle fixed risk amount change confirmation."""
        self.user_sessions[user.telegram_id] = {"step": "risk_amount"}

        await query.edit_message_text(
            "💰 **设置每单固定止损金额，以进行定 R 开仓。**\n\n请输入定 R 金额 u（数字）：",
            parse_mode="Markdown",
        )

    def _format_usdt_balance_text(self, assets, raw_limit: int, compact: bool) -> str:
        """Format account balance API payload for display."""
        balance_text = "💰 **U本位合约账户余额**\n\n"
        found_assets = False

        if isinstance(assets, list):
            for asset in assets:
                coin = asset.get("coin") or asset.get("marginCoin") or asset.get("currency", "")
                if coin == "USDT":
                    available = float(asset.get("available") or asset.get("availableBalance") or asset.get("equity", 0))
                    frozen = float(asset.get("frozen") or asset.get("locked") or asset.get("freezeBalance", 0))
                    total = available + frozen

                    if total > 0:
                        balance_text += "**USDT:**\n"
                        balance_text += f"  可用: {available:.4f}\n"
                        balance_text += f"  冻结: {frozen:.4f}\n"
                        balance_text += f"  总计: {total:.4f}\n\n"
                        found_assets = True
                        break
        elif isinstance(assets, dict):
            if "USDT" in assets:
                usdt_data = assets["USDT"]
                available = float(
                    usdt_data.get("available") or usdt_data.get("availableBalance") or usdt_data.get("equity", 0)
                )
                frozen = float(usdt_data.get("frozen") or usdt_data.get("locked") or usdt_data.get("freezeBalance", 0))
                total = available + frozen

                if total > 0:
                    balance_text += "**USDT:**\n"
                    balance_text += f"  可用: {available:.4f}\n"
                    balance_text += f"  冻结: {frozen:.4f}\n"
                    balance_text += f"  总计: {total:.4f}\n\n"
                    found_assets = True

        if not found_assets:
            empty_text = "暂无 USDT 资产或余额为零" if compact else "暂无 USDT 资产或余额为零"
            balance_text += f"{empty_text}\n\n"
            balance_text += f"📊 **原始API数据：**\n```\n{str(assets)[:raw_limit]}...\n```\n\n"

        if compact:
            balance_text += "ℹ️ **说明：** 仅显示 U 本位合约账户的 USDT 余额"
        else:
            balance_text += "ℹ️ **说明：** 仅显示 U 本位合约账户的 USDT 余额"
        return balance_text
