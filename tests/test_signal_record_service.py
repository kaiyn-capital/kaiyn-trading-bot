from types import SimpleNamespace

import pytest

from app.order_types import SignalDraft
from app.signal_record_service import SignalRecordService


class FakeSignalRecordRepo:
    def __init__(self):
        self.records = {}
        self.status_updates = []
        self.created = []

    async def get_by_public_id(self, public_id):
        return self.records.get(public_id)

    async def create_signal_record(
        self,
        *,
        public_id,
        user_id,
        sender_telegram_id,
        sender_username,
        signal,
        signal_text,
        granularity,
        chart_status,
        chart_error,
    ):
        record = {
            "id": len(self.created) + 1,
            "public_id": public_id,
            "user_id": user_id,
            "sender_telegram_id": sender_telegram_id,
            "sender_username": sender_username,
            "symbol": signal.symbol,
            "direction": signal.direction,
            "entry_lower": signal.entry_lower,
            "entry_upper": signal.entry_upper,
            "stop_loss": signal.stop_loss,
            "take_profit_levels": signal.take_profit_levels,
            "remark": signal.remark,
            "signal_text": signal_text,
            "granularity": granularity,
            "status": "preview_pending",
            "chart_status": chart_status,
            "chart_error": chart_error,
        }
        self.created.append(record)
        self.records[public_id] = record
        return record

    async def update_status(self, record_id, status):
        self.status_updates.append((record_id, status))
        return True


def make_signal():
    return SignalDraft(
        symbol="BTCUSDT",
        direction="long",
        entry_lower=100,
        entry_upper=102,
        stop_loss=95,
        take_profit_levels=[108, 110],
        remark="wait",
    )


@pytest.mark.asyncio
async def test_create_signal_record_retries_public_id_collision():
    repo = FakeSignalRecordRepo()
    repo.records["dup0001"] = {"public_id": "dup0001"}
    generated_ids = iter(["dup0001", "ok00002"])
    service = SignalRecordService(repo, public_id_generator=lambda: next(generated_ids))
    user = SimpleNamespace(id=7, telegram_id=123)

    record, signal_text = await service.create_signal_record(
        user=user,
        signal=make_signal(),
        sender_username="admin",
        chart_status="generated",
        chart_error=None,
    )

    assert record["public_id"] == "ok00002"
    assert record["sender_telegram_id"] == 123
    assert "交易id: <code>ok00002</code>" in signal_text


@pytest.mark.asyncio
async def test_create_signal_record_raises_after_repeated_collisions():
    repo = FakeSignalRecordRepo()
    repo.records["dup0001"] = {"public_id": "dup0001"}
    service = SignalRecordService(repo, public_id_generator=lambda: "dup0001")

    with pytest.raises(RuntimeError):
        await service.create_signal_record(
            user=SimpleNamespace(id=7, telegram_id=123),
            signal=make_signal(),
            sender_username="admin",
            chart_status="generated",
            chart_error=None,
        )


@pytest.mark.asyncio
async def test_update_send_status_maps_sent_count_to_record_status():
    repo = FakeSignalRecordRepo()
    service = SignalRecordService(repo)

    await service.update_send_status(1, 2)
    await service.update_send_status(2, 0)

    assert repo.status_updates == [(1, "sent"), (2, "send_failed")]


def test_can_update_signal_record_allows_owner_or_admin_only():
    record = {"sender_telegram_id": 123}
    service = SignalRecordService(FakeSignalRecordRepo(), is_admin_checker=lambda telegram_id: telegram_id == 999)

    assert service.can_update_signal_record(SimpleNamespace(telegram_id=123), record) is True
    assert service.can_update_signal_record(SimpleNamespace(telegram_id=999), record) is True
    assert service.can_update_signal_record(SimpleNamespace(telegram_id=456), record) is False


def test_signal_record_to_draft_restores_signal_payload():
    service = SignalRecordService(FakeSignalRecordRepo())
    record = {
        "symbol": "ETHUSDT",
        "direction": "short",
        "entry_lower": 3000,
        "entry_upper": 3050,
        "stop_loss": 3100,
        "take_profit_levels": [2900, 2800],
        "remark": "pullback",
    }

    signal = service.signal_record_to_draft(record)

    assert signal == SignalDraft("ETHUSDT", "short", 3000, 3050, 3100, [2900, 2800], "pullback")
