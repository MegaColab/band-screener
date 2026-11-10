"""Synthetic stocks and prices for the --demo mode and for tests. Not real data."""

from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

DEMO_END = pd.Timestamp("2026-11-13")


def demo_universe(n_us: int = 60, n_asx: int = 40) -> list[dict]:
    rows = []
    for i in range(1, n_us + 1):
        t = f"USDEMO{i:02d}"
        rows.append(
            {"ticker": t, "yahoo": t, "name": f"Demo US Company {i:02d}", "market": "US",
             "currency": "USD", "sector": "Demo"}
        )
    for i in range(1, n_asx + 1):
        t = f"AUDEMO{i:02d}"
        rows.append(
            {"ticker": t, "yahoo": f"{t}.AX", "name": f"Demo ASX Company {i:02d}", "market": "ASX",
             "currency": "AUD", "sector": ""}
        )
    return rows


def demo_holdings(n_us: int = 10, n_asx: int = 6) -> list[dict]:
    """A small made-up holdings list for the Sell tab demo."""
    return demo_universe(n_us, n_asx)


def synthetic_prices(symbols: list[str], end: pd.Timestamp = DEMO_END, years: int = 6) -> dict[str, pd.DataFrame]:
    """Random-walk OHLCV. Some symbols fall hard near the end so the demo has matches."""
    idx = pd.bdate_range(end=end, periods=int(years * 252))
    prices: dict[str, pd.DataFrame] = {}
    for n, sym in enumerate(symbols):
        rng = np.random.default_rng(zlib.crc32(sym.encode()))
        vol = rng.uniform(0.010, 0.028)
        rets = rng.normal(rng.uniform(-0.0001, 0.0006), vol, len(idx))
        mood = rng.random()
        if mood < 0.35:  # a sell-off over the last ~3 months
            rets[-60:] += rng.uniform(-0.012, -0.004)
        elif mood < 0.65:  # a rally over the last ~3 months
            rets[-60:] += rng.uniform(0.004, 0.012)
        close = rng.uniform(5, 250) * np.exp(np.cumsum(rets))
        low = close * (1 - np.abs(rng.normal(0, 0.009, len(idx))))
        high = close * (1 + np.abs(rng.normal(0, 0.009, len(idx))))
        volume = rng.lognormal(mean=13.0, sigma=1.2, size=len(idx)).astype(float)
        df = pd.DataFrame(
            {"Open": close, "High": high, "Low": np.minimum(low, close), "Close": close, "Volume": volume},
            index=idx,
        )
        if n % 23 == 5:        # a recent listing: only two years of history
            df = df.iloc[-504:]
        elif n % 41 == 7:      # delisted/halted: data stops a month early
            df = df[df.index <= end - pd.Timedelta(days=30)]
        elif n % 37 == 3:      # nothing from the data source
            continue
        prices[sym] = df
    return prices
