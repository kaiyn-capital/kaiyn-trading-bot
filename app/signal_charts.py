from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402

from .market_types import MarketCandle  # noqa: E402
from .order_types import SignalDraft  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FLOATING_PNL_ALPHA = 0.42
FLOATING_LONG_PROFIT_COLOR = "#0f766e"
FLOATING_SHORT_PROFIT_COLOR = "#991b1b"
FLOATING_LOSS_COLOR = "#4b3036"


@dataclass(frozen=True)
class SignalChartLevels:
    entry: float
    stop_loss: float
    target: float
    other_targets: tuple[float, ...]


@dataclass(frozen=True)
class FloatingPnlOverlay:
    lower: float
    upper: float
    color: str
    alpha: float
    state: str


def select_signal_chart_levels(signal: SignalDraft) -> SignalChartLevels:
    if not signal.take_profit_levels:
        raise ValueError("signal must have at least one take-profit level")

    if signal.direction == "long":
        entry = signal.entry_upper
        target = max(signal.take_profit_levels)
        if not target > entry > signal.stop_loss:
            raise ValueError("invalid long signal chart geometry")
    elif signal.direction == "short":
        entry = signal.entry_lower
        target = min(signal.take_profit_levels)
        if not target < entry < signal.stop_loss:
            raise ValueError("invalid short signal chart geometry")
    else:
        raise ValueError("invalid signal direction")

    other_targets = tuple(tp for tp in signal.take_profit_levels if tp != target)
    return SignalChartLevels(
        entry=float(entry),
        stop_loss=float(signal.stop_loss),
        target=float(target),
        other_targets=tuple(float(tp) for tp in other_targets),
    )


def render_signal_chart(signal: SignalDraft, candles: list[MarketCandle], granularity: str) -> bytes:
    return _render_signal_chart(signal, candles, granularity, signal_time=None, show_current_overlay=False)


def render_signal_update_chart(
    signal: SignalDraft,
    candles: list[MarketCandle],
    granularity: str,
    signal_time: datetime,
) -> bytes:
    return _render_signal_chart(signal, candles, granularity, signal_time=signal_time, show_current_overlay=True)


def _render_signal_chart(
    signal: SignalDraft,
    candles: list[MarketCandle],
    granularity: str,
    signal_time: datetime | None,
    show_current_overlay: bool,
) -> bytes:
    if len(candles) < 2:
        raise ValueError("not enough candles to render chart")

    levels = select_signal_chart_levels(signal)
    data = _candles_to_dataframe(candles)
    if data.empty:
        raise ValueError("no candles to render chart")

    market_colors = mpf.make_marketcolors(
        up="#f8fafc",
        down="#8b949e",
        edge="inherit",
        wick="inherit",
        volume="inherit",
    )
    style = mpf.make_mpf_style(
        marketcolors=market_colors,
        facecolor="#000000",
        figcolor="#000000",
        edgecolor="#1f2937",
        gridcolor="#000000",
        gridstyle="",
        y_on_right=True,
        rc={
            "axes.grid": False,
            "axes.labelcolor": "#9ca3af",
            "axes.titlecolor": "#d1d5db",
            "font.size": 10,
            "xtick.color": "#9ca3af",
            "ytick.color": "#9ca3af",
        },
    )

    fig = None
    try:
        fig, axes = mpf.plot(
            data,
            type="candle",
            style=style,
            volume=False,
            figsize=(12, 7),
            returnfig=True,
            tight_layout=True,
            warn_too_much_data=10000,
        )
        ax = axes[0]
        _style_axes(ax)
        _draw_signal_overlay(
            ax,
            data,
            signal,
            levels,
            signal_time=signal_time,
            show_current_overlay=show_current_overlay,
        )
        _draw_header(ax, signal, granularity)
        _format_time_axis(ax, data)

        image = BytesIO()
        fig.subplots_adjust(left=0.04, right=0.92, top=0.97, bottom=0.07)
        fig.savefig(image, format="png", dpi=130, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.04)
        return image.getvalue()
    finally:
        if fig is not None:
            plt.close(fig)


def _candles_to_dataframe(candles: list[MarketCandle]) -> pd.DataFrame:
    rows = [
        {
            "Date": candle.timestamp,
            "Open": candle.open,
            "High": candle.high,
            "Low": candle.low,
            "Close": candle.close,
            "Volume": candle.volume,
        }
        for candle in candles
    ]
    dataframe = pd.DataFrame(rows)
    dataframe = dataframe.sort_values("Date").drop_duplicates(subset="Date", keep="last")
    return dataframe.set_index("Date")


def _style_axes(ax) -> None:
    ax.set_facecolor("#000000")
    ax.grid(False)
    ax.set_xlabel("")
    ax.set_ylabel("")
    for spine in ax.spines.values():
        spine.set_color("#1f2937")
        spine.set_linewidth(0.8)


def _format_time_axis(ax, data: pd.DataFrame) -> None:
    candle_count = len(data.index)
    if candle_count <= 1:
        ax.set_xticks([])
        return

    max_labels = min(4, candle_count)
    tick_positions = sorted({round(index * (candle_count - 1) / (max_labels - 1)) for index in range(max_labels)})
    tick_labels = [_format_time_label(data.index[position]) for position in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels)
    ax.tick_params(axis="x", labelrotation=0, labelsize=8, colors="#8b949e", length=0, pad=4)


def _format_time_label(timestamp) -> str:
    return f"{timestamp.strftime('%b')} {timestamp.day}"


def _draw_header(ax, signal: SignalDraft, granularity: str) -> None:
    ax.text(
        0.012,
        0.985,
        f"{signal.symbol} · {granularity} · Bitget",
        color="#d1d5db",
        fontsize=11,
        fontweight="bold",
        ha="left",
        va="top",
        transform=ax.transAxes,
    )


def _draw_signal_overlay(
    ax,
    data: pd.DataFrame,
    signal: SignalDraft,
    levels: SignalChartLevels,
    signal_time: datetime | None = None,
    show_current_overlay: bool = False,
) -> None:
    candle_count = len(data.index)
    visible_extra = max(10, int(candle_count * 0.08 if signal_time is not None else candle_count * 0.18))
    x_start = _find_signal_anchor_index(data, signal_time) if signal_time is not None else candle_count - 1
    x_end = candle_count + visible_extra * 0.72

    x_left, _ = ax.get_xlim()
    ax.set_xlim(x_left, candle_count + visible_extra)
    _set_price_limits(ax, data, levels)

    is_long = signal.direction == "long"
    reward_color = "#064e3b" if is_long else "#7f1d1d"
    reward_edge = "#99f6e4" if is_long else "#fecaca"
    risk_color = "#2f3339"
    line_color = "#e5e7eb"

    ax.fill_between([x_start, x_end], levels.entry, levels.target, color=reward_color, alpha=0.72, linewidth=0)
    ax.fill_between([x_start, x_end], levels.stop_loss, levels.entry, color=risk_color, alpha=0.78, linewidth=0)

    if show_current_overlay:
        current_price = float(data["Close"].iloc[-1])
        overlay = select_floating_pnl_overlay(signal, levels, current_price)
        if overlay:
            ax.fill_between(
                [x_start, x_end],
                overlay.lower,
                overlay.upper,
                color=overlay.color,
                alpha=overlay.alpha,
                linewidth=0,
            )

    ax.hlines(levels.target, x_start, x_end, colors=reward_edge, linewidth=1.15)
    ax.hlines(levels.entry, x_start, x_end, colors=line_color, linewidth=1.1)
    ax.hlines(levels.stop_loss, x_start, x_end, colors=line_color, linewidth=1.1)

    for target in levels.other_targets:
        ax.hlines(target, x_start, x_end, colors=reward_edge, linewidth=0.8, linestyles="dashed", alpha=0.75)
        _draw_level_text(ax, x_end, target, "tp", va="center")

    _draw_level_text(ax, x_end, levels.target, "tp", va="bottom" if is_long else "top")
    _draw_level_text(ax, x_end, levels.entry, "entry", va="top" if is_long else "bottom")
    _draw_level_text(ax, x_end, levels.stop_loss, "sl", va="top" if is_long else "bottom")
    _draw_price_tag(ax, levels.target, reward_edge)
    _draw_price_tag(ax, levels.entry, line_color)
    _draw_price_tag(ax, levels.stop_loss, line_color)


def select_floating_pnl_overlay(
    signal: SignalDraft,
    levels: SignalChartLevels,
    current_price: float,
) -> FloatingPnlOverlay | None:
    tolerance = max(abs(levels.entry) * 1e-9, 1e-12)
    if abs(current_price - levels.entry) <= tolerance:
        return None

    if signal.direction == "long":
        if current_price > levels.entry:
            lower = levels.entry
            upper = min(current_price, levels.target)
            color = FLOATING_LONG_PROFIT_COLOR
            state = "profit"
        else:
            lower = max(current_price, levels.stop_loss)
            upper = levels.entry
            color = FLOATING_LOSS_COLOR
            state = "loss"
    elif signal.direction == "short":
        if current_price < levels.entry:
            lower = max(current_price, levels.target)
            upper = levels.entry
            color = FLOATING_SHORT_PROFIT_COLOR
            state = "profit"
        else:
            lower = levels.entry
            upper = min(current_price, levels.stop_loss)
            color = FLOATING_LOSS_COLOR
            state = "loss"
    else:
        return None

    if upper <= lower:
        return None

    return FloatingPnlOverlay(
        lower=lower,
        upper=upper,
        color=color,
        alpha=FLOATING_PNL_ALPHA,
        state=state,
    )


def _find_signal_anchor_index(data: pd.DataFrame, signal_time: datetime | None) -> int:
    if signal_time is None:
        return len(data.index) - 1

    normalized_time = _ensure_aware_utc(signal_time)
    timestamps = [_ensure_aware_utc(timestamp.to_pydatetime()) for timestamp in data.index]
    anchor_index = None
    for index, timestamp in enumerate(timestamps):
        if timestamp <= normalized_time:
            anchor_index = index
        else:
            break

    if anchor_index is None:
        raise ValueError("candles do not cover signal time")

    return anchor_index


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _set_price_limits(ax, data: pd.DataFrame, levels: SignalChartLevels) -> None:
    prices = [
        float(data["Low"].min()),
        float(data["High"].max()),
        levels.entry,
        levels.stop_loss,
        levels.target,
        *levels.other_targets,
    ]
    price_min = min(prices)
    price_max = max(prices)
    padding = max((price_max - price_min) * 0.08, abs(levels.entry) * 0.002, 1e-8)
    ax.set_ylim(price_min - padding, price_max + padding)


def _draw_level_text(ax, x: float, y: float, label: str, va: str) -> None:
    ax.text(
        x - 0.45,
        y,
        label,
        color="#f8fafc",
        fontsize=10,
        fontweight="bold",
        ha="right",
        va=va,
    )


def _draw_price_tag(ax, price: float, color: str) -> None:
    ax.annotate(
        _format_price(price),
        xy=(1, price),
        xycoords=("axes fraction", "data"),
        xytext=(8, 0),
        textcoords="offset points",
        color="#111827",
        fontsize=8,
        ha="left",
        va="center",
        bbox={
            "boxstyle": "round,pad=0.18",
            "facecolor": "#f8fafc",
            "edgecolor": color,
            "linewidth": 0.8,
        },
        clip_on=False,
    )


def _format_price(price: float) -> str:
    return f"{price:,.8f}".rstrip("0").rstrip(".")
