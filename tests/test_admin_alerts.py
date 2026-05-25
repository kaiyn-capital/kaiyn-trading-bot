import pytest
from settings_factory import make_settings

from app.admin_alerts import AdminAlertManager, AlertStateStore
from app.bitget_errors import BitgetErrorCategory, ClassifiedBitgetError


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


@pytest.mark.asyncio
async def test_bitget_failure_alerts_after_threshold(tmp_path):
    bot = FakeBot()
    system_log_repo = FakeSystemLogRepo()
    manager = AdminAlertManager(
        bot,
        system_log_repo,
        AlertStateStore(tmp_path / "alert_state.json"),
        settings=make_settings(
            admin_ids=(111,),
            bitget_alert_failure_threshold=3,
            bitget_alert_window_seconds=600,
            admin_alert_cooldown_seconds=1800,
        ),
    )
    classified = ClassifiedBitgetError(
        category=BitgetErrorCategory.NETWORK,
        user_message="网络连接异常，请稍后重新点击最新信号下单。",
        raw_code="timeout",
        raw_message="timeout",
        is_retryable=True,
    )

    await manager.record_bitget_failure(classified, "status_command")
    await manager.record_bitget_failure(classified, "status_command")
    assert bot.messages == []

    await manager.record_bitget_failure(classified, "status_command")
    assert len(bot.messages) == 1
    assert "Bitget API 连续异常" in bot.messages[0]["text"]
    assert bot.messages[0]["kwargs"]["parse_mode"] == "HTML"
    assert len(system_log_repo.logs) == 3

    await manager.record_bitget_failure(classified, "status_command")
    assert len(bot.messages) == 1


@pytest.mark.asyncio
async def test_user_config_error_does_not_alert_admin(tmp_path):
    bot = FakeBot()
    manager = AdminAlertManager(
        bot,
        FakeSystemLogRepo(),
        AlertStateStore(tmp_path / "alert_state.json"),
        settings=make_settings(admin_ids=(111,)),
    )
    classified = ClassifiedBitgetError(
        category=BitgetErrorCategory.USER_CONFIG,
        user_message="API 设置或权限异常，请检查 API Key 权限。",
    )

    result = await manager.record_bitget_failure(classified, "balance_command")

    assert result is False
    assert bot.messages == []
