import html
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import Config

BACKUPS_DIR = Path("backups")
BACKUP_STATUS_FILE = "backup_status.json"


@dataclass(frozen=True)
class BackupHealth:
    status: str
    message: str
    timestamp: Optional[datetime] = None
    filename: Optional[str] = None

    @property
    def is_problem(self) -> bool:
        return self.status in {"failed", "missing", "stale", "invalid"}


@dataclass(frozen=True)
class MaintenanceHealth:
    status: str
    message: str
    timestamp: Optional[datetime] = None

    @property
    def is_problem(self) -> bool:
        return self.status in {"failed", "missing", "stale"}


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def format_utc8(value: Optional[datetime]) -> str:
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
    stale_hours: int = Config.BACKUP_STALE_HOURS,
    now: Optional[datetime] = None,
) -> BackupHealth:
    now = now or datetime.utcnow()
    status_path = backups_dir / BACKUP_STATUS_FILE

    if status_path.exists():
        try:
            with status_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception as exc:
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
    stale_hours: int = Config.MAINTENANCE_STALE_HOURS,
    now: Optional[datetime] = None,
) -> MaintenanceHealth:
    now = now or datetime.utcnow()
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
    started_at: Optional[datetime],
    pending_order_repo=None,
    backups_dir: Path = BACKUPS_DIR,
) -> tuple[str, dict]:
    now = datetime.utcnow()
    db_ok = await db_manager.health_check()
    backup_health = read_backup_health(backups_dir=backups_dir, now=now)
    maintenance_health = await read_maintenance_health(system_log_repo, now=now)
    stale_processing_count = await _count_stale_processing_orders(pending_order_repo, now)
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
        now=now,
    )
    status = {
        "db_ok": db_ok,
        "backup_problem": backup_health.is_problem,
        "maintenance_problem": maintenance_health.is_problem,
        "bitget_counts": bitget_counts,
        "stale_processing_count": stale_processing_count,
        "recent_error_count": len(recent_errors),
    }
    return report, status


def format_admin_health_report(
    db_ok: bool,
    backup_health: BackupHealth,
    maintenance_health: MaintenanceHealth,
    recent_errors: list,
    bitget_counts: dict[str, int],
    started_at: Optional[datetime],
    stale_processing_count: Optional[int] = None,
    now: Optional[datetime] = None,
) -> str:
    now = now or datetime.utcnow()
    uptime = format_duration((now - started_at).total_seconds()) if started_at else "未知"
    db_text = "✅ 正常" if db_ok else "❌ 异常"
    backup_icon = "✅" if not backup_health.is_problem else "❌"
    maintenance_icon = "✅" if not maintenance_health.is_problem else "❌"
    bitget_text = _format_bitget_counts(bitget_counts)
    processing_text = _format_stale_processing_count(stale_processing_count)
    error_text = _format_recent_errors(recent_errors)

    backup_msg_escaped = html.escape(backup_health.message)
    backup_file_escaped = html.escape(backup_health.filename) if backup_health.filename else "无"
    maint_msg_escaped = html.escape(maintenance_health.message)

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
        f"Bitget API：{bitget_text}\n\n"
        f"最近错误：\n{error_text}"
    )


def _find_newest_backup(backups_dir: Path) -> Optional[Path]:
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
        except Exception:
            category = None
        if category:
            counts[category] = counts.get(category, 0) + 1
    return counts


async def _count_stale_processing_orders(pending_order_repo, now: datetime) -> Optional[int]:
    if not pending_order_repo:
        return None
    cutoff = now - timedelta(seconds=Config.PENDING_ORDER_RECONCILE_AFTER_SECONDS)
    try:
        return await pending_order_repo.count_stale_processing_orders(cutoff)
    except Exception:
        return None


def _format_bitget_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "✅ 近 24 小时无系统级 API 异常"
    return "⚠️ " + " / ".join(f"{html.escape(category)}: {count}" for category, count in sorted(counts.items()))


def _format_stale_processing_count(count: Optional[int]) -> str:
    if count is None:
        return "未知"
    if count == 0:
        return "✅ 0 笔"
    threshold_minutes = max(int(Config.PENDING_ORDER_RECONCILE_AFTER_SECONDS / 60), 1)
    return f"⚠️ {count} 笔超过 {threshold_minutes} 分钟"


def _format_recent_errors(errors: list) -> str:
    if not errors:
        return "✅ 近 24 小时无 ERROR/CRITICAL"
    lines = []
    for error in errors[:5]:
        message = html.escape(str(error.message).replace("\n", " ")[:120])
        lines.append(f"- {format_utc8(error.created_at)} {error.level} {message}")
    return "\n".join(lines)
