import json
from dataclasses import replace
from pathlib import Path

import pytest

from bandscreener.cli import main
from bandscreener.config import load_config
from bandscreener.pipeline import build_empty_payload, build_payload, history_snapshot
from bandscreener.report import read_latest, write_outputs
from bandscreener.sample_data import demo_holdings, synthetic_prices
from bandscreener.signals import SignalParams, evaluate_upper
from bandscreener.universe import load_holdings, parse_holdings

from helpers import AS_OF, band_for, make_daily, rising_closes

ROOT = Path(__file__).parent.parent
PARAMS = SignalParams(bb_period=20, bb_std=2.0, threshold=0.10, week_days=5, band_mode="live")


def run(df, latest=AS_OF):
    return evaluate_upper(df, PARAMS, as_of=AS_OF, latest_market_date=latest)


# --- upper band logic: highest price, not closing price ---------------------

def test_high_touch_then_pullback_is_visible():
    prior, final = rising_closes(), 80.0
    _, _, upper = band_for(prior, final)
    touch_high = upper * 0.95  # 5% below the upper band, mid-week
    df = make_daily(prior, final, overrides={"2026-11-10": {"High": touch_high}})
    r = run(df)
    assert r["status"] == "ok"
    assert r["upper"] == pytest.approx(upper)
    assert r["week_high"] == pytest.approx(touch_high)
    assert r["week_dist"] == pytest.approx(touch_high / upper - 1)
    assert r["week_hit"]
    assert r["week_pullback"]  # the close is nowhere near the band any more


def test_high_above_band_is_a_hit_with_positive_gap():
    prior, final = rising_closes(), 80.0
    _, _, upper = band_for(prior, final)
    df = make_daily(prior, final, overrides={"2026-11-12": {"High": upper * 1.03}})
    r = run(df)
    assert r["week_hit"]
    assert r["week_dist"] == pytest.approx(0.03)


def test_high_far_below_band_is_not_a_hit():
    prior, final = rising_closes(), 80.0
    _, _, upper = band_for(prior, final)
    df = make_daily(prior, final, overrides={"2026-11-12": {"High": upper * 0.85}})
    r = run(df)
    assert not r["week_hit"]


def test_threshold_boundary_is_inclusive_either_side():
    prior, final = rising_closes(), 80.0
    _, _, upper = band_for(prior, final)
    near = make_daily(prior, final, overrides={"2026-11-12": {"High": upper * 0.92}})
    far = make_daily(prior, final, overrides={"2026-11-12": {"High": upper * 0.88}})
    assert run(near)["week_hit"]
    assert not run(far)["week_hit"]


def test_old_high_outside_the_week_only_counts_in_quarter_to_date():
    prior, final = rising_closes(), 80.0
    _, _, upper = band_for(prior, final)
    df = make_daily(prior, final, overrides={"2026-10-06": {"High": upper * 1.02}})
    r = run(df)
    assert not r["week_hit"]
    assert r["qtd_hit"]
    assert r["qtd_high"] == pytest.approx(upper * 1.02)


def test_short_history_and_missing_data_are_reported_not_scored():
    df = make_daily(rising_closes(), 80.0, start="2025-01-02")
    assert run(df)["status"] == "insufficient_history"
    assert run(None)["status"] == "no_data"


# --- holdings file ---------------------------------------------------------

def test_parse_holdings_accepts_the_common_formats():
    rows, problems = parse_holdings("ASX:BHP, BHP.AX\nNASDAQ:NVDA NYSE:KO aapl\nBRK.B\n")
    by = {(r["market"], r["ticker"]): r["yahoo"] for r in rows}
    assert by[("ASX", "BHP")] == "BHP.AX"
    assert by[("US", "NVDA")] == "NVDA"
    assert by[("US", "KO")] == "KO"
    assert by[("US", "AAPL")] == "AAPL"
    assert by[("US", "BRK.B")] == "BRK-B"
    assert len(rows) == 5  # BHP listed twice, kept once
    assert problems == []


def test_parse_holdings_ignores_comments_and_reports_unsupported_exchanges():
    rows, problems = parse_holdings("# my list\nNVDA  # chips\nLON:VOD\n")
    assert [r["ticker"] for r in rows] == ["NVDA"]
    assert problems == ["LON:VOD"]


def test_load_holdings_missing_or_comment_only_file_is_empty(tmp_path):
    assert load_holdings(tmp_path / "nope.txt") == ([], [])
    f = tmp_path / "h.txt"
    f.write_text("# nothing yet\n")
    assert load_holdings(f) == ([], [])


def test_load_holdings_warns_about_unreadable_entries(tmp_path):
    f = tmp_path / "h.txt"
    f.write_text("NVDA\nLON:VOD\n")
    rows, warnings = load_holdings(f)
    assert len(rows) == 1
    assert "LON:VOD" in warnings[0]


def test_shipped_holdings_file_contains_no_personal_data():
    text = (ROOT / "data" / "holdings.txt").read_text()
    assert "@" not in text


# --- payload, files, CLI ---------------------------------------------------

def sell_payload():
    cfg = load_config(ROOT / "config.toml")
    universe = demo_holdings()
    prices = synthetic_prices([u["yahoo"] for u in universe])
    return cfg, build_payload(cfg, universe, prices, [], side="upper")


def test_sell_payload_marks_hits_at_or_above_minus_threshold():
    cfg, payload = sell_payload()
    assert payload["side"] == "upper"
    t = cfg.sell_threshold
    scored = [r for r in payload["rows"] if r["status"] == "ok"]
    assert scored
    for r in scored:
        assert r["week_hit"] == (r["week_dist"] >= -t)
    json.dumps(payload, allow_nan=False)


def test_sell_threshold_is_configurable_separately():
    cfg, _ = sell_payload()
    strict = replace(cfg, sell_threshold=0.0)
    universe = demo_holdings()
    prices = synthetic_prices([u["yahoo"] for u in universe])
    payload = build_payload(strict, universe, prices, [], side="upper")
    assert payload["params"]["threshold"] == 0.0
    for r in payload["rows"]:
        if r["status"] == "ok":
            assert r["week_hit"] == (r["week_dist"] >= 0)


def test_sell_history_snapshot_lists_only_hits():
    _, payload = sell_payload()
    snap = history_snapshot(payload)
    expected = {r["ticker"] for r in payload["rows"] if r["status"] == "ok" and (r["week_hit"] or r["qtd_hit"])}
    assert {h["ticker"] for h in snap["hits"]} == expected


def test_buy_and_sell_runs_share_one_page_without_overwriting_each_other(tmp_path):
    cfg = str(ROOT / "config.toml")
    assert main(["run", "--config", cfg, "--demo", "--out", str(tmp_path)]) == 0
    assert main(["sell", "--config", cfg, "--demo", "--out", str(tmp_path)]) == 0
    assert read_latest(tmp_path, "lower")["side"] == "lower"
    assert read_latest(tmp_path, "upper")["side"] == "upper"
    html = (tmp_path / "index.html").read_text()
    assert 'id="payload-buy"' in html and 'id="payload-sell"' in html
    assert "null" not in html.split('id="payload-buy">')[1][:10]
    assert "null" not in html.split('id="payload-sell">')[1][:10]
    hist = {p.name for p in (tmp_path / "data" / "history").iterdir()}
    assert any(n.startswith("sell-") for n in hist)
    assert any(not n.startswith("sell-") for n in hist)

    # A later buy run must keep the Sell tab's data.
    assert main(["run", "--config", cfg, "--demo", "--out", str(tmp_path)]) == 0
    assert 'id="payload-sell">null' not in (tmp_path / "index.html").read_text()


def test_empty_holdings_writes_an_empty_sell_tab_and_succeeds(tmp_path):
    holdings = tmp_path / "holdings.txt"
    holdings.write_text("# nothing yet\n")
    cfg = tmp_path / "config.toml"
    cfg.write_text((ROOT / "config.toml").read_text().replace('"data/holdings.txt"', json.dumps(str(holdings))))
    # config paths are resolved against the config file's folder; absolute paths pass through unchanged
    out = tmp_path / "docs"
    assert main(["sell", "--config", str(cfg), "--out", str(out)]) == 0
    data = read_latest(out, "upper")
    assert data["empty"] is True and data["rows"] == []
    assert (out / "index.html").exists()


def test_build_empty_payload_is_valid_json():
    cfg = load_config(ROOT / "config.toml")
    json.dumps(build_empty_payload(cfg, "upper", []), allow_nan=False)
