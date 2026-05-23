from datetime import UTC, datetime, timedelta

import pytest

from app.market_types import MarketCandle
from app.order_types import SignalDraft
from app.signal_charts import (
    PNG_SIGNATURE,
    _format_time_label,
    render_signal_chart,
    render_signal_update_chart,
    select_floating_pnl_overlay,
    select_signal_chart_levels,
)


def make_candles(count=30):
    start = datetime(2026, 5, 18, tzinfo=UTC)
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


def test_render_signal_update_chart_returns_png_bytes():
    signal = SignalDraft("BTCUSDT", "long", 100, 102, 95, [108, 110])
    candles = make_candles(40)

    image = render_signal_update_chart(signal, candles, "1H", candles[20].timestamp)

    assert image.startswith(PNG_SIGNATURE)
    assert len(image) > 1000


@pytest.mark.parametrize(
    ("signal", "current_price", "expected_lower", "expected_upper", "expected_state"),
    [
        (SignalDraft("BTCUSDT", "long", 100, 102, 95, [110]), 106, 102, 106, "profit"),
        (SignalDraft("BTCUSDT", "long", 100, 102, 95, [110]), 99, 99, 102, "loss"),
        (SignalDraft("BTCUSDT", "short", 100, 102, 106, [90]), 95, 95, 100, "profit"),
        (SignalDraft("BTCUSDT", "short", 100, 102, 106, [90]), 103, 100, 103, "loss"),
    ],
)
def test_select_floating_pnl_overlay_for_update_chart(
    signal,
    current_price,
    expected_lower,
    expected_upper,
    expected_state,
):
    levels = select_signal_chart_levels(signal)

    overlay = select_floating_pnl_overlay(signal, levels, current_price)

    assert overlay is not None
    assert overlay.lower == expected_lower
    assert overlay.upper == expected_upper
    assert overlay.state == expected_state


@pytest.mark.parametrize(
    ("signal", "current_price", "expected_lower", "expected_upper"),
    [
        (SignalDraft("BTCUSDT", "long", 100, 102, 95, [110]), 120, 102, 110),
        (SignalDraft("BTCUSDT", "long", 100, 102, 95, [110]), 90, 95, 102),
        (SignalDraft("BTCUSDT", "short", 100, 102, 106, [90]), 80, 90, 100),
        (SignalDraft("BTCUSDT", "short", 100, 102, 106, [90]), 120, 100, 106),
    ],
)
def test_select_floating_pnl_overlay_clamps_to_risk_reward_box(
    signal,
    current_price,
    expected_lower,
    expected_upper,
):
    levels = select_signal_chart_levels(signal)

    overlay = select_floating_pnl_overlay(signal, levels, current_price)

    assert overlay is not None
    assert overlay.lower == expected_lower
    assert overlay.upper == expected_upper


def test_select_floating_pnl_overlay_skips_entry_price():
    signal = SignalDraft("BTCUSDT", "long", 100, 102, 95, [110])
    levels = select_signal_chart_levels(signal)

    assert select_floating_pnl_overlay(signal, levels, 102) is None


@pytest.mark.parametrize(
    ("signal", "latest_close"),
    [
        (SignalDraft("BTCUSDT", "long", 100, 102, 95, [108, 110]), 106),
        (SignalDraft("BTCUSDT", "long", 100, 102, 95, [108, 110]), 99),
        (SignalDraft("BTCUSDT", "short", 100, 102, 106, [95, 90]), 95),
        (SignalDraft("BTCUSDT", "short", 100, 102, 106, [95, 90]), 103),
    ],
)
def test_render_signal_update_chart_handles_profit_and_loss_overlays(signal, latest_close):
    candles = make_candles(40)
    last = candles[-1]
    candles[-1] = MarketCandle(
        timestamp=last.timestamp,
        open=last.open,
        high=max(last.high, latest_close),
        low=min(last.low, latest_close),
        close=latest_close,
        volume=last.volume,
    )

    image = render_signal_update_chart(signal, candles, "1H", candles[20].timestamp)

    assert image.startswith(PNG_SIGNATURE)
    assert len(image) > 1000


def test_render_signal_update_chart_rejects_missing_signal_time():
    signal = SignalDraft("BTCUSDT", "long", 100, 102, 95, [108, 110])
    candles = make_candles(40)

    with pytest.raises(ValueError):
        render_signal_update_chart(signal, candles, "1H", candles[0].timestamp - timedelta(hours=2))


def test_format_time_label_uses_compact_day_label():
    assert _format_time_label(datetime(2026, 5, 19, 21, 30, tzinfo=UTC)) == "May 19"
