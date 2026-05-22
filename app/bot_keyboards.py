from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .decimal_utils import decimal_text


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔗 设置 API", callback_data="setup_api")],
            [InlineKeyboardButton("📊 查看状态", callback_data="check_status")],
            [InlineKeyboardButton("💰 查看余额", callback_data="check_balance")],
            [InlineKeyboardButton("⚙️ 交易设置", callback_data="trading_settings")],
        ]
    )


def status_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 查看余额", callback_data="check_balance")],
            [InlineKeyboardButton("⚙️ 交易设置", callback_data="trading_settings")],
        ]
    )


def trading_settings_keyboard(include_return: bool = False) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton("💰 设置固定风险金额(1R)", callback_data="set_risk_amount")]]

    if include_return:
        keyboard.append([InlineKeyboardButton("🏠 返回", callback_data="return_start")])

    return InlineKeyboardMarkup(keyboard)


def signal_order_keyboard(
    symbol: str,
    direction: str,
    entry_lower,
    entry_upper,
    stop_loss,
) -> InlineKeyboardMarkup:
    entry_lower_text = decimal_text(entry_lower)
    entry_upper_text = decimal_text(entry_upper)
    stop_loss_text = decimal_text(stop_loss)
    order_payload = f"{symbol}_{direction}_{entry_lower_text}_{entry_upper_text}_{stop_loss_text}"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💰 市价下单",
                    callback_data=f"place_order_market_{order_payload}",
                ),
                InlineKeyboardButton(
                    "📌 挂单",
                    callback_data=f"place_order_limit_{order_payload}",
                ),
            ]
        ]
    )


def signal_preview_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认转发", callback_data=f"confirm_signal_{token}")],
            [InlineKeyboardButton("❌ 取消", callback_data=f"cancel_signal_{token}")],
        ]
    )


def chart_update_preview_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认转发", callback_data=f"confirm_chart_update_{token}")],
            [InlineKeyboardButton("❌ 取消", callback_data=f"cancel_chart_update_{token}")],
        ]
    )


def pending_order_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认下单", callback_data=f"confirm_order_{token}")],
            [InlineKeyboardButton("❌ 取消", callback_data=f"cancel_order_{token}")],
        ]
    )


def return_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 返回", callback_data="return_start")]])
