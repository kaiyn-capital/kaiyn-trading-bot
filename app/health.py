import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from .settings import Settings
from .telegram_formatting import html_escape
from .time_utils import utc_now_naive

BACKUPS_DIR = Path("backups")
BACKUP_STATUS_FILE = "backup_status.json"


@dataclass(frozen=True)
class BackupHealth:
    status: str
    message: str
    timestamp: datetime | None = None
    filename: str | None = None

    @property
    def is_problem(self) -> bool:
        return self.status in {"failed", "missing", "stale", "invalid"}


@dataclass(frozen=True)
class MaintenanceHealth:
    status: str
    message: str
    timestamp: datetime | None = None

    @property
    def is_problem(self) -> bool:
        return self.status in {"failed", "missing", "stale"}


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def format_utc8(value: datetime | None) -> str:
    if not value:
        return "未知"
    return (value + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S UTC+8")


def format_duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if minutes or not parts:
        parts.append(f"{minutes} 分钟")
    return " ".join(parts)


def read_backup_health(
    backups_dir: Path = BACKUPS_DIR,
    stale_hours: int | None = None,
    now: datetime | None = None,
) -> BackupHealth:
    now = now or utc_now_naive()
    stale_hours = stale_hours if stale_hours is not None else Settings.from_env().backup_stale_hours
    status_path = backups_dir / BACKUP_STATUS_FILE

    if status_path.exists():
        try:
            with status_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            return BackupHealth("invalid", f"备份状态文件无法读取：{exc}")

        status = str(data.get("status") or "invalid")
        timestamp = parse_iso_datetime(data.get("timestamp"))
        filename = data.get("filename")
        if status == "failed":
            return BackupHealth(
                "failed",
                str(data.get("error") or "最近一次备份失败"),
                timestamp=timestamp,
                filename=filename,
            )
        if status != "success" or not timestamp:
            return BackupHealth("invalid", "备份状态文件内容不完整")
        if now - timestamp > timedelta(hours=stale_hours):
            return BackupHealth(
                "stale",
                f"最近备份超过 {stale_hours} 小时未更新",
                timestamp=timestamp,
                filename=filename,
            )
        return BackupHealth(
            "ok",
            "备份正常",
            timestamp=timestamp,
            filename=filename,
        )

    newest_backup = _find_newest_backup(backups_dir)
    if not newest_backup:
        return BackupHealth("missing", "找不到 PostgreSQL 备份文件")

    timestamp = datetime.utcfromtimestamp(newest_backup.stat().st_mtime)
    if now - timestamp > timedelta(hours=stale_hours):
        return BackupHealth(
            "stale",
            f"最近备份超过 {stale_hours} 小时未更新",
            timestamp=timestamp,
            filename=newest_backup.name,
        )

    return BackupHealth(
        "ok",
        "备份正常",
        timestamp=timestamp,
        filename=newest_backup.name,
    )


async def read_maintenance_health(
    system_log_repo,
    stale_hours: int | None = None,
    now: datetime | None = None,
) -> MaintenanceHealth:
    now = now or utc_now_naive()
    stale_hours = stale_hours if stale_hours is not None else Settings.from_env().maintenance_stale_hours
    latest = await system_log_repo.get_latest_log(
        module="maintenance",
        function="run_cleanup_retention",
    )
    if not latest:
        return MaintenanceHealth("missing", "尚无 cleanup 执行纪录")

    timestamp = latest.created_at
    if latest.level in {"ERROR", "CRITICAL"}:
        return MaintenanceHealth("failed", latest.message, timestamp=timestamp)
    if now - timestamp > timedelta(hours=stale_hours):
        return MaintenanceHealth(
            "stale",
            f"最近 cleanup 超过 {stale_hours} 小时未更新",
            timestamp=timestamp,
        )
    return MaintenanceHealth("ok", "cleanup 正常", timestamp=timestamp)


async def build_admin_health_report(
    db_manager,
    system_log_repo,
    started_at: datetime | None,
    pending_order_repo=None,
    user_session_repo=None,
    backups_dir: Path = BACKUPS_DIR,
    settings: Settings | None = None,
) -> tuple[str, dict]:
    now = utc_now_naive()
    settings = settings or Settings.from_env()
    db_ok = await db_manager.health_check()
    backup_health = read_backup_health(
        backups_dir=backups_dir,
        stale_hours=settings.backup_stale_hours,
        now=now,
    )
    maintenance_health = await read_maintenance_health(
        system_log_repo,
        stale_hours=settings.maintenance_stale_hours,
        now=now,
    )
    stale_processing_count = await _count_stale_processing_orders(
        pending_order_repo,
        now,
        settings.pending_order_reconcile_after_seconds,
    )
    active_session_count = await _count_active_user_sessions(user_session_repo, now)
    expired_session_count = await _count_expired_user_sessions(user_session_repo, now)
    recent_errors = await system_log_repo.get_recent_logs(
        levels=["ERROR", "CRITICAL"],
        since=now - timedelta(hours=24),
        limit=5,
    )
    bitget_logs = await system_log_repo.get_recent_logs(
        module="bitget_api",
        since=now - timedelta(hours=24),
        limit=50,
    )
    bitget_counts = _count_bitget_categories(bitget_logs)
    report = format_admin_health_report(
        db_ok=db_ok,
        backup_health=backup_health,
        maintenance_health=maintenance_health,
        recent_errors=recent_errors,
        bitget_counts=bitget_counts,
        started_at=started_at,
        stale_processing_count=stale_processing_count,
        active_session_count=active_session_count,
        expired_session_count=expired_session_count,
        processing_threshold_seconds=settings.pending_order_reconcile_after_seconds,
        now=now,
    )
    status = {
        "db_ok": db_ok,
        "backup_problem": backup_health.is_problem,
        "maintenance_problem": maintenance_health.is_problem,
        "bitget_counts": bitget_counts,
        "stale_processing_count": stale_processing_count,
        "active_session_count": active_session_count,
        "expired_session_count": expired_session_count,
        "recent_error_count": len(recent_errors),
    }
    return report, status


def format_admin_health_report(
    db_ok: bool,
    backup_health: BackupHealth,
    maintenance_health: MaintenanceHealth,
    recent_errors: list,
    bitget_counts: dict[str, int],
    started_at: datetime | None,
    stale_processing_count: int | None = None,
    active_session_count: int | None = None,
    expired_session_count: int | None = None,
    processing_threshold_seconds: int = 900,
    now: datetime | None = None,
) -> str:
    now = now or utc_now_naive()
    uptime = format_duration((now - started_at).total_seconds()) if started_at else "未知"
    db_text = "✅ 正常" if db_ok else "❌ 异常"
    backup_icon = "✅" if not backup_health.is_problem else "❌"
    maintenance_icon = "✅" if not maintenance_health.is_problem else "❌"
    bitget_text = _format_bitget_counts(bitget_counts)
    processing_text = _format_stale_processing_count(stale_processing_count, processing_threshold_seconds)
    session_text = _format_session_count(active_session_count, expired_session_count)
    error_text = _format_recent_errors(recent_errors)

    backup_msg_escaped = html_escape(backup_health.message)
    backup_file_escaped = html_escape(backup_health.filename) if backup_health.filename else "无"
    maint_msg_escaped = html_escape(maintenance_health.message)

    return (
        "🩺 <b>系统健康检查</b>\n\n"
        f"Bot：✅ 正常\n"
        f"Uptime：{uptime}\n"
        f"DB：{db_text}\n"
        f"Backup：{backup_icon} {backup_msg_escaped}\n"
        f"Backup 时间：{format_utc8(backup_health.timestamp)}\n"
        f"Backup 文件：{backup_file_escaped}\n"
        f"Maintenance：{maintenance_icon} {maint_msg_escaped}\n"
        f"Maintenance 时间：{format_utc8(maintenance_health.timestamp)}\n"
        f"Processing 卡单：{processing_text}\n"
        f"Sessions：{session_text}\n"
        f"Bitget API：{bitget_text}\n\n"
        f"最近错误：\n{error_text}"
    )


def _find_newest_backup(backups_dir: Path) -> Path | None:
    if not backups_dir.exists():
        return None
    backups = list(backups_dir.glob("kaiyn_trading_bot_*.sql.gz"))
    if not backups:
        return None
    return max(backups, key=lambda path: path.stat().st_mtime)


def _count_bitget_categories(logs: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for log in logs:
        try:
            extra_data = log.get_extra_data()
            category = extra_data.get("classified_error", {}).get("category") or extra_data.get("category")
        except (AttributeError, json.JSONDecodeError, TypeError):
            category = None
        if category:
            counts[category] = counts.get(category, 0) + 1
    return counts


async def _count_stale_processing_orders(
    pending_order_repo,
    now: datetime,
    threshold_seconds: int,
) -> int | None:
    if not pending_order_repo:
        return None
    cutoff = now - timedelta(seconds=threshold_seconds)
    try:
        result = await pending_order_repo.count_stale_processing_orders(cutoff)
        return int(result) if result is not None else None
    except SQLAlchemyError:
        return None


async def _count_active_user_sessions(user_session_repo, now: datetime) -> int | None:
    if not user_session_repo:
        return None
    try:
        result = await user_session_repo.count_active_sessions(now)
        return int(result) if result is not None else None
    except SQLAlchemyError:
        return None


async def _count_expired_user_sessions(user_session_repo, now: datetime) -> int | None:
    if not user_session_repo:
        return None
    try:
        result = await user_session_repo.count_expired_sessions(now)
        return int(result) if result is not None else None
    except SQLAlchemyError:
        return None


def _format_bitget_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "✅ 近 24 小时无系统级 API 异常"
    return "⚠️ " + " / ".join(f"{html_escape(category)}: {count}" for category, count in sorted(counts.items()))


def _format_stale_processing_count(count: int | None, threshold_seconds: int = 900) -> str:
    if count is None:
        return "未知"
    if count == 0:
        return "✅ 0 笔"
    threshold_minutes = max(int(threshold_seconds / 60), 1)
    return f"⚠️ {count} 笔超过 {threshold_minutes} 分钟"


def _format_session_count(active_count: int | None, expired_count: int | None) -> str:
    if active_count is None:
        return "未知"
    if expired_count is None:
        return f"{active_count} active"
    return f"{active_count} active / {expired_count} expired"


def _format_recent_errors(errors: list) -> str:
    if not errors:
        return "✅ 近 24 小时无 ERROR/CRITICAL"
    lines = []
    for error in errors[:5]:
        message = html_escape(str(error.message).replace("\n", " ")[:120])
        lines.append(f"- {format_utc8(error.created_at)} {error.level} {message}")
    return "\n".join(lines)
