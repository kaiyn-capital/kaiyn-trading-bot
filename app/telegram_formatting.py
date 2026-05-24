from html import escape
from typing import Any

HTML_PARSE_MODE = "HTML"


def html_escape(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=True)


def html_code(value: Any) -> str:
    return f"<code>{html_escape(value)}</code>"


def html_bold(value: Any) -> str:
    return f"<b>{html_escape(value)}</b>"


def html_link(label: Any, url: Any) -> str:
    return f'<a href="{html_escape(url)}">{html_escape(label)}</a>'


def html_pre(value: Any) -> str:
    return f"<pre>{html_escape(value)}</pre>"
