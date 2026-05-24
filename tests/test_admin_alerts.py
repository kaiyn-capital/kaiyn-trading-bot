import asyncio

from app.admin_alerts import AdminAlertManager, AlertStateStore
from app.bitget_errors import BitgetErrorCategory, ClassifiedBitgetError
from app.config import Config


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class FakeSystemLogRepo:
    def __init__(self):
        self.logs = []

    async def log(self, **kwargs):
        self.logs.append(kwargs)


def test_alert_state_store_enforces_cooldown(tmp_path):
    store = AlertStateStore(tmp_path / "alert_state.json")

    assert store.should_send("startup", cooldown_seconds=60) is True
    assert store.should_send("startup", cooldown_seconds=60) is False


def test_bitget_failure_alerts_after_threshold(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "get_admin_ids", classmethod(lambda cls: [111]))
    monkeypatch.setattr(Config, "BITGET_ALERT_FAILURE_THRESHOLD", 3)
    monkeypatch.setattr(Config, "BITGET_ALERT_WINDOW_SECONDS", 600)
    monkeypatch.setattr(Config, "ADMIN_ALERT_COOLDOWN_SECONDS", 1800)

    bot = FakeBot()
    system_log_repo = FakeSystemLogRepo()
    manager = AdminAlertManager(
        bot,
        system_log_repo,
        AlertStateStore(tmp_path / "alert_state.json"),
    )
    classified = ClassifiedBitgetError(
        category=BitgetErrorCategory.NETWORK,
        user_message="网络连接异常，请稍后重新点击最新信号下单。",
        raw_code="timeout",
        raw_message="timeout",
        is_retryable=True,
    )

    asyncio.run(manager.record_bitget_failure(classified, "status_command"))
    asyncio.run(manager.record_bitget_failure(classified, "status_command"))
    assert bot.messages == []

    asyncio.run(manager.record_bitget_failure(classified, "status_command"))
    assert len(bot.messages) == 1
    assert "Bitget API 连续异常" in bot.messages[0]["text"]
    assert bot.messages[0]["kwargs"]["parse_mode"] == "HTML"
    assert len(system_log_repo.logs) == 3

    asyncio.run(manager.record_bitget_failure(classified, "status_command"))
    assert len(bot.messages) == 1


def test_user_config_error_does_not_alert_admin(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "get_admin_ids", classmethod(lambda cls: [111]))
    bot = FakeBot()
    manager = AdminAlertManager(
        bot,
        FakeSystemLogRepo(),
        AlertStateStore(tmp_path / "alert_state.json"),
    )
    classified = ClassifiedBitgetError(
        category=BitgetErrorCategory.USER_CONFIG,
        user_message="API 设置或权限异常，请检查 API Key 权限。",
    )

    result = asyncio.run(manager.record_bitget_failure(classified, "balance_command"))

    assert result is False
    assert bot.messages == []
