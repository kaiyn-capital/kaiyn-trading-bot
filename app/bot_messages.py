from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .decimal_utils import decimal_text
from .order_flow import OrderExecutionResult, OrderPreview, SignalDraft

UTC_PLUS_8 = timezone(timedelta(hours=8))


def escape_markdown(text: str) -> str:
    if not text:
        return text

    # Only escape legacy Markdown (V1) special characters to avoid literal backslashes in Telegram client
    escape_chars = [
        "_",
        "*",
        "[",
        "`",
    ]
    for char in escape_chars:
        text = text.replace(char, f"\\{char}")
    return text


def welcome_message() -> str:
    return """
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


def help_message() -> str:
    return """
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
• `/update_chart` - 更新既有交易信号图表（原发单者或管理员）
• 📊 **信号交易** - 当管理员发送交易信号时可一键下单

**管理员功能：**（仅管理员可用）
• `/admin` - 管理员面板


**安全须知：**
🔒 所有 API 信息都会加密存储
🔒 输入的 API 密钥会自动删除保护隐私
🔒 只给予交易权限，不要给予提币权限
        """


def settings_message(risk_amount: float | None) -> str:
    risk_text = f"{decimal_text(risk_amount)} USDT" if risk_amount else "未设置"
    return f"""
⚙️ **交易设置**

**当前设置：**
• 固定风险金额(1R)：{risk_text}

**风险管理：**
固定风险金额(1R)用于计算每笔交易的开仓金额
        """


def signal_usage_message() -> str:
    return (
        "📊 **发送交易信号 - 格式**\n\n"
        "使用方法：\n"
        "`/send_signal 交易对 方向 entry[进场价1 进场价2] sl[止损价] tp[止盈价1 止盈价2] [备注文字]`\n\n"
        "例如：\n"
        "`/send_signal PUMPUSDT long entry[0.00179] sl[0.00156] tp[0.0022 0.00268]`\n"
        "`/send_signal BTCUSDT short entry[80200 81000] sl[81700] tp[77777 75000] 等待回踩后执行`"
    )


def _format_signal_price(value) -> str:
    return decimal_text(value)


def _format_usdt(value, places: int = 2) -> str:
    return f"{Decimal(decimal_text(value)):.{places}f}"


def _format_price(value, places: int = 4) -> str:
    return f"{Decimal(decimal_text(value)):,.{places}f}"


def _format_signal_entry(signal: SignalDraft) -> str:
    lower = _format_signal_price(signal.entry_lower)
    upper = _format_signal_price(signal.entry_upper)
    if lower == upper:
        return lower
    return f"{upper}-{lower}"


def signal_message(signal: SignalDraft, sender_username: str, signal_id: str | None = None) -> str:
    direction_text = "多 Long" if signal.direction == "long" else "空 Short"
    tp_text = "/".join([_format_signal_price(tp) for tp in signal.take_profit_levels])
    signal_time = datetime.now(UTC_PLUS_8).strftime("%Y-%m-%d %H:%M:%S")

    text = f"🚨 **交易信号** by @{sender_username}\n\n"
    text += f"**Symbol：** {signal.symbol}\n"
    text += f"**Direction：** {direction_text}\n"
    text += f"**Entry：** {_format_signal_entry(signal)}\n"
    text += f"**TP：** {tp_text}\n"
    text += f"**SL：** {_format_signal_price(signal.stop_loss)}\n"
    if signal.remark:
        text += f"{escape_markdown(signal.remark)}\n"
    text += "\n"
    if signal_id:
        text += f"交易id: `{signal_id}`\n"
    text += f"⏰ {signal_time} UTC+8"
    return text


def chart_update_message(signal_id: str, remark: str = "") -> str:
    update_time = datetime.now(UTC_PLUS_8).strftime("%Y-%m-%d %H:%M:%S")
    text = ""
    if remark:
        text += f"{escape_markdown(remark)}\n\n"
    text += f"交易id: `{signal_id}`\n"
    text += f"⏰ {update_time} UTC+8"
    return text


def signal_sent_message(sent_to_channels: int, signal_text: str) -> str:
    return f"✅ **交易信号已发送**\n\n📺 发送到频道：{sent_to_channels} 个\n\n**信号详情：**\n{signal_text}"


def order_preview_message(symbol: str, direction: str, preview: OrderPreview) -> str:
    direction_text = "做多" if direction == "long" else "做空"
    order_mode_text = "市价下单" if preview.order_mode == "market" else "挂单"

    text = "💰 **交易确认**\n\n"
    if preview.switch_notice:
        text += preview.switch_notice
    text += f"**交易对：** {symbol}\n"
    text += f"**方向：** {direction_text}\n"
    text += f"**下单方式：** {order_mode_text}\n"
    text += f"**当前价格：** ${_format_price(preview.current_price)}\n"
    if preview.order_mode == "limit":
        limit_price_text = preview.limit_price_text or _format_price(preview.limit_price)
        text += f"**挂单价格：** ${limit_price_text}\n"
    text += f"**止损价格：** ${_format_price(preview.stop_loss)}\n"
    quantity_text = preview.quantity_text or decimal_text(preview.quantity, 6)
    text += f"**交易数量：** {quantity_text}\n"
    text += f"**名义价值：** ${_format_usdt(preview.position_value)}\n"
    text += f"**风险金额(1R)：** ${_format_usdt(preview.risk_amount)}\n"
    text += f"**止损距离：** {_format_usdt(preview.stop_distance_pct * Decimal('100'))}%\n\n"
    if preview.order_mode == "limit":
        text += "⚠️ 将送出 GTC 限价挂单，订单送出不代表已成交"
    else:
        text += "⚠️ 将使用市价单进场"
    return text


def order_success_message(
    result: OrderExecutionResult,
    direction: str,
    stop_loss,
    current_price,
    risk_amount,
) -> str:
    is_limit_order = result.order_type == "limit"
    text = "✅ **挂单已送出**\n\n" if is_limit_order else "✅ **下单成功**\n\n"
    text += f"**币种：** {result.symbol}\n"
    text += f"**方向：** {'做多' if direction == 'long' else '做空'}\n"
    text += f"**下单方式：** {'挂单' if is_limit_order else '市价'}\n"
    text += f"**仓位名义价值：** ${_format_usdt(result.position_value)}\n"
    text += f"**止损：** ${_format_price(stop_loss)}\n"
    if is_limit_order:
        text += f"**挂单价格：** ${_format_price(result.limit_price)}\n"
        text += f"**当前价格：** ${_format_price(current_price)}\n"
    else:
        text += f"**进场价格：** ${_format_price(current_price)}\n"
    text += f"**当前 1R 设置：** ${_format_usdt(risk_amount)}\n"
    text += f"**订单 ID：** {result.bitget_order_id[:16]}...\n\n"
    text += "✅ 止损已同时设置"
    if is_limit_order:
        text += "\n⚠️ 挂单成功代表订单已送出，不代表已成交"
    return text
