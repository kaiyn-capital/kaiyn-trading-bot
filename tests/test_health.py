import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.health import (
    format_admin_health_report,
    read_backup_health,
    read_maintenance_health,
)


def write_backup_status(path, data):
    path.mkdir(parents=True, exist_ok=True)
    (path / "backup_status.json").write_text(
        json.dumps(data),
        encoding="utf-8",
    )


def test_backup_health_reads_success_status(tmp_path):
    now = datetime(2026, 5, 13, 12, 0, 0)
    write_backup_status(
        tmp_path,
        {
            "status": "success",
            "timestamp": "2026-05-13T11:30:00Z",
            "filename": "kaiyn_trading_bot_20260513_113000.sql.gz",
        },
    )

    result = read_backup_health(tmp_path, stale_hours=36, now=now)

    assert result.status == "ok"
    assert result.filename == "kaiyn_trading_bot_20260513_113000.sql.gz"


def test_backup_health_reports_failure_status(tmp_path):
    write_backup_status(
        tmp_path,
        {
            "status": "failed",
            "timestamp": "2026-05-13T11:30:00Z",
            "filename": "kaiyn_trading_bot_20260513_113000.sql.gz",
            "error": "pg_dump failed",
        },
    )

    result = read_backup_health(tmp_path)

    assert result.status == "failed"
    assert result.is_problem is True
    assert result.message == "pg_dump failed"


def test_backup_health_reports_stale_status(tmp_path):
    now = datetime(2026, 5, 13, 12, 0, 0)
    write_backup_status(
        tmp_path,
        {
            "status": "success",
            "timestamp": "2026-05-11T00:00:00Z",
            "filename": "kaiyn_trading_bot_20260511_000000.sql.gz",
        },
    )

    result = read_backup_health(tmp_path, stale_hours=36, now=now)

    assert result.status == "stale"
    assert result.is_problem is True


class FakeSystemLogRepo:
    def __init__(self, latest):
        self.latest = latest

    async def get_latest_log(self, **kwargs):
        return self.latest


@pytest.mark.asyncio
async def test_maintenance_health_reports_recent_success():
    latest = SimpleNamespace(
        level="INFO",
        message="Retention cleanup completed",
        created_at=datetime.utcnow(),
    )

    result = await read_maintenance_health(FakeSystemLogRepo(latest))

    assert result.status == "ok"


@pytest.mark.asyncio
async def test_maintenance_health_reports_stale_success():
    now = datetime(2026, 5, 13, 12, 0, 0)
    latest = SimpleNamespace(
        level="INFO",
        message="Retention cleanup completed",
        created_at=now - timedelta(hours=48),
    )

    result = await read_maintenance_health(FakeSystemLogRepo(latest), stale_hours=36, now=now)

    assert result.status == "stale"


def test_admin_health_report_includes_core_sections():
    report = format_admin_health_report(
        db_ok=True,
        backup_health=SimpleNamespace(
            is_problem=False,
            message="备份正常",
            timestamp=datetime(2026, 5, 13, 12, 0, 0),
            filename="backup.sql.gz",
        ),
        maintenance_health=SimpleNamespace(
            is_problem=False,
            message="cleanup 正常",
            timestamp=datetime(2026, 5, 13, 12, 0, 0),
        ),
        recent_errors=[],
        bitget_counts={},
        started_at=datetime(2026, 5, 13, 11, 30, 0),
        now=datetime(2026, 5, 13, 12, 0, 0),
    )

    assert "<b>系统健康检查</b>" in report
    assert "DB：✅ 正常" in report
    assert "Backup：✅ 备份正常" in report
    assert "Bitget API：✅" in report


def test_admin_health_report_escapes_html():
    report = format_admin_health_report(
        db_ok=True,
        backup_health=SimpleNamespace(
            is_problem=False,
            message="备份 <test> &正常",
            timestamp=datetime(2026, 5, 13, 12, 0, 0),
            filename="backup_&_test.sql.gz",
        ),
        maintenance_health=SimpleNamespace(
            is_problem=False,
            message="cleanup 正常",
            timestamp=datetime(2026, 5, 13, 12, 0, 0),
        ),
        recent_errors=[
            SimpleNamespace(
                created_at=datetime(2026, 5, 13, 12, 0, 0),
                level="ERROR",
                message="Error with <script> tag",
            )
        ],
        bitget_counts={"BAD_&_PARAMS": 1},
        started_at=datetime(2026, 5, 13, 11, 30, 0),
        now=datetime(2026, 5, 13, 12, 0, 0),
    )

    assert "备份 &lt;test&gt; &amp;正常" in report
    assert "backup_&amp;_test.sql.gz" in report
    assert "Error with &lt;script&gt; tag" in report
    assert "BAD_&amp;_PARAMS" in report
