"""Signal logic: quarterly Bollinger Bands and distance of recent lows to the lower band.

This module is pure (no network, no files) so it can be tested on its own.

Definitions
-----------
* Quarterly bars: the last daily Close of each calendar quarter.
* Bands: simple average of the last ``bb_period`` quarterly closes, plus/minus
  ``bb_std`` population standard deviations (the standard Bollinger convention).
* "live" mode: the unfinished current quarter counts as the latest bar, so the
  band matches what a chart shows today. "frozen" mode drops it.
* Gap: (low - lower_band) / lower_band. Negative means the low broke below the band.
  The low is the lowest daily Low in the window (last N trading days, or
  quarter-to-date), not the closing price, so a touch followed by a rally still counts.
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


def evaluate(
    daily: pd.DataFrame | None,
    params: SignalParams,
    as_of: pd.Timestamp,
    latest_market_date: pd.Timestamp,
    liq_window: int = 60,
    stale_days: int = 7,
) -> dict:
    """Evaluate one stock.

    ``daily`` needs a DatetimeIndex (tz-naive) and columns Close, Low and optionally Volume.
    Returns a dict with a ``status``:
      ok, negative_band, insufficient_history, stale, no_data.
    """
    if daily is None or len(daily) == 0:
        return {"status": "no_data"}

    daily = daily[~daily.index.duplicated(keep="last")].sort_index()
    daily = daily.dropna(subset=["Close"])
    if daily.empty:
        return {"status": "no_data"}

    last_date = daily.index[-1]
    out: dict = {"last_date": last_date.strftime("%Y-%m-%d")}

    if (latest_market_date - last_date).days > stale_days:
        out["status"] = "stale"
        return out

    quarterly = quarterly_closes(daily, as_of, include_current=(params.band_mode == "live"))
    out["bars"] = int(len(quarterly))
    bands = bollinger(quarterly, params.bb_period, params.bb_std)
    if bands is None:
        out["status"] = "insufficient_history"
        return out

    lower, mid, upper = bands
    close = float(daily["Close"].iloc[-1])
    low_series = daily["Low"].fillna(daily["Close"]) if "Low" in daily else daily["Close"]

    week = low_series.tail(params.week_days)
    week_low = float(week.min())
    quarter_rows = low_series[low_series.index >= as_of.to_period("Q").start_time]
    qtd_low = float(quarter_rows.min()) if len(quarter_rows) else None

    out.update(
        close=close,
        lower=lower,
        mid=mid,
        upper=upper,
        bandwidth=((upper - lower) / mid) if mid > 0 else None,
        week_low=week_low,
        week_low_date=week.idxmin().strftime("%Y-%m-%d"),
        qtd_low=qtd_low,
        qtd_low_date=quarter_rows.idxmin().strftime("%Y-%m-%d") if qtd_low is not None else None,
        adv=_avg_daily_value(daily, liq_window),
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
        pct_b=((close - lower) / (upper - lower)) if upper > lower else None,
        week_hit=week_gap <= thr,
        qtd_hit=(qtd_gap is not None and qtd_gap <= thr),
        week_rallied=(week_gap <= thr < close_gap),
        qtd_rallied=(qtd_gap is not None and qtd_gap <= thr < close_gap),
    )
    return out


def _avg_daily_value(daily: pd.DataFrame, window: int) -> float | None:
    """Average of Close x Volume over the last ``window`` sessions, in local currency."""
    if "Volume" not in daily:
        return None
    traded = (daily["Close"] * daily["Volume"]).tail(window).dropna()
    if traded.empty:
        return None
    return float(traded.mean())
