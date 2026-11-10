"""Glue: run the signal over the whole universe and build the dashboard payload."""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

from .config import Config
from .signals import evaluate

ROUND_DIGITS = 5


def _clean(value):
    """JSON-safe: NaN/inf become None, floats are rounded."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, ROUND_DIGITS)
    return value


def build_payload(
    cfg: Config,
    universe: list[dict],
    prices: dict[str, pd.DataFrame],
    warnings: list[str],
    asx_meta: dict | None = None,
    generated_at: datetime | None = None,
) -> dict:
    if not prices:
        raise RuntimeError("No price data was loaded.")

    latest = max(df.index[-1] for df in prices.values())
    as_of = latest  # the quarter that contains the latest trading day is the "current" quarter
    generated_at = generated_at or datetime.now(timezone.utc)

    rows = []
    for stock in universe:
        result = evaluate(prices.get(stock["yahoo"]), cfg.signal, as_of, latest, cfg.liq_window)
        row = {k: stock[k] for k in ("ticker", "name", "market", "currency", "sector")}
        row.update(result)
        min_adv = cfg.liq_min_us if stock["currency"] == "USD" else cfg.liq_min_au
        adv = result.get("adv")
        row["low_liquidity"] = bool(adv is not None and adv < min_adv)
        rows.append(_clean(row))

    loaded = sum(1 for s in universe if s["yahoo"] in prices)
    sig = cfg.signal
    return {
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "as_of": latest.strftime("%Y-%m-%d"),
        "params": {
            "threshold": sig.threshold,
            "week_days": sig.week_days,
            "bb_period": sig.bb_period,
            "bb_std": sig.bb_std,
            "band_mode": sig.band_mode,
            "liq_window": cfg.liq_window,
            "liq_min_us": cfg.liq_min_us,
            "liq_min_au": cfg.liq_min_au,
        },
        "counts": {
            "universe": len(universe),
            "loaded": loaded,
            "by_status": dict(Counter(r["status"] for r in rows)),
            "by_market": dict(Counter(r["market"] for r in rows)),
        },
        "warnings": warnings,
        "asx_list": asx_meta or {},
        "rows": rows,
    }


def history_snapshot(payload: dict) -> dict:
    """Small hits-only record for the weekly history file (keeps the repo light)."""
    keep = ("ticker", "market", "week_low", "lower", "week_dist", "qtd_dist", "close_dist")
    hits = [
        {k: r.get(k) for k in keep}
        for r in payload["rows"]
        if r["status"] == "ok" and (r.get("week_hit") or r.get("qtd_hit"))
    ]
    return {
        "as_of": payload["as_of"],
        "generated_at": payload["generated_at"],
        "params": payload["params"],
        "hits": hits,
    }
