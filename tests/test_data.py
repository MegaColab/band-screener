import sys
import types

import numpy as np
import pandas as pd

from bandscreener import data


def frame(n=30, tz=None):
    idx = pd.bdate_range("2026-01-01", periods=n, tz=tz)
    close = np.linspace(10, 20, n)
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Adj Close": close, "Volume": 1000.0},
        index=idx,
    )


def multi(symbols, order="ticker"):
    parts = {s: frame() for s in symbols}
    df = pd.concat(parts, axis=1)  # columns: (ticker, field)
    if order == "column":
        df = df.swaplevel(axis=1)
    return df


def test_split_download_ticker_first_columns():
    out = data._split_download(multi(["AAA", "BBB"]), ["AAA", "BBB", "MISSING"])
    assert set(out) == {"AAA", "BBB"}
    assert list(out["AAA"].columns) == ["Open", "High", "Low", "Close", "Volume"]  # Adj Close dropped


def test_split_download_field_first_columns():
    out = data._split_download(multi(["AAA", "BBB"], order="column"), ["AAA", "BBB"])
    assert set(out) == {"AAA", "BBB"}


def test_split_download_single_flat_frame():
    out = data._split_download(frame(), ["AAA"])
    assert set(out) == {"AAA"}


def test_all_nan_symbol_is_dropped():
    raw = multi(["AAA", "BBB"])
    raw["BBB"] = np.nan
    assert set(data._split_download(raw, ["AAA", "BBB"])) == {"AAA"}


def test_timezone_is_removed_and_dates_normalised():
    out = data._split_download(multi(["AAA"]), ["AAA"])["AAA"]
    assert out.index.tz is None
    tz_frame = frame(tz="Australia/Sydney")
    clean = data._normalise(tz_frame)
    assert clean.index.tz is None
    assert (clean.index == clean.index.normalize()).all()


def test_download_uses_start_date_not_an_unsupported_period(monkeypatch):
    calls = []

    def fake_download(symbols, **kwargs):
        calls.append(kwargs)
        return multi(symbols)

    fake = types.SimpleNamespace(download=fake_download)
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setattr(data.time, "sleep", lambda *_: None)

    out = data.download_prices(["AAA", "BBB", "CCC"], years=6, batch_size=2)

    assert set(out) == {"AAA", "BBB", "CCC"}
    assert len(calls) == 2  # two batches
    for kw in calls:
        assert "start" in kw and "period" not in kw  # Yahoo has no 6y period
        assert kw["auto_adjust"] is False
        assert kw["interval"] == "1d"
    years_back = (pd.Timestamp.today() - pd.Timestamp(calls[0]["start"])).days / 365.25
    assert 5.9 < years_back < 6.1


def test_missing_symbols_are_retried_once(monkeypatch):
    seen = []

    def fake_download(symbols, **kwargs):
        seen.append(list(symbols))
        return multi([s for s in symbols if not (s == "BBB" and len(seen) == 1)])  # drops BBB first time

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=fake_download))
    monkeypatch.setattr(data.time, "sleep", lambda *_: None)
    out = data.download_prices(["AAA", "BBB"], batch_size=10)
    assert set(out) == {"AAA", "BBB"}
    assert seen == [["AAA", "BBB"], ["BBB"]]
