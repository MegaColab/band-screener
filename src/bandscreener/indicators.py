"""Extra indicators that sit beside the Bollinger Bands. Pure functions: no network, no files.

RSI is measured on the same quarterly closes as the bands (including the unfinished quarter in
"live" mode), so it reads like the RSI under a quarterly chart.
"""

from __future__ import annotations

import pandas as pd

from .signals import quarterly_closes


def wilder_rsi(closes: pd.Series, period: int = 14) -> float | None:
    """Wilder's RSI of the last value in ``closes``, or None if there are too few bars.

    Needs ``period + 1`` closes. The first average gain and loss are simple averages of the first
    ``period`` changes, then Wilder smoothing is applied (the way charting packages do it).
    """
    values = [float(v) for v in closes.dropna()]
    if len(values) < period + 1:
        return None
    changes = [b - a for a, b in zip(values[:-1], values[1:])]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def quarterly_rsi(
    daily: pd.DataFrame | None,
    as_of: pd.Timestamp,
    include_current: bool = True,
    period: int = 14,
) -> float | None:
    """RSI of the quarterly closes built from a daily price table (same cleaning as the bands)."""
    if daily is None or len(daily) == 0:
        return None
    daily = daily[~daily.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])
    if daily.empty:
        return None
    return wilder_rsi(quarterly_closes(daily, as_of, include_current), period)
