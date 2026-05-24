import json
from datetime import timedelta
from typing import Any

from .log_sanitizer import mask_value

AUDIT_MODULE = "audit"
AUDIT_TIME_OFFSET = timedelta(hours=8)


def summarize_identifier(value: Any) -> str | None:
    """Mask identifiers while keeping enough tail characters for tracing."""
    return mask_value(value)


def summarize_message_text(text: str | None, preview_chars: int = 80) -> dict[str, Any]:
    """Return message length plus a short preview without storing full text by intent."""
    if not text:
        return {"length": 0, "preview": None}

    preview = text[:preview_chars]
    if len(text) > preview_chars:
        preview = f"{preview}..."

    return {
        "length": len(text),
        "preview": preview,
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


async def emit_audit_event(owner: Any, user: Any, action: str, details: dict[str, Any] | None = None) -> None:
    """Call the bot audit hook when available; tests can omit it safely."""
    audit_method = getattr(owner, "_audit_action", None)
    if not callable(audit_method):
        return

    await audit_method(user, action, details or {})


async def record_audit_event(
    system_log_repo: Any,
    user: Any,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist one structured audit event into system_logs."""
    await system_log_repo.log(
        level="INFO",
        message=f"Audit: {action}",
        module=AUDIT_MODULE,
        function=action,
        user_id=getattr(user, "id", None),
        telegram_id=getattr(user, "telegram_id", None),
        extra_data=_json_safe(details or {}),
    )


def parse_log_extra_data(log_entry: Any) -> dict[str, Any]:
    if hasattr(log_entry, "get_extra_data"):
        try:
            data = log_entry.get_extra_data()
            return data if isinstance(data, dict) else {}
        except (AttributeError, json.JSONDecodeError, TypeError):
            return {}

    raw_data = getattr(log_entry, "extra_data", None)
    if isinstance(raw_data, dict):
        return raw_data
    if isinstance(raw_data, str) and raw_data:
        try:
            data = json.loads(raw_data)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def format_audit_log_entry(log_entry: Any) -> str:
    created_at = getattr(log_entry, "created_at", None)
    if created_at:
        display_time = (created_at + AUDIT_TIME_OFFSET).strftime("%m-%d %H:%M:%S")
    else:
        display_time = "未知时间"

    action = getattr(log_entry, "function", None) or "unknown"
    telegram_id = getattr(log_entry, "telegram_id", None) or "-"
    data = parse_log_extra_data(log_entry)
    summary = _format_audit_summary(data)

    if summary:
        return f"{display_time} | {action} | TG:{telegram_id} | {summary}"
    return f"{display_time} | {action} | TG:{telegram_id}"


def _format_audit_summary(data: dict[str, Any]) -> str:
    priority_keys = [
        "status",
        "symbol",
        "direction",
        "order_mode",
        "requested_order_mode",
        "target_telegram_id",
        "chat_id",
        "channel_title",
        "target_count",
        "sent_count",
        "failed_count",
        "reason",
        "error_category",
    ]
    parts = []
    for key in priority_keys:
        value = data.get(key)
        if value is not None:
            parts.append(f"{key}={value}")

    if not parts and data:
        for key, value in list(data.items())[:4]:
            if value is not None:
                parts.append(f"{key}={value}")

    return ", ".join(parts[:6])
