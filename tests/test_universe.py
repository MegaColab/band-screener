from datetime import date

import pytest

from bandscreener.universe import (
    asx_list_warnings,
    load_asx200,
    parse_sp500_table,
    yahoo_symbol_asx,
    yahoo_symbol_us,
)


def test_us_symbol_mapping():
    assert yahoo_symbol_us("BRK.B") == "BRK-B"
    assert yahoo_symbol_us("aapl") == "AAPL"


def test_asx_symbol_mapping():
    assert yahoo_symbol_asx("BHP") == "BHP.AX"
    assert yahoo_symbol_asx("360") == "360.AX"


def test_load_asx200_reads_metadata_and_rows(tmp_path):
    f = tmp_path / "asx.csv"
    f.write_text(
        "# as_of: 2026-09-21\n# note: test list\nticker,name\nBHP,BHP Group Ltd\nXYZ,\"Block, Inc\"\n",
        encoding="utf-8",
    )
    rows, meta = load_asx200(f)
    assert meta == {"as_of": "2026-09-21", "note": "test list"}
    assert [r["yahoo"] for r in rows] == ["BHP.AX", "XYZ.AX"]
    assert rows[1]["name"] == "Block, Inc"
    assert all(r["market"] == "ASX" and r["currency"] == "AUD" for r in rows)


def test_shipped_asx_list_is_well_formed():
    rows, meta = load_asx200(__import__("pathlib").Path(__file__).parent.parent / "data" / "asx200.csv")
    tickers = [r["ticker"] for r in rows]
    assert 190 <= len(tickers) <= 215
    assert len(tickers) == len(set(tickers))
    assert "as_of" in meta


def test_asx_list_age_warning():
    old = asx_list_warnings({"as_of": "2026-01-01"}, 100, date(2026, 11, 10))
    fresh = asx_list_warnings({"as_of": "2026-09-21"}, 100, date(2026, 11, 10))
    assert old and "days old" in old[0]
    assert fresh == []
    assert asx_list_warnings({}, 100, date(2026, 11, 10))


def test_parse_sp500_table():
    html = """
    <table class="wikitable"><thead><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr></thead>
    <tbody>
    <tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td></tr>
    <tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td></tr>
    </tbody></table>
    """
    rows = parse_sp500_table(html)
    assert [r["yahoo"] for r in rows] == ["AAPL", "BRK-B"]
    assert rows[0]["sector"] == "Information Technology"
    assert rows[1]["ticker"] == "BRK.B"
