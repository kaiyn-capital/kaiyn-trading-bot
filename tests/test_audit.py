import asyncio
from datetime import datetime
from types import SimpleNamespace

from app.audit import (
    AUDIT_MODULE,
    format_audit_log_entry,
    record_audit_event,
    summarize_identifier,
    summarize_message_text,
)


class FakeSystemLogRepo:
    def __init__(self):
        self.logs = []

    async def log(self, **kwargs):
        self.logs.append(kwargs)


def test_summarize_identifier_masks_value():
    assert summarize_identifier("pending-token-abcdef123456") == "***3456"
    assert summarize_identifier(None) is None


def test_summarize_message_text_returns_length_and_preview():
    summary = summarize_message_text("x" * 100, preview_chars=10)

    assert summary == {"length": 100, "preview": "xxxxxxxxxx..."}


def test_record_audit_event_uses_audit_module_and_function():
    repo = FakeSystemLogRepo()
    user = SimpleNamespace(id=7, telegram_id=123)

    asyncio.run(
        record_audit_event(
            repo,
            user,
            "admin_add_trader",
            {"status": "success", "target_telegram_id": 456},
        )
    )

    assert repo.logs == [
        {
            "level": "INFO",
            "message": "Audit: admin_add_trader",
            "module": AUDIT_MODULE,
            "function": "admin_add_trader",
            "user_id": 7,
            "telegram_id": 123,
            "extra_data": {"status": "success", "target_telegram_id": 456},
        }
    ]


def test_format_audit_log_entry_uses_utc_plus_8_and_summary():
    log_entry = SimpleNamespace(
        created_at=datetime(2026, 5, 12, 1, 2, 3),
        function="signal_sent",
        telegram_id=123,
        extra_data={
            "status": "completed",
            "symbol": "BTCUSDT",
            "direction": "short",
            "target_count": 2,
            "sent_count": 1,
            "failed_count": 1,
        },
    )

    line = format_audit_log_entry(log_entry)

    assert line.startswith("05-12 09:02:03 | signal_sent | TG:123")
    assert "symbol=BTCUSDT" in line
    assert "target_count=2" in line
