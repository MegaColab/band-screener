"""Builders for synthetic price histories with exactly known quarterly closes."""

from __future__ import annotations

import numpy as np
import pandas as pd

AS_OF = pd.Timestamp("2026-11-13")  # a Friday inside Q4 2026

# 19 completed quarters: 2022Q1 .. 2026Q3. With the current quarter (2026Q4) that makes 20 bars.
PRIOR_QUARTERS = pd.period_range("2022Q1", "2026Q3", freq="Q")


def band_for(prior_closes: list[float], final_close: float, k: float = 2.0):
    """Independent calculation of (lower, mid, upper) for the live band."""
    window = np.array(list(prior_closes) + [final_close], dtype=float)[-20:]
    mid = window.mean()
    sd = window.std()  # numpy default is the population standard deviation
    return mid - k * sd, mid, mid + k * sd


def make_daily(
    prior_closes: list[float],
    final_close: float,
    overrides: dict[str, dict] | None = None,
    low_factor: float = 0.995,
    volume: float = 1_000_000,
    start: str = "2022-01-03",
    end: pd.Timestamp = AS_OF,
) -> pd.DataFrame:
    """Daily bars where every day in a quarter closes at that quarter's value.

    So the quarterly closes are exactly ``prior_closes`` plus ``final_close`` for the current
    quarter. ``overrides`` maps a date string to {"Low": x, "Close": y} for specific days.
    """
    idx = pd.bdate_range(start=start, end=end)
    quarter_of = idx.to_period("Q")
    value_by_quarter = dict(zip(PRIOR_QUARTERS, prior_closes))
    current = AS_OF.to_period("Q")
    close = np.array([value_by_quarter.get(q, final_close) if q != current else final_close for q in quarter_of], dtype=float)
    df = pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * low_factor, "Close": close, "Volume": volume},
        index=idx,
    )
    for date, vals in (overrides or {}).items():
        for col, val in vals.items():
            df.loc[pd.Timestamp(date), col] = val
    df = df[df.index >= pd.Timestamp(start)]
    return df


def rising_closes() -> list[float]:
    """19 steadily rising quarterly closes (60 .. 114)."""
    return [60.0 + 3.0 * i for i in range(19)]
