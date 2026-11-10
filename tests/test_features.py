"""ETF tag, "new since last run" tag and the shared page controls (Buy and Sell tabs)."""

import json
from pathlib import Path

from bandscreener.cli import main
from bandscreener.config import load_config
from bandscreener.pipeline import build_payload, history_snapshot, mark_new
from bandscreener.report import read_latest, read_previous_snapshot
from bandscreener.sample_data import demo_holdings, demo_universe, synthetic_prices
from bandscreener.universe import load_etfs

ROOT = Path(__file__).parent.parent


def payload_for(side, n=12, etfs=None):
    cfg = load_config(ROOT / "config.toml")
    universe = demo_holdings(n, 0) if side == "upper" else demo_universe(n, 0)
    prices = synthetic_prices([u["yahoo"] for u in universe])
    return build_payload(cfg, universe, prices, [], side=side, etfs=etfs)


# --- ETF list ----------------------------------------------------------------

def test_load_etfs_reads_market_and_ticker_and_ignores_comments(tmp_path):
    f = tmp_path / "etfs.txt"
    f.write_text("# my etfs\nASX:VAS\nNASDAQ:SOXX  # chips\nNYSEARCA:BAI\n")
    assert load_etfs(f) == {("ASX", "VAS"), ("US", "SOXX"), ("US", "BAI")}


def test_load_etfs_missing_file_or_none_means_no_etfs(tmp_path):
    assert load_etfs(tmp_path / "nope.txt") == set()
    assert load_etfs(None) == set()


def test_etf_tag_matches_on_market_and_ticker():
    payload = payload_for("upper", etfs={("US", "USDEMO01")})
    tags = {r["ticker"]: r["is_etf"] for r in payload["rows"]}
    assert tags["USDEMO01"] is True
    assert tags["USDEMO02"] is False
    # an ASX stock with the same code is not tagged by a US entry
    assert all(r["is_etf"] is False for r in payload_for("upper")["rows"])


def test_shipped_etf_list_only_holds_tickers_that_parse():
    text = (ROOT / "data" / "etfs.txt").read_text()
    assert "@" not in text
    assert len(load_etfs(ROOT / "data" / "etfs.txt")) >= 1


# --- "new since the previous run" --------------------------------------------

def snapshot(side, as_of, hits, threshold=0.10):
    return {"as_of": as_of, "generated_at": as_of, "params": {"threshold": threshold}, "hits": hits}


def test_mark_new_flags_only_stocks_that_were_not_in_the_zone_before():
    payload = payload_for("upper")
    hit_now = [r for r in payload["rows"] if r["status"] == "ok" and r["week_hit"]]
    assert len(hit_now) >= 2
    kept, fresh = hit_now[0], hit_now[1]
    prev = snapshot(
        "upper", "2026-11-12",
        [{"ticker": kept["ticker"], "market": kept["market"], "week_dist": kept["week_dist"], "qtd_dist": kept["qtd_dist"]}],
    )
    mark_new(payload, prev)
    by = {r["ticker"]: r for r in payload["rows"] if r["status"] == "ok"}
    assert payload["prev_as_of"] == "2026-11-12"
    assert by[kept["ticker"]]["week_new"] is False
    assert by[fresh["ticker"]]["week_new"] is True
    for r in by.values():  # a stock outside the zone is never "new"
        if not r["week_hit"]:
            assert r["week_new"] is False


def test_mark_new_without_a_previous_run_tags_nothing():
    payload = payload_for("upper")
    mark_new(payload, None)
    assert payload["prev_as_of"] is None
    assert not any("week_new" in r or "qtd_new" in r for r in payload["rows"])


def test_mark_new_works_the_same_way_on_the_buy_side():
    payload = payload_for("lower", n=30)
    hit_now = [r for r in payload["rows"] if r["status"] == "ok" and r["week_hit"]]
    assert hit_now
    mark_new(payload, snapshot("lower", "2026-11-06", []))  # nothing was in the zone last time
    for r in payload["rows"]:
        if r["status"] == "ok":
            assert r["week_new"] == bool(r["week_hit"])


def test_read_previous_snapshot_picks_the_latest_earlier_run_for_the_same_tab(tmp_path):
    hist = tmp_path / "data" / "history"
    hist.mkdir(parents=True)
    for name in ("2026-11-03.json", "2026-11-10.json", "2026-11-17.json", "sell-2026-11-12.json"):
        (hist / name).write_text(json.dumps({"as_of": name[:-5]}))
    assert read_previous_snapshot(tmp_path, "lower", "2026-11-13")["as_of"] == "2026-11-10.json"[:-5]
    assert read_previous_snapshot(tmp_path, "lower", "2026-11-03") is None
    assert read_previous_snapshot(tmp_path, "upper", "2026-11-13")["as_of"] == "sell-2026-11-12"
    assert read_previous_snapshot(tmp_path, "upper", "2026-11-12") is None  # same day is not "previous"
    assert read_previous_snapshot(tmp_path / "missing", "upper", "2026-11-13") is None
    assert read_previous_snapshot(tmp_path, "upper", None) is None


def test_sell_run_marks_new_against_the_previous_history_file(tmp_path):
    cfg = str(ROOT / "config.toml")
    hist = tmp_path / "data" / "history"
    hist.mkdir(parents=True)
    (hist / "sell-2026-11-12.json").write_text(json.dumps(snapshot("upper", "2026-11-12", [])))
    assert main(["sell", "--config", cfg, "--demo", "--out", str(tmp_path)]) == 0
    data = read_latest(tmp_path, "upper")
    assert data["prev_as_of"] == "2026-11-12"
    assert any(r.get("week_new") for r in data["rows"])
    # the history file written by this run feeds the next one
    snap = json.loads((hist / f"sell-{data['as_of']}.json").read_text())
    assert snap["hits"] and {"week_dist", "qtd_dist"} <= set(snap["hits"][0])


def test_history_snapshot_still_lists_only_hits_after_the_new_fields():
    payload = payload_for("upper")
    mark_new(payload, snapshot("upper", "2026-11-12", []))
    expected = {r["ticker"] for r in payload["rows"] if r["status"] == "ok" and (r["week_hit"] or r["qtd_hit"])}
    assert {h["ticker"] for h in history_snapshot(payload)["hits"]} == expected


# --- the shared page ---------------------------------------------------------

def test_page_carries_the_new_controls_on_both_tabs(tmp_path):
    cfg = str(ROOT / "config.toml")
    assert main(["run", "--config", cfg, "--demo", "--out", str(tmp_path)]) == 0
    assert main(["sell", "--config", cfg, "--demo", "--out", str(tmp_path)]) == 0
    html = (tmp_path / "index.html").read_text()
    for role in ('data-role="typ"', 'data-role="newonly"', 'data-role="all"'):
        assert role in html
    assert html.count('data-role="typewrap"') == 2  # one macro, rendered for each tab
