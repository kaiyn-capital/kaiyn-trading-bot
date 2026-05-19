from datetime import datetime, timedelta, timezone

import pytest

from app.market_types import MarketCandle
from app.order_types import SignalDraft
from app.signal_charts import PNG_SIGNATURE, _format_time_label, render_signal_chart, select_signal_chart_levels


def make_candles(count=30):
    start = datetime(2026, 5, 18, tzinfo=timezone.utc)
    candles = []
    for index in range(count):
        price = 100 + index * 0.4
        candles.append(
            MarketCandle(
                timestamp=start + timedelta(hours=index),
                open=price,
                high=price + 1.2,
                low=price - 1.1,
                close=price + 0.5,
                volume=10 + index,
            )
        )
    return candles


def test_select_signal_chart_levels_uses_long_worse_entry_and_farthest_tp():
    signal = SignalDraft(
        symbol="BTCUSDT",
        direction="long",
        entry_lower=100,
        entry_upper=102,
        stop_loss=95,
        take_profit_levels=[106, 110, 108],
    )

    levels = select_signal_chart_levels(signal)

    assert levels.entry == 102
    assert levels.target == 110
    assert levels.stop_loss == 95
    assert levels.other_targets == (106, 108)


def test_select_signal_chart_levels_uses_short_worse_entry_and_farthest_tp():
    signal = SignalDraft(
        symbol="BTCUSDT",
        direction="short",
        entry_lower=100,
        entry_upper=102,
        stop_loss=106,
        take_profit_levels=[95, 90, 93],
    )

    levels = select_signal_chart_levels(signal)

    assert levels.entry == 100
    assert levels.target == 90
    assert levels.stop_loss == 106
    assert levels.other_targets == (95, 93)


@pytest.mark.parametrize(
    "signal",
    [
        SignalDraft("BTCUSDT", "long", 100, 102, 103, [110]),
        SignalDraft("BTCUSDT", "short", 100, 102, 99, [90]),
        SignalDraft("BTCUSDT", "long", 100, 102, 95, [101]),
    ],
)
def test_select_signal_chart_levels_rejects_invalid_geometry(signal):
    with pytest.raises(ValueError):
        select_signal_chart_levels(signal)


@pytest.mark.parametrize(
    "signal",
    [
        SignalDraft("BTCUSDT", "long", 100, 102, 95, [108, 110]),
        SignalDraft("BTCUSDT", "short", 100, 102, 106, [95, 90]),
    ],
)
def test_render_signal_chart_returns_png_bytes(signal):
    image = render_signal_chart(signal, make_candles(), "1H")

    assert image.startswith(PNG_SIGNATURE)
    assert len(image) > 1000


def test_format_time_label_uses_compact_day_label():
    assert _format_time_label(datetime(2026, 5, 19, 21, 30, tzinfo=timezone.utc)) == "May 19"
