import numpy as np
import pandas as pd
import pytest

from bandscreener.signals import SignalParams, bollinger, evaluate, quarterly_closes

from helpers import AS_OF, band_for, make_daily, rising_closes

PARAMS = SignalParams(bb_period=20, bb_std=2.0, threshold=0.10, week_days=5, band_mode="live")


def run(df, params=PARAMS, latest=AS_OF):
    return evaluate(df, params, as_of=AS_OF, latest_market_date=latest)


# --- building blocks -------------------------------------------------------

def test_quarterly_closes_are_last_close_of_each_quarter():
    idx = pd.bdate_range("2026-01-01", "2026-06-30")
    df = pd.DataFrame({"Close": np.arange(len(idx), dtype=float)}, index=idx)
    q = quarterly_closes(df, pd.Timestamp("2026-06-30"), include_current=True)
    assert list(q.index.astype(str)) == ["2026Q1", "2026Q2"]
    assert q.iloc[0] == df.loc[:"2026-03-31", "Close"].iloc[-1]
    assert q.iloc[1] == df["Close"].iloc[-1]


def test_quarterly_closes_can_drop_the_current_quarter():
    idx = pd.bdate_range("2026-01-01", "2026-11-13")
    df = pd.DataFrame({"Close": np.arange(len(idx), dtype=float)}, index=idx)
    live = quarterly_closes(df, AS_OF, include_current=True)
    frozen = quarterly_closes(df, AS_OF, include_current=False)
    assert str(live.index[-1]) == "2026Q4"
    assert str(frozen.index[-1]) == "2026Q3"


def test_bollinger_matches_population_standard_deviation():
    q = pd.Series(np.arange(1.0, 21.0))  # 1..20
    lower, mid, upper = bollinger(q, 20, 2.0)
    assert mid == pytest.approx(10.5)
    sd = np.sqrt((20**2 - 1) / 12)  # population sd of 1..20
    assert lower == pytest.approx(10.5 - 2 * sd)
    assert upper == pytest.approx(10.5 + 2 * sd)


def test_bollinger_needs_enough_bars():
    assert bollinger(pd.Series([1.0] * 19), 20, 2.0) is None


# --- the business rule: lowest price, not closing price --------------------

def test_touch_and_rally_is_visible():
    """The low came within 10% of the band on Tuesday, then price rallied. It must still appear."""
    prior, final = rising_closes(), 110.0
    lower, _, _ = band_for(prior, final)
    touch_low = lower * 1.05  # 5% above the band, mid-week
    df = make_daily(prior, final, overrides={"2026-11-10": {"Low": touch_low}})
    r = run(df)
    assert r["status"] == "ok"
    assert r["lower"] == pytest.approx(lower)
    assert r["week_low"] == pytest.approx(touch_low)
    assert r["week_dist"] == pytest.approx(0.05)
    assert r["week_hit"] is True
    assert r["close_dist"] > 0.10          # the close ended far above the band
    assert r["week_rallied"] is True


def test_close_only_screen_would_have_missed_it():
    prior, final = rising_closes(), 110.0
    lower, _, _ = band_for(prior, final)
    df = make_daily(prior, final, overrides={"2026-11-10": {"Low": lower * 1.05}})
    r = run(df)
    assert r["close"] / r["lower"] - 1 > 0.10  # a closing-price screen fails this stock
    assert r["week_hit"] is True               # the low-based screen catches it


def test_low_below_the_band_passes_with_negative_gap():
    prior, final = rising_closes(), 110.0
    lower, _, _ = band_for(prior, final)
    df = make_daily(prior, final, overrides={"2026-11-12": {"Low": lower * 0.97}})
    r = run(df)
    assert r["week_dist"] == pytest.approx(-0.03)
    assert r["week_hit"] is True


def test_threshold_is_configurable():
    prior, final = rising_closes(), 110.0
    lower, _, _ = band_for(prior, final)
    df = make_daily(prior, final, overrides={"2026-11-11": {"Low": lower * 1.08}})
    assert run(df)["week_hit"] is True                       # 8% above the band is inside the 10% default
    assert run(df, SignalParams(threshold=0.05))["week_hit"] is False   # but outside a 5% setting
    assert run(df, SignalParams(threshold=0.25))["week_hit"] is True
    df2 = make_daily(prior, final, overrides={"2026-11-11": {"Low": lower * 1.12}})
    assert run(df2)["week_hit"] is False                     # 12% is outside the 10% default


def test_far_from_band_does_not_pass():
    prior, final = rising_closes(), 110.0
    df = make_daily(prior, final)  # lows sit at 99.5% of a close far above the band
    r = run(df)
    assert r["week_hit"] is False and r["qtd_hit"] is False


# --- week window vs quarter-to-date ---------------------------------------

def test_old_low_shows_in_quarter_to_date_but_not_in_week():
    prior, final = rising_closes(), 110.0
    lower, _, _ = band_for(prior, final)
    df = make_daily(prior, final, overrides={"2026-10-08": {"Low": lower * 1.02}})  # five weeks ago
    r = run(df)
    assert r["week_hit"] is False
    assert r["qtd_hit"] is True
    assert r["qtd_low_date"] == "2026-10-08"


def test_week_window_is_the_last_n_trading_days():
    prior, final = rising_closes(), 110.0
    lower, _, _ = band_for(prior, final)
    # 2026-11-06 is the Friday before the last 5 sessions (Nov 9-13): outside the window
    df = make_daily(prior, final, overrides={"2026-11-06": {"Low": lower * 1.02}})
    assert run(df)["week_hit"] is False
    wide = SignalParams(week_days=6)
    assert run(df, wide)["week_hit"] is True


# --- band modes -------------------------------------------------------------

def test_live_and_frozen_bands_use_different_bars():
    """Frozen uses 20 completed quarters; live swaps the oldest for the unfinished quarter."""
    prior = rising_closes()
    idx = pd.bdate_range("2021-10-01", AS_OF)
    quarters = pd.period_range("2021Q4", "2026Q3", freq="Q")  # 20 completed quarters
    values = dict(zip(quarters, [50.0] + prior))
    close = np.array([values.get(q, 40.0) for q in idx.to_period("Q")], dtype=float)  # current quarter closes at 40
    df = pd.DataFrame({"Open": close, "High": close, "Low": close * 0.995, "Close": close, "Volume": 1e6}, index=idx)

    frozen = run(df, SignalParams(band_mode="frozen"))
    live = run(df, SignalParams(band_mode="live"))

    completed = np.array([50.0] + prior)
    with_current = np.array(prior + [40.0])
    assert frozen["status"] == live["status"] == "ok"
    assert frozen["lower"] == pytest.approx(completed.mean() - 2 * completed.std())
    assert live["lower"] == pytest.approx(with_current.mean() - 2 * with_current.std())
    assert frozen["lower"] != pytest.approx(live["lower"])


def test_frozen_mode_needs_twenty_completed_quarters():
    # the standard fixture has 19 completed quarters, so frozen mode cannot form a band
    r = run(make_daily(rising_closes(), 110.0), SignalParams(band_mode="frozen"))
    assert r["status"] == "insufficient_history"


# --- statuses and edge cases ------------------------------------------------

def test_negative_band_is_reported_separately():
    prior = [1.0, 300.0] * 9 + [1.0]          # wildly volatile: lower band falls below zero
    final = 1.0
    assert band_for(prior, final)[0] < 0
    r = run(make_daily(prior, final))
    assert r["status"] == "negative_band"
    assert "week_dist" not in r


def test_insufficient_history():
    df = make_daily(rising_closes(), 110.0, start="2024-01-02")
    r = run(df)
    assert r["status"] == "insufficient_history"
    assert r["bars"] < 20


def test_stale_stock_is_flagged():
    df = make_daily(rising_closes(), 110.0)
    df = df[df.index <= AS_OF - pd.Timedelta(days=30)]
    assert run(df)["status"] == "stale"


def test_no_data():
    assert run(None)["status"] == "no_data"
    assert run(pd.DataFrame())["status"] == "no_data"


def test_missing_low_values_fall_back_to_close():
    prior, final = rising_closes(), 110.0
    df = make_daily(prior, final)
    df["Low"] = np.nan
    r = run(df)
    assert r["status"] == "ok"
    assert r["week_low"] == pytest.approx(final)


def test_average_daily_value_uses_close_times_volume():
    df = make_daily(rising_closes(), 110.0, volume=2_000_000)
    r = run(df)
    expected = (df["Close"] * df["Volume"]).tail(60).mean()  # last 60 sessions straddle two quarters
    assert r["adv"] == pytest.approx(expected)
