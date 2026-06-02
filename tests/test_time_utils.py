from datetime import UTC, datetime

from app.time_utils import utc_now_naive


def test_utc_now_naive_returns_naive_utc_datetime():
    before = datetime.now(UTC).replace(tzinfo=None)
    result = utc_now_naive()
    after = datetime.now(UTC).replace(tzinfo=None)

    assert result.tzinfo is None
    assert before <= result <= after
