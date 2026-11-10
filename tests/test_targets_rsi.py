"""Manual targets and per-tab hiding, and the quarterly RSI."""

import json
from pathlib import Path

import pandas as pd
import pytest

from bandscreener.cli import main
from bandscreener.config import load_config
from bandscreener.indicators import quarterly_rsi, wilder_rsi
from bandscreener.pipeline import build_payload
from bandscreener.report import render_dashboard
from bandscreener.sample_data import demo_holdings, synthetic_prices
from bandscreener.targets import load_targets, parse_targets

from helpers import AS_OF, make_daily, rising_closes

ROOT = Path(__file__).parent.parent


# --- targets file ------------------------------------------------------------

def test_parse_targets_reads_prices_and_hiding():
    entries, problems = parse_targets(
        "# my targets\n"
        "ASX:BHP buy=40.5 sell=55\n"
        "nasdaq:nvda sell=$1,240 hide=buy  # chips\n"
        "BHP.AX hide=buy,sell\n"
    )
    assert problems == []
    assert entries["ASX:BHP"] == {"buy": None, "sell": None, "hide": ["buy", "sell"]}  # last line wins
    assert entries["US:NVDA"] == {"buy": None, "sell": 1240.0, "hide": ["buy"]}


def test_parse_targets_keeps_both_prices_on_one_line():
    entries, _ = parse_targets("ASX:WOW buy=28 sell=36.25 hide=sell")
    assert entries["ASX:WOW"] == {"buy": 28.0, "sell": 36.25, "hide": ["sell"]}


@pytest.mark.parametrize(
    "line",
    [
        "LON:VOD buy=1",          # unsupported exchange
        "ASX:BHP buy=abc",        # not a number
        "ASX:BHP buy=-5",         # not a positive price
        "ASX:BHP buy=0",
        "ASX:BHP hide=everywhere",
        "ASX:BHP hide=",
        "ASX:BHP target=5",       # unknown field
        "ASX:BHP 40",             # missing field name
    ],
)
def test_parse_targets_reports_lines_it_cannot_read_instead_of_dropping_them(line):
    entries, problems = parse_targets(line + "\nASX:WOW buy=28\n")
    assert problems == [line]
    assert list(entries) == ["ASX:WOW"]  # the good line is unaffected


def test_load_targets_missing_file_is_empty_and_carries_the_edit_link(tmp_path):
    assert load_targets(tmp_path / "nope.txt", "https://example.test/edit") == {
        "entries": {}, "warnings": [], "edit_url": "https://example.test/edit",
    }
    assert load_targets(None)["entries"] == {}


def test_load_targets_warns_about_unreadable_lines(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("ASX:BHP buy=40\nASX:WOW buy=oops\n")
    result = load_targets(f)
    assert "ASX:BHP" in result["entries"]
    assert "ASX:WOW buy=oops" in result["warnings"][0]


def test_shipped_targets_file_parses_cleanly_and_has_no_personal_data():
    path = ROOT / "data" / "targets.txt"
    assert "@" not in path.read_text()
    assert load_targets(path)["warnings"] == []


# --- RSI ---------------------------------------------------------------------

def test_wilder_rsi_matches_a_hand_calculation():
    # period 2, closes 10, 12, 11, 13: changes +2, -1, +2.
    # First averages: gain (2+0)/2 = 1, loss (0+1)/2 = 0.5. Then gain (1*1+2)/2 = 1.5, loss (0.5*1+0)/2 = 0.25.
    # RS = 6, RSI = 100 - 100/7.
    assert wilder_rsi(pd.Series([10.0, 12.0, 11.0, 13.0]), period=2) == pytest.approx(100 - 100 / 7)


def test_wilder_rsi_extremes_and_short_history():
    assert wilder_rsi(pd.Series(range(1, 30, 2), dtype=float)) == 100.0  # only gains
    assert wilder_rsi(pd.Series(range(30, 1, -2), dtype=float)) == 0.0   # only losses
    assert wilder_rsi(pd.Series([1.0] * 14)) is None                      # needs period + 1 closes
    assert wilder_rsi(pd.Series([], dtype=float)) is None


def test_wilder_rsi_ignores_gaps_in_the_series():
    assert wilder_rsi(pd.Series([10.0, None, 12.0, 11.0, 13.0]), period=2) == pytest.approx(100 - 100 / 7)


def test_quarterly_rsi_uses_the_quarterly_closes_including_the_unfinished_quarter():
    prior, final = rising_closes(), 80.0
    df = make_daily(prior, final)
    expected = wilder_rsi(pd.Series(prior + [final]))
    assert quarterly_rsi(df, AS_OF, include_current=True) == pytest.approx(expected)
    # frozen mode: completed quarters only. Those only rise, so RSI is 100; the live quarter's drop pulls it down.
    assert quarterly_rsi(df, AS_OF, include_current=False) == pytest.approx(wilder_rsi(pd.Series(prior)))
    assert quarterly_rsi(df, AS_OF, include_current=False) == 100.0
    assert expected < 100.0
    assert quarterly_rsi(None, AS_OF) is None


def test_payload_rows_carry_rsi_and_the_thresholds():
    cfg = load_config(ROOT / "config.toml")
    universe = demo_holdings(12, 0)
    payload = build_payload(cfg, universe, synthetic_prices([u["yahoo"] for u in universe]), [], side="upper")
    scored = [r for r in payload["rows"] if r["status"] == "ok"]
    assert scored
    for r in scored:
        assert r["rsi"] is None or 0 <= r["rsi"] <= 100
    assert any(r["rsi"] is not None for r in scored)
    assert all("rsi" not in r for r in payload["rows"] if r["status"] != "ok")
    assert payload["params"]["rsi_oversold"] == 30 and payload["params"]["rsi_overbought"] == 70
    json.dumps(payload, allow_nan=False)


def test_config_rejects_a_nonsense_rsi_band(tmp_path):
    bad = tmp_path / "config.toml"
    bad.write_text((ROOT / "config.toml").read_text().replace("oversold = 30 ", "oversold = 80 "))
    with pytest.raises(ValueError):
        load_config(bad)


# --- the page ----------------------------------------------------------------

def test_page_embeds_the_targets_and_the_edit_link():
    targets = {"entries": {"ASX:BHP": {"buy": 40.5, "sell": 55.0, "hide": ["buy"]}},
               "warnings": [], "edit_url": "https://example.test/edit"}
    html = render_dashboard(None, None, targets)
    block = html.split('id="targets">')[1].split("</script>")[0]
    assert json.loads(block) == targets


def test_page_without_targets_still_renders():
    block = render_dashboard(None, None).split('id="targets">')[1].split("</script>")[0]
    assert json.loads(block)["entries"] == {}


def test_cli_run_puts_the_targets_file_on_the_page(tmp_path):
    targets = tmp_path / "targets.txt"
    targets.write_text("ASX:AUDEMO01 buy=12.5 sell=20 hide=sell\nASX:AUDEMO02 buy=oops\n")
    cfg = tmp_path / "config.toml"
    text = (ROOT / "config.toml").read_text()
    cfg.write_text(text.replace('file = "data/targets.txt"', f"file = {json.dumps(str(targets))}"))
    out = tmp_path / "docs"
    assert main(["sell", "--config", str(cfg), "--demo", "--out", str(out)]) == 0
    html = (out / "index.html").read_text()
    data = json.loads(html.split('id="targets">')[1].split("</script>")[0])
    assert data["entries"]["ASX:AUDEMO01"] == {"buy": 12.5, "sell": 20.0, "hide": ["sell"]}
    assert "AUDEMO02" in data["warnings"][0]
    assert data["edit_url"].startswith("https://github.com/")


def test_phone_layout_and_new_columns_are_in_the_template():
    html = render_dashboard(None, None)
    for needle in ("Target buy", "Target sell", "RSI (qtr)", "@media (max-width: 640px)", "data-role=\"sortsel\""):
        assert needle in html
