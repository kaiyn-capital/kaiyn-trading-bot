from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .repository_types import ChannelRecord
from .telegram_formatting import html_code, html_escape

ADMIN_CHANNELS_EMPTY_MESSAGE = (
    "📺 <b>频道/群组管理</b>\n\n目前没有管理的频道或群组。\n\n使用 <code>/add_channel</code> 添加频道或群组。"
)

ADD_CHANNEL_USAGE_MESSAGE = (
    "📺 <b>添加频道/群组</b>\n\n"
    "使用方法：\n"
    "<code>/add_channel @username 描述</code>\n"
    "<code>/add_channel -1001234567890 私人群组</code>\n\n"
    "<b>注意：</b>\n"
    "• 机器人必须是频道/群组的管理员\n"
    "• 对于私人群组，请使用群组的数字 ID\n"
    "• 对于公开频道，可使用 @username"
)

SET_CHANNEL_TOPIC_USAGE_MESSAGE = (
    "📌 <b>设置频道指定话题</b>\n\n"
    "使用方法：\n"
    "<code>/set_channel_topic 频道编号 topic_id [话题名称]</code>\n\n"
    "例如：\n"
    "<code>/set_channel_topic 1 12345 交易信号</code>"
)

CLEAR_CHANNEL_TOPIC_USAGE_MESSAGE = "📌 <b>清除频道指定话题</b>\n\n使用方法：\n<code>/clear_channel_topic 频道编号</code>\n\n例如：\n<code>/clear_channel_topic 1</code>"

ADD_NEW_CHANNEL_CALLBACK_MESSAGE = (
    "📺 <b>添加频道/群组</b>\n\n"
    "请使用 <code>/add_channel</code> 命令添加新的频道或群组。\n\n"
    "使用方法：\n"
    "<code>/add_channel @username 描述</code>\n"
    "<code>/add_channel -1001234567890 私人群组</code>"
)

MANAGE_CHANNELS_EMPTY_MESSAGE = "📺 <b>管理频道</b>\n\n目前没有任何频道。\n\n使用 <code>/add_channel</code> 添加频道。"
DELETE_CHANNEL_PROMPT_MESSAGE = "🗑️ <b>删除频道</b>\n\n请输入要删除的频道编号："


def format_channel_topic(channel: ChannelRecord) -> str:
    message_thread_id = channel.message_thread_id
    if not message_thread_id:
        return "未设置"
    return html_escape(str(channel.thread_title or message_thread_id))


def format_admin_channels_html(channels: list[ChannelRecord]) -> str:
    channels_text = "📺 <b>已管理的频道/群组</b>\n\n"
    for channel in channels:
        status = "✅" if channel.auto_forward_signals else "❌"
        title = html_escape(str(channel.title or "Unknown"))
        chat_type = html_escape(str(channel.chat_type))
        username = channel.username

        channels_text += f"{status} <b>{title}</b>\n"
        channels_text += f"   类型: {chat_type}\n"
        channels_text += f"   ID: {html_code(channel.chat_id)}\n"
        if username:
            channels_text += f"   用户名: @{html_escape(str(username))}\n"
        channels_text += f"   自动转发: {'开启' if channel.auto_forward_signals else '关闭'}\n"
        channels_text += f"   指定话题: {format_channel_topic(channel)}\n\n"

    return channels_text


def format_manage_channels_html(channels_data) -> str:
    manage_text = "📺 <b>管理频道</b>\n\n"
    for channel in channels_data:
        title = html_escape(str(channel["title"]))
        username_text = f"(@{html_escape(str(channel['username']))})" if channel["username"] else ""
        manage_text += f"{channel['id']}. {title} {username_text}\n"

    return f"{manage_text}\n请选择操作："


def build_manage_channels_data(channels: list[ChannelRecord]) -> list[dict]:
    return [
        {
            "id": index,
            "chat_id": channel.chat_id,
            "title": channel.title or "Unknown",
            "username": channel.username,
        }
        for index, channel in enumerate(channels, 1)
    ]


def format_channel_added_html(chat_title: str, chat_type: str, chat_id: int | str, description: str) -> str:
    return (
        f"✅ <b>频道/群组添加成功</b>\n\n"
        f"<b>名称：</b> {html_escape(str(chat_title))}\n"
        f"<b>类型：</b> {html_escape(chat_type)}\n"
        f"<b>ID：</b> {html_code(chat_id)}\n"
        f"<b>描述：</b> {html_escape(description)}\n\n"
        "现在可以向此频道发送交易信号了！"
    )


def format_topic_set_html(channel_title: str, message_thread_id: int, display_title: str) -> str:
    return (
        f"✅ <b>指定话题已设置</b>\n\n"
        f"<b>频道：</b> {html_escape(str(channel_title or 'Unknown'))}\n"
        f"<b>Topic ID：</b> {html_code(message_thread_id)}\n"
        f"<b>话题名称：</b> {html_escape(display_title)}"
    )


def format_topic_cleared_html(channel_title: str) -> str:
    return f"✅ <b>指定话题已清除</b>\n\n<b>频道：</b> {html_escape(str(channel_title or 'Unknown'))}"


def admin_channels_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 添加频道", callback_data="add_new_channel")],
            [InlineKeyboardButton("⚙️ 管理设置", callback_data="manage_channels")],
        ]
    )


def manage_channels_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑️ 删除频道", callback_data="delete_channel_start")],
            [InlineKeyboardButton("🔙 返回", callback_data="return_admin_channels")],
        ]
    )
