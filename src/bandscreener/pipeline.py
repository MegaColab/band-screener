"""Glue: run the signal over a universe and build the dashboard payload.

``side`` is "lower" for the Buy tab (stocks near the lower band) and "upper" for the
Sell tab (holdings near the upper band).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd

from .config import Config
from .indicators import quarterly_rsi
from .signals import evaluate, evaluate_upper

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


def _params_block(cfg: Config, signal) -> dict:
    return {
        "threshold": signal.threshold,
        "week_days": signal.week_days,
        "bb_period": signal.bb_period,
        "bb_std": signal.bb_std,
        "band_mode": signal.band_mode,
        "liq_window": cfg.liq_window,
        "liq_min_us": cfg.liq_min_us,
        "liq_min_au": cfg.liq_min_au,
        "rsi_period": cfg.rsi_period,
        "rsi_oversold": cfg.rsi_oversold,
        "rsi_overbought": cfg.rsi_overbought,
    }


def _signal_for(cfg: Config, side: str):
    if side == "upper":
        return replace(cfg.signal, threshold=cfg.sell_threshold)
    return cfg.signal


def build_payload(
    cfg: Config,
    universe: list[dict],
    prices: dict[str, pd.DataFrame],
    warnings: list[str],
    asx_meta: dict | None = None,
    generated_at: datetime | None = None,
    side: str = "lower",
    etfs: set[tuple[str, str]] | None = None,
) -> dict:
    if not prices:
        raise RuntimeError("No price data was loaded.")

    signal = _signal_for(cfg, side)
    evaluator = evaluate_upper if side == "upper" else evaluate
    latest = max(df.index[-1] for df in prices.values())
    as_of = latest  # the quarter that contains the latest trading day is the "current" quarter
    generated_at = generated_at or datetime.now(timezone.utc)

    rows = []
    for stock in universe:
        result = evaluator(prices.get(stock["yahoo"]), signal, as_of, latest, cfg.liq_window)
        row = {k: stock[k] for k in ("ticker", "name", "market", "currency", "sector")}
        row.update(result)
        min_adv = cfg.liq_min_us if stock["currency"] == "USD" else cfg.liq_min_au
        adv = result.get("adv")
        row["low_liquidity"] = bool(adv is not None and adv < min_adv)
        row["is_etf"] = (stock["market"], stock["ticker"]) in (etfs or set())
        if result.get("status") == "ok":
            row["rsi"] = quarterly_rsi(
                prices.get(stock["yahoo"]), as_of, include_current=(signal.band_mode == "live"), period=cfg.rsi_period
            )
        rows.append(_clean(row))

    loaded = sum(1 for s in universe if s["yahoo"] in prices)
    return {
        "side": side,
        "empty": False,
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "as_of": latest.strftime("%Y-%m-%d"),
        "params": _params_block(cfg, signal),
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


def mark_new(payload: dict, previous: dict | None) -> None:
    """Tag stocks that are in the zone now but were not in the previous run's hit list.

    ``previous`` is the previous run's history snapshot for the same tab (see ``history_snapshot``).
    Each window is compared on its own: ``week_new`` and ``qtd_new``. With no previous snapshot
    nothing is tagged, so the first run does not claim that everything is new.
    """
    payload["prev_as_of"] = None
    if not previous or not previous.get("as_of"):
        return

    upper = payload.get("side") == "upper"
    thr = previous.get("params", {}).get("threshold", payload["params"]["threshold"])

    def in_zone(dist) -> bool:
        if dist is None:
            return False
        return dist >= -thr if upper else dist <= thr

    before = {
        (h["market"], h["ticker"]): (in_zone(h.get("week_dist")), in_zone(h.get("qtd_dist")))
        for h in previous.get("hits", [])
    }
    payload["prev_as_of"] = previous["as_of"]
    for row in payload["rows"]:
        if row.get("status") != "ok":
            continue
        was_week, was_qtd = before.get((row["market"], row["ticker"]), (False, False))
        row["week_new"] = bool(row.get("week_hit")) and not was_week
        row["qtd_new"] = bool(row.get("qtd_hit")) and not was_qtd


def build_empty_payload(cfg: Config, side: str, warnings: list[str], generated_at: datetime | None = None) -> dict:
    """A payload with no stocks, used when the holdings list is still empty."""
    generated_at = generated_at or datetime.now(timezone.utc)
    return {
        "side": side,
        "empty": True,
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "as_of": None,
        "params": _params_block(cfg, _signal_for(cfg, side)),
        "counts": {"universe": 0, "loaded": 0, "by_status": {}, "by_market": {}},
        "warnings": warnings,
        "asx_list": {},
        "rows": [],
    }


def history_snapshot(payload: dict) -> dict:
    """Small hits-only record for the history file (keeps the repo light)."""
    if payload.get("side") == "upper":
        keep = ("ticker", "market", "week_high", "upper", "week_dist", "qtd_dist", "close_dist")
    else:
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
