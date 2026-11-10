# Band Screener

Every Saturday morning (Sydney time) this repo screens the **S&P 500** and the **ASX 200** and publishes a dashboard of stocks whose recent **lowest price** came within 10% of the **lower quarterly Bollinger Band**.

It runs entirely on GitHub Actions with plain Python. No AI is involved, so it costs nothing to run.

## What counts as "close to the band"

- **Bands:** average of the last 20 quarterly closes, minus 2 standard deviations. By default the unfinished quarter counts as the latest bar, so the band matches a chart today (`band_mode = "frozen"` uses completed quarters only).
- **Gap:** `(lowest daily low in the window - lower band) / lower band`. Negative means the low broke below the band.
- **Windows:** the lowest low over the last 5 trading days (week), or since the start of the quarter (quarter-to-date). The dashboard switches between them.
- **Lowest price, not closing price:** a stock that touched the band on Tuesday and rallied by Friday still appears, with a "rallied since" tag.
- **Threshold:** 10% by default. Change `proximity_threshold` in `config.toml`, or type a different number on the dashboard to try it instantly.
- **Separate sections:** a lower band at or below zero ("band not meaningful"), stocks with fewer than 20 quarterly bars ("not enough history"), and stocks with missing or stale data.
- **Liquidity:** thin stocks are tagged "low liquidity", never removed. A tick box hides them.

## One-time setup

1. In the repo, go to **Settings → Pages**. Under "Build and deployment", set **Source** to *Deploy from a branch*, branch **main**, folder **/docs**, then Save.
2. Go to **Actions → Weekly screen → Run workflow** to create the first dashboard. It takes a few minutes.
3. The dashboard is then at the address shown on the Pages settings page. Bookmark it on your phone.

After that it runs by itself each week. You can also run it by hand any time from the same Actions tab.

## Settings (`config.toml`)

| Setting | Default | Meaning |
|---|---|---|
| `proximity_threshold` | 0.10 | How close counts as close (10%) |
| `week_lookback_days` | 5 | Trading days in the "week" window |
| `band_mode` | live | `live` or `frozen` (see above) |
| `bb_period`, `bb_std` | 20, 2.0 | Standard Bollinger settings |
| `min_avg_daily_value_us/au` | 5M / 1M | Below this a stock is tagged low liquidity |
| `min_success_ratio` | 0.80 | If fewer stocks than this load, the run stops and the old dashboard stays |

## Keeping the ASX 200 list current

The S&P 500 list is fetched fresh from Wikipedia each run. The ASX 200 list is the file `data/asx200.csv`, because no free reliable feed exists. The index changes in March, June, September and December. After each change, replace the file (same two columns, `ticker,name`) and update the `# as_of:` line at the top. The dashboard shows a warning when the list is more than 100 days old.

The current file is **approximate**: it was built from a third-party snapshot patched with the official S&P announcements, and it is not an exact index copy. That is fine for a screening guide.

## Layout

| Path | Job |
|---|---|
| `src/bandscreener/signals.py` | The business logic: quarterly bars, bands, gaps. Pure functions, fully tested |
| `src/bandscreener/universe.py` | Which stocks to screen |
| `src/bandscreener/data.py` | Price downloads from Yahoo Finance |
| `src/bandscreener/pipeline.py` | Runs the signal over every stock and builds the result |
| `src/bandscreener/report.py`, `templates/` | Dashboard page and data files |
| `config.toml` | All settings |
| `tests/` | Automated tests, run before every weekly screen |
| `docs/` | Published dashboard and data (written by the workflow) |

To add another market or index, add a loader in `universe.py` that returns the same fields. To add another indicator, add a function beside the Bollinger one in `signals.py` and a column in the template. Weekly hit lists are kept in `docs/data/history/`, ready for "new this week" features.

## Running on your own computer (optional)

```
pip install -r requirements.txt
python -m pytest
PYTHONPATH=src python -m bandscreener run --demo    # synthetic data, no internet, writes demo_out/
PYTHONPATH=src python -m bandscreener run           # real run, writes docs/
```

## Privacy

This is a public repository and contains no personal data: only index lists, code, settings and screening results. Nothing about holdings or accounts belongs here. A test (`tests/test_privacy.py`) fails if an email address appears in any file.

## Limits to know about

- Prices come from Yahoo Finance, which is free but unofficial. It can rate-limit or change without notice. If too few stocks load, the run stops instead of publishing a half-empty page.
- The week's low is compared with the band as it stands at the latest close. The band moves slightly as the quarter progresses.
- GitHub pauses scheduled workflows in a repository with no activity for 60 days. The weekly run commits its results, which counts as activity.
- Screening output only. It says nothing about why a stock is near its band.
