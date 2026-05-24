import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from .bitget_errors import BitgetErrorCategory, ClassifiedBitgetError
from .config import Config
from .telegram_formatting import HTML_PARSE_MODE, html_escape

logger = logging.getLogger(__name__)


ALERT_STATE_PATH = Path("logs/alert_state.json")
ALERTABLE_BITGET_CATEGORIES = {
    BitgetErrorCategory.NETWORK,
    BitgetErrorCategory.TEMPORARY_EXCHANGE,
    BitgetErrorCategory.UNKNOWN,
}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _safe_admin_ids() -> list[int]:
    try:
        return Config.get_admin_ids()
    except Exception as exc:
        logger.error(f"Invalid TELEGRAM_ADMIN_IDS for admin alert: {exc}")
        return []


class AlertStateStore:
    def __init__(self, path: Path = ALERT_STATE_PATH):
        self.path = path

    def load(self) -> dict:
        if not self.path.exists():
            return {"sent": {}}
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                return {"sent": {}}
            data.setdefault("sent", {})
            return data
        except Exception as exc:
            logger.warning(f"Failed to load alert state: {exc}")
            return {"sent": {}}

    def save(self, state: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)

    def should_send(
        self,
        alert_key: str,
        cooldown_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        state = self.load()
        sent = state.setdefault("sent", {})
        now = now or _utcnow()
        last_sent = _parse_iso_datetime(sent.get(alert_key))
        if last_sent and now - last_sent < timedelta(seconds=cooldown_seconds):
            return False

        sent[alert_key] = now.isoformat()
        self.save(state)
        return True


async def send_direct_admin_alert(
    text: str,
    alert_key: str | None = None,
    cooldown_seconds: int | None = None,
    state_store: AlertStateStore | None = None,
) -> bool:
    token = Config.TELEGRAM_BOT_TOKEN
    admin_ids = _safe_admin_ids()
    if not token or not admin_ids:
        logger.warning("Skipping direct admin alert because Telegram config is missing")
        return False

    state_store = state_store or AlertStateStore()
    if alert_key:
        cooldown = cooldown_seconds or Config.ADMIN_ALERT_COOLDOWN_SECONDS
        if not state_store.should_send(alert_key, cooldown):
            return False

    sent_any = False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        for admin_id in admin_ids:
            try:
                response = await client.post(
                    url,
                    json={"chat_id": admin_id, "text": text, "parse_mode": HTML_PARSE_MODE},
                )
                response.raise_for_status()
                sent_any = True
            except Exception as exc:
                logger.error(f"Failed to send direct admin alert to {admin_id}: {exc}")

    return sent_any


class AdminAlertManager:
    def __init__(
        self,
        bot,
        system_log_repo=None,
        state_store: AlertStateStore | None = None,
    ):
        self.bot = bot
        self.system_log_repo = system_log_repo
        self.state_store = state_store or AlertStateStore()
        self.bitget_failures: dict[str, list[datetime]] = {}

    async def send_alert(
        self,
        text: str,
        alert_key: str | None = None,
        cooldown_seconds: int | None = None,
    ) -> bool:
        admin_ids = _safe_admin_ids()
        if not admin_ids:
            logger.warning("Skipping admin alert because TELEGRAM_ADMIN_IDS is empty")
            return False

        if alert_key:
            cooldown = cooldown_seconds or Config.ADMIN_ALERT_COOLDOWN_SECONDS
            if not self.state_store.should_send(alert_key, cooldown):
                return False

        sent_any = False
        for admin_id in admin_ids:
            try:
                await self.bot.send_message(chat_id=admin_id, text=text, parse_mode=HTML_PARSE_MODE)
                sent_any = True
            except Exception as exc:
                logger.error(f"Failed to send admin alert to {admin_id}: {exc}")

        return sent_any

    async def alert_startup_success(self):
        if not Config.ADMIN_NOTIFY_STARTUP_SUCCESS:
            return False
        return await self.send_alert(
            "✅ Kaiyn Trading Bot 已启动成功。",
            alert_key="startup_success",
        )

    async def alert_startup_failure(self, error: Exception):
        return await send_direct_admin_alert(
            f"❌ Kaiyn Trading Bot 启动失败。\n\n错误：{html_escape(error)}",
            alert_key="startup_failure",
        )

    async def alert_db_failure(self, source: str, error: Exception | None = None):
        suffix = f"\n\n错误：{html_escape(error)}" if error else ""
        return await self.send_alert(
            f"❌ Kaiyn Trading Bot DB 健康检查失败。\n\n来源：{html_escape(source)}{suffix}",
            alert_key=f"db_failure:{source}",
        )

    async def alert_backup_problem(self, message: str):
        return await self.send_alert(
            f"❌ Kaiyn Trading Bot 备份状态异常。\n\n{html_escape(message)}",
            alert_key="backup_problem",
        )

    async def alert_maintenance_problem(self, message: str):
        return await self.send_alert(
            f"❌ Kaiyn Trading Bot 维护任务异常。\n\n{html_escape(message)}",
            alert_key="maintenance_problem",
        )

    async def record_bitget_failure(
        self,
        classified_error: ClassifiedBitgetError,
        source: str,
        context: dict | None = None,
    ) -> bool:
        if classified_error.category not in ALERTABLE_BITGET_CATEGORIES:
            return False

        await self._log_bitget_failure(classified_error, source, context or {})

        category = classified_error.category.value
        now = _utcnow()
        window_start = now - timedelta(seconds=Config.BITGET_ALERT_WINDOW_SECONDS)
        failures = [timestamp for timestamp in self.bitget_failures.get(category, []) if timestamp >= window_start]
        failures.append(now)
        self.bitget_failures[category] = failures

        if len(failures) < Config.BITGET_ALERT_FAILURE_THRESHOLD:
            return False

        return await self.send_alert(
            "⚠️ Kaiyn Trading Bot Bitget API 连续异常。\n\n"
            f"分类：{html_escape(category)}\n"
            f"次数：{len(failures)} / {Config.BITGET_ALERT_WINDOW_SECONDS} 秒\n"
            f"来源：{html_escape(source)}\n"
            f"最近错误：{html_escape(classified_error.storage_message())}",
            alert_key=f"bitget_failure:{category}",
        )

    async def _log_bitget_failure(
        self,
        classified_error: ClassifiedBitgetError,
        source: str,
        context: dict,
    ):
        if not self.system_log_repo:
            return
        try:
            await self.system_log_repo.log(
                level="WARNING",
                message="Bitget API classified failure",
                module="bitget_api",
                function=source,
                extra_data={
                    "classified_error": classified_error.to_log_data(),
                    "context": context,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to persist Bitget failure log: {exc}")
