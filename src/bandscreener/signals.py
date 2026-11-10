"""Signal logic: quarterly Bollinger Bands and distance of recent extremes to a band.

This module is pure (no network, no files) so it can be tested on its own.

Definitions
-----------
* Quarterly bars: the last daily Close of each calendar quarter.
* Bands: simple average of the last ``bb_period`` quarterly closes, plus/minus
  ``bb_std`` population standard deviations (the standard Bollinger convention).
* "live" mode: the unfinished current quarter counts as the latest bar, so the
  band matches what a chart shows today. "frozen" mode drops it.

Buy side (``evaluate``)
  Gap = (lowest daily Low in the window - lower band) / lower band.
  Negative means the low broke below the band. A stock passes when gap <= threshold.

Sell side (``evaluate_upper``)
  Gap = (highest daily High in the window - upper band) / upper band.
  Positive means the high went above the band. A stock passes when gap >= -threshold.

In both cases the window is the last N trading days ("week") or the quarter so far,
and the extreme is an intraday low/high, not a close, so a touch followed by a
reversal still counts.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SignalParams:
    bb_period: int = 20
    bb_std: float = 2.0
    threshold: float = 0.10
    week_days: int = 5
    band_mode: str = "live"  # "live" or "frozen"


def quarterly_closes(daily: pd.DataFrame, as_of: pd.Timestamp, include_current: bool) -> pd.Series:
    """Last Close of each calendar quarter, indexed by quarter (PeriodIndex)."""
    close = daily["Close"].dropna()
    quarterly = close.groupby(close.index.to_period("Q")).last()
    if not include_current:
        quarterly = quarterly[quarterly.index < as_of.to_period("Q")]
    return quarterly


def bollinger(quarterly: pd.Series, period: int, k: float) -> tuple[float, float, float] | None:
    """(lower, middle, upper) from the last ``period`` quarterly closes, or None if too few."""
    if len(quarterly) < period:
        return None
    window = quarterly.iloc[-period:]
    mid = float(window.mean())
    sd = float(window.std(ddof=0))
    return mid - k * sd, mid, mid + k * sd


def _prepare(
    daily: pd.DataFrame | None,
    params: SignalParams,
    as_of: pd.Timestamp,
    latest_market_date: pd.Timestamp,
    liq_window: int,
    stale_days: int,
) -> tuple[dict, dict | None]:
    """Steps shared by both sides. Returns (result so far, context) - context is None if we must stop."""
    if daily is None or len(daily) == 0:
        return {"status": "no_data"}, None

    daily = daily[~daily.index.duplicated(keep="last")].sort_index()
    daily = daily.dropna(subset=["Close"])
    if daily.empty:
        return {"status": "no_data"}, None

    last_date = daily.index[-1]
    out: dict = {"last_date": last_date.strftime("%Y-%m-%d")}

    if (latest_market_date - last_date).days > stale_days:
        out["status"] = "stale"
        return out, None

    quarterly = quarterly_closes(daily, as_of, include_current=(params.band_mode == "live"))
    out["bars"] = int(len(quarterly))
    bands = bollinger(quarterly, params.bb_period, params.bb_std)
    if bands is None:
        out["status"] = "insufficient_history"
        return out, None

    lower, mid, upper = bands
    close = float(daily["Close"].iloc[-1])
    out.update(
        close=close,
        lower=lower,
        mid=mid,
        upper=upper,
        bandwidth=((upper - lower) / mid) if mid > 0 else None,
        adv=_avg_daily_value(daily, liq_window),
    )
    return out, {"daily": daily, "lower": lower, "mid": mid, "upper": upper, "close": close}


def evaluate(
    daily: pd.DataFrame | None,
    params: SignalParams,
    as_of: pd.Timestamp,
    latest_market_date: pd.Timestamp,
    liq_window: int = 60,
    stale_days: int = 7,
) -> dict:
    """Buy side: how close did the lowest price get to the lower band?

    ``daily`` needs a DatetimeIndex (tz-naive) and columns Close, Low and optionally Volume.
    Returns a dict with a ``status``:
      ok, negative_band, insufficient_history, stale, no_data.
    """
    out, ctx = _prepare(daily, params, as_of, latest_market_date, liq_window, stale_days)
    if ctx is None:
        return out

    daily, lower, close = ctx["daily"], ctx["lower"], ctx["close"]
    low_series = daily["Low"].fillna(daily["Close"]) if "Low" in daily else daily["Close"]

    week = low_series.tail(params.week_days)
    week_low = float(week.min())
    quarter_rows = low_series[low_series.index >= as_of.to_period("Q").start_time]
    qtd_low = float(quarter_rows.min()) if len(quarter_rows) else None

    out.update(
        week_low=week_low,
        week_low_date=week.idxmin().strftime("%Y-%m-%d"),
        qtd_low=qtd_low,
        qtd_low_date=quarter_rows.idxmin().strftime("%Y-%m-%d") if qtd_low is not None else None,
    )

    if lower <= 0:
        # A band at or below zero makes "distance to the band" meaningless: everything passes.
        out["status"] = "negative_band"
        return out

    thr = params.threshold
    week_gap = week_low / lower - 1
    qtd_gap = (qtd_low / lower - 1) if qtd_low is not None else None
    close_gap = close / lower - 1

    out.update(
        status="ok",
        week_dist=week_gap,
        qtd_dist=qtd_gap,
        close_dist=close_gap,
        pct_b=_pct_b(close, lower, ctx["upper"]),
        week_hit=week_gap <= thr,
        qtd_hit=(qtd_gap is not None and qtd_gap <= thr),
        week_rallied=(week_gap <= thr < close_gap),
        qtd_rallied=(qtd_gap is not None and qtd_gap <= thr < close_gap),
    )
    return out


def evaluate_upper(
    daily: pd.DataFrame | None,
    params: SignalParams,
    as_of: pd.Timestamp,
    latest_market_date: pd.Timestamp,
    liq_window: int = 60,
    stale_days: int = 7,
) -> dict:
    """Sell side: how close did the highest price get to the upper band?

    Same statuses as ``evaluate`` except there is no negative-band case (the upper band is
    always above the average). Gap is positive when the high went above the band.
    """
    out, ctx = _prepare(daily, params, as_of, latest_market_date, liq_window, stale_days)
    if ctx is None:
        return out

    daily, upper, close = ctx["daily"], ctx["upper"], ctx["close"]
    high_series = daily["High"].fillna(daily["Close"]) if "High" in daily else daily["Close"]

    week = high_series.tail(params.week_days)
    week_high = float(week.max())
    quarter_rows = high_series[high_series.index >= as_of.to_period("Q").start_time]
    qtd_high = float(quarter_rows.max()) if len(quarter_rows) else None

    out.update(
        week_high=week_high,
        week_high_date=week.idxmax().strftime("%Y-%m-%d"),
        qtd_high=qtd_high,
        qtd_high_date=quarter_rows.idxmax().strftime("%Y-%m-%d") if qtd_high is not None else None,
    )

    if upper <= 0:  # cannot happen with real prices; guard against bad data
        out["status"] = "negative_band"
        return out

    thr = params.threshold
    week_gap = week_high / upper - 1
    qtd_gap = (qtd_high / upper - 1) if qtd_high is not None else None
    close_gap = close / upper - 1

    out.update(
        status="ok",
        week_dist=week_gap,
        qtd_dist=qtd_gap,
        close_dist=close_gap,
        pct_b=_pct_b(close, ctx["lower"], upper),
        week_hit=week_gap >= -thr,
        qtd_hit=(qtd_gap is not None and qtd_gap >= -thr),
        # touched the zone, but the close has since fallen back out of it
        week_pullback=(week_gap >= -thr and close_gap < -thr),
        qtd_pullback=(qtd_gap is not None and qtd_gap >= -thr and close_gap < -thr),
    )
    return out


def _pct_b(close: float, lower: float, upper: float) -> float | None:
    return ((close - lower) / (upper - lower)) if upper > lower else None


def _avg_daily_value(daily: pd.DataFrame, window: int) -> float | None:
    """Average of Close x Volume over the last ``window`` sessions, in local currency."""
    if "Volume" not in daily:
        return None
    traded = (daily["Close"] * daily["Volume"]).tail(window).dropna()
    if traded.empty:
        return None
    return float(traded.mean())
