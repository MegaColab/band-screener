"""Price data from Yahoo Finance (via yfinance), downloaded in batches."""

from __future__ import annotations

import sys
import time

import pandas as pd

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _normalise(df: pd.DataFrame) -> pd.DataFrame | None:
    """Keep OHLCV, tz-naive dates, no empty rows. Returns None if nothing usable."""
    if df is None or df.empty:
        return None
    df = df[[c for c in COLUMNS if c in df.columns]].copy()
    if "Close" not in df:
        return None
    idx = pd.to_datetime(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df.dropna(subset=["Close"])
    return df if not df.empty else None


def _split_download(raw: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return frames
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(raw.columns.get_level_values(0))
        level1 = set(raw.columns.get_level_values(1))
        for sym in symbols:
            if sym in level0:
                part = raw[sym]
            elif sym in level1:
                part = raw.xs(sym, axis=1, level=1)
            else:
                continue
            clean = _normalise(part)
            if clean is not None:
                frames[sym] = clean
    elif len(symbols) == 1:
        clean = _normalise(raw)
        if clean is not None:
            frames[symbols[0]] = clean
    return frames


def _download(yf, symbols: list[str], start_date: str, retries: int) -> dict[str, pd.DataFrame]:
    for attempt in range(retries + 1):
        try:
            raw = yf.download(
                symbols,
                start=start_date,  # Yahoo only accepts fixed periods (5y, 10y...), so use a start date
                interval="1d",
                auto_adjust=False,  # Close is split-adjusted but not dividend-adjusted, like most charts
                group_by="ticker",
                threads=True,
                progress=False,
            )
            return _split_download(raw, symbols)
        except Exception as exc:  # noqa: BLE001
            print(f"  download error ({exc}); attempt {attempt + 1} of {retries + 1}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    return {}


def download_prices(
    symbols: list[str], years: int = 6, batch_size: int = 80, retries: int = 2, pause: float = 1.0
) -> dict[str, pd.DataFrame]:
    """Daily OHLCV per Yahoo symbol. Symbols with no usable data are left out."""
    import yfinance as yf

    start_date = (pd.Timestamp.today().normalize() - pd.DateOffset(years=years)).strftime("%Y-%m-%d")
    prices: dict[str, pd.DataFrame] = {}
    for first in range(0, len(symbols), batch_size):
        batch = symbols[first : first + batch_size]
        got = _download(yf, batch, start_date, retries)
        missing = [s for s in batch if s not in got]
        if missing:  # one more try for anything the batch dropped (rate limits are common)
            time.sleep(2)
            got.update(_download(yf, missing, start_date, retries=1))
        prices.update(got)
        print(f"  prices: {len(prices)} of {min(first + batch_size, len(symbols))} loaded", file=sys.stderr)
        time.sleep(pause)
    return prices
