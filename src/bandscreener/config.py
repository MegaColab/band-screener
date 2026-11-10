"""Settings loaded from config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .signals import SignalParams


@dataclass(frozen=True)
class Config:
    root: Path
    signal: SignalParams
    sell_threshold: float
    liq_window: int
    liq_min_us: float
    liq_min_au: float
    history_years: int
    batch_size: int
    min_success_ratio: float
    asx200_file: Path
    asx200_max_age_days: int
    sp500_cache_file: Path
    holdings_file: Path
    out_dir: Path
    keep_history: bool
    etf_file: Path | None = None  # tickers listed here are tagged ETF (drives the ETF filter)


def load_config(path: str | Path = "config.toml") -> Config:
    path = Path(path).resolve()
    root = path.parent
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    sig = raw.get("signal", {})
    sell = raw.get("sell", {})
    liq = raw.get("liquidity", {})
    dat = raw.get("data", {})
    uni = raw.get("universe", {})
    out = raw.get("output", {})

    params = SignalParams(
        bb_period=int(sig.get("bb_period", 20)),
        bb_std=float(sig.get("bb_std", 2.0)),
        threshold=float(sig.get("proximity_threshold", 0.10)),
        week_days=int(sig.get("week_lookback_days", 5)),
        band_mode=str(sig.get("band_mode", "live")),
    )
    if params.band_mode not in ("live", "frozen"):
        raise ValueError("signal.band_mode must be 'live' or 'frozen'")
    if params.threshold <= 0:
        raise ValueError("signal.proximity_threshold must be greater than 0")
    if params.bb_period < 2 or params.week_days < 1:
        raise ValueError("bb_period must be >= 2 and week_lookback_days >= 1")

    sell_threshold = float(sell.get("proximity_threshold", params.threshold))
    if sell_threshold <= 0:
        raise ValueError("sell.proximity_threshold must be greater than 0")

    return Config(
        root=root,
        signal=params,
        sell_threshold=sell_threshold,
        liq_window=int(liq.get("window_days", 60)),
        liq_min_us=float(liq.get("min_avg_daily_value_us", 5_000_000)),
        liq_min_au=float(liq.get("min_avg_daily_value_au", 1_000_000)),
        history_years=int(dat.get("history_years", 6)),
        batch_size=int(dat.get("batch_size", 80)),
        min_success_ratio=float(dat.get("min_success_ratio", 0.80)),
        asx200_file=root / uni.get("asx200_file", "data/asx200.csv"),
        asx200_max_age_days=int(uni.get("asx200_max_age_days", 100)),
        sp500_cache_file=root / uni.get("sp500_cache_file", "data/sp500_cache.csv"),
        holdings_file=root / uni.get("holdings_file", "data/holdings.txt"),
        out_dir=root / out.get("dir", "docs"),
        keep_history=bool(out.get("keep_history", True)),
        etf_file=root / uni.get("etf_file", "data/etfs.txt"),
    )
