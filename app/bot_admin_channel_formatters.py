from telegram import InlineKeyboardButton, InlineKeyboardMarkup

ADMIN_CHANNELS_EMPTY_MESSAGE = (
    "📺 **频道/群组管理**\n\n目前没有管理的频道或群组。\n\n使用 `/add_channel` 添加频道或群组。"
)

ADD_CHANNEL_USAGE_MESSAGE = (
    "📺 **添加频道/群组**\n\n"
    "使用方法：\n"
    "`/add_channel @username 描述`\n"
    "`/add_channel -1001234567890 私人群组`\n\n"
    "**注意：**\n"
    "• 机器人必须是频道/群组的管理员\n"
    "• 对于私人群组，请使用群组的数字 ID\n"
    "• 对于公开频道，可使用 @username"
)

SET_CHANNEL_TOPIC_USAGE_MESSAGE = (
    "📌 **设置频道指定话题**\n\n"
    "使用方法：\n"
    "`/set_channel_topic 频道编号 topic_id [话题名称]`\n\n"
    "例如：\n"
    "`/set_channel_topic 1 12345 交易信号`"
)

CLEAR_CHANNEL_TOPIC_USAGE_MESSAGE = (
    "📌 **清除频道指定话题**\n\n使用方法：\n`/clear_channel_topic 频道编号`\n\n例如：\n`/clear_channel_topic 1`"
)

ADD_NEW_CHANNEL_CALLBACK_MESSAGE = (
    "📺 **添加频道/群组**\n\n"
    "请使用 `/add_channel` 命令添加新的频道或群组。\n\n"
    "使用方法：\n"
    "`/add_channel @username 描述`\n"
    "`/add_channel -1001234567890 私人群组`"
)

MANAGE_CHANNELS_EMPTY_MESSAGE = "📺 **管理频道**\n\n目前没有任何频道。\n\n使用 `/add_channel` 添加频道。"
DELETE_CHANNEL_PROMPT_MESSAGE = "🗑️ **删除频道**\n\n请输入要删除的频道编号："


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_channel_topic(channel) -> str:
    message_thread_id = channel.get("message_thread_id")
    if not message_thread_id:
        return "未设置"
    return escape_html(str(channel.get("thread_title") or message_thread_id))


def format_admin_channels_html(channels) -> str:
    channels_text = "📺 <b>已管理的频道/群组</b>\n\n"
    for channel in channels:
        status = "✅" if channel["auto_forward_signals"] else "❌"
        title = escape_html(str(channel["title"] or "Unknown"))
        chat_type = escape_html(str(channel["chat_type"]))
        username = channel["username"]

        channels_text += f"{status} <b>{title}</b>\n"
        channels_text += f"   类型: {chat_type}\n"
        channels_text += f"   ID: <code>{escape_html(str(channel['chat_id']))}</code>\n"
        if username:
            channels_text += f"   用户名: @{escape_html(str(username))}\n"
        channels_text += f"   自动转发: {'开启' if channel['auto_forward_signals'] else '关闭'}\n"
        channels_text += f"   指定话题: {format_channel_topic(channel)}\n\n"

    return channels_text


def format_manage_channels_html(channels_data) -> str:
    manage_text = "📺 <b>管理频道</b>\n\n"
    for channel in channels_data:
        title = escape_html(str(channel["title"]))
        username_text = f"(@{escape_html(str(channel['username']))})" if channel["username"] else ""
        manage_text += f"{channel['id']}. {title} {username_text}\n"

    return f"{manage_text}\n请选择操作："


def build_manage_channels_data(channels) -> list[dict]:
    return [
        {
            "id": index,
            "chat_id": channel["chat_id"],
            "title": channel["title"] or "Unknown",
            "username": channel["username"],
        }
        for index, channel in enumerate(channels, 1)
    ]


def format_channel_added_html(chat_title: str, chat_type: str, chat_id: int | str, description: str) -> str:
    return (
        f"✅ <b>频道/群组添加成功</b>\n\n"
        f"<b>名称：</b> {escape_html(str(chat_title))}\n"
        f"<b>类型：</b> {chat_type}\n"
        f"<b>ID：</b> <code>{chat_id}</code>\n"
        f"<b>描述：</b> {escape_html(description)}\n\n"
        "现在可以向此频道发送交易信号了！"
    )


def format_topic_set_html(channel_title: str, message_thread_id: int, display_title: str) -> str:
    return (
        f"✅ <b>指定话题已设置</b>\n\n"
        f"<b>频道：</b> {escape_html(str(channel_title or 'Unknown'))}\n"
        f"<b>Topic ID：</b> <code>{message_thread_id}</code>\n"
        f"<b>话题名称：</b> {escape_html(display_title)}"
    )


def format_topic_cleared_html(channel_title: str) -> str:
    return f"✅ <b>指定话题已清除</b>\n\n<b>频道：</b> {escape_html(str(channel_title or 'Unknown'))}"


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
