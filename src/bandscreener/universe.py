"""Which stocks to screen: S&P 500 (fetched weekly) and ASX 200 (maintained list file)."""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

import pandas as pd
import requests

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "band-screener/0.1 (personal stock screener run by GitHub Actions)"


def yahoo_symbol_us(symbol: str) -> str:
    """Wikipedia writes BRK.B; Yahoo Finance writes BRK-B."""
    return symbol.strip().upper().replace(".", "-")


def yahoo_symbol_asx(code: str) -> str:
    return f"{code.strip().upper()}.AX"


def _us_row(symbol: str, name: str, sector: str) -> dict:
    return {
        "ticker": symbol.strip().upper(),
        "yahoo": yahoo_symbol_us(symbol),
        "name": name,
        "market": "US",
        "currency": "USD",
        "sector": sector,
    }


def parse_sp500_table(html: str) -> list[dict]:
    tables = pd.read_html(io.StringIO(html), match="Symbol")
    df = tables[0]
    cols = {str(c).strip().lower(): c for c in df.columns}
    sym_col = cols["symbol"]
    name_col = cols.get("security") or cols.get("company")
    sector_col = cols.get("gics sector")
    rows = []
    for _, r in df.iterrows():
        rows.append(
            _us_row(
                str(r[sym_col]),
                str(r[name_col]) if name_col is not None else "",
                str(r[sector_col]) if sector_col is not None else "",
            )
        )
    return rows


def load_sp500(cache_file: Path) -> tuple[list[dict], list[str]]:
    """Fetch the current S&P 500 list; fall back to the last good copy if the fetch fails."""
    warnings: list[str] = []
    try:
        resp = requests.get(SP500_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        rows = parse_sp500_table(resp.text)
        if len(rows) < 450:
            raise ValueError(f"only {len(rows)} S&P 500 rows parsed")
        _write_cache(cache_file, rows)
        return rows, warnings
    except Exception as exc:  # noqa: BLE001 - any failure should fall back to the cache
        if cache_file.exists():
            warnings.append(f"S&P 500 list could not be refreshed ({exc}); using the last saved copy.")
            return _read_cache(cache_file), warnings
        raise RuntimeError(f"Could not load the S&P 500 list and no cached copy exists: {exc}") from exc


def _write_cache(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["ticker", "name", "sector"])
        for r in sorted(rows, key=lambda r: r["ticker"]):
            writer.writerow([r["ticker"], r["name"], r["sector"]])


def _read_cache(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [_us_row(r["ticker"], r["name"], r["sector"]) for r in csv.DictReader(fh)]


def load_asx200(path: Path) -> tuple[list[dict], dict]:
    """Read the ASX 200 list file. Lines starting with '#' hold metadata as 'key: value'."""
    meta: dict[str, str] = {}
    data_lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            key, _, value = line[1:].partition(":")
            meta[key.strip()] = value.strip()
        elif line.strip():
            data_lines.append(line)
    rows = []
    for r in csv.DictReader(data_lines):
        rows.append(
            {
                "ticker": r["ticker"].strip().upper(),
                "yahoo": yahoo_symbol_asx(r["ticker"]),
                "name": r["name"].strip(),
                "market": "ASX",
                "currency": "AUD",
                "sector": "",
            }
        )
    return rows, meta


def asx_list_warnings(meta: dict, max_age_days: int, today: date) -> list[str]:
    as_of = meta.get("as_of")
    if not as_of:
        return ["The ASX 200 list has no 'as_of' date; refresh it."]
    age = (today - date.fromisoformat(as_of)).days
    if age > max_age_days:
        return [
            f"The ASX 200 list is {age} days old (as at {as_of}). "
            "Refresh data/asx200.csv after the latest quarterly rebalance."
        ]
    return []


def load_universe(cfg, today: date | None = None) -> tuple[list[dict], list[str], dict]:
    """All stocks to screen, warnings, and the ASX list metadata."""
    today = today or date.today()
    us, us_warn = load_sp500(cfg.sp500_cache_file)
    asx, meta = load_asx200(cfg.asx200_file)
    warnings = us_warn + asx_list_warnings(meta, cfg.asx200_max_age_days, today)
    return us + asx, warnings, meta


# --- holdings (the Sell tab) -------------------------------------------------

US_EXCHANGES = {"NASDAQ", "NYSE", "NYSEARCA", "NYSEAMERICAN", "NYSEMKT", "AMEX", "BATS", "CBOE", "US"}


def parse_holdings(text: str) -> tuple[list[dict], list[str]]:
    """Parse the holdings file into universe rows, plus any entries that could not be understood.

    Accepted entries (one per line or separated by commas/spaces; '#' starts a comment):
      ASX:BHP   BHP.AX            -> ASX
      NASDAQ:NVDA  NYSE:KO  NVDA  -> US (a plain symbol is treated as US)
      BRK.B  BRK-B                -> US, written the way Yahoo expects
    """
    rows: list[dict] = []
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()

    for line in text.splitlines():
        line = line.split("#", 1)[0]
        for token in line.replace(",", " ").split():
            entry = _holding_row(token)
            if entry is None:
                problems.append(token)
                continue
            key = (entry["market"], entry["ticker"])
            if key not in seen:
                seen.add(key)
                rows.append(entry)
    return rows, problems


def _holding_row(token: str) -> dict | None:
    token = token.strip().upper()
    if not token:
        return None
    market = "US"
    symbol = token
    if ":" in token:
        exchange, _, symbol = token.partition(":")
        if exchange == "ASX":
            market = "ASX"
        elif exchange in US_EXCHANGES:
            market = "US"
        else:
            return None  # an exchange we do not support
    elif token.endswith(".AX"):
        market, symbol = "ASX", token[:-3]
    if not symbol or not all(ch.isalnum() or ch in ".-" for ch in symbol):
        return None
    if market == "ASX":
        return {"ticker": symbol, "yahoo": yahoo_symbol_asx(symbol), "name": "", "market": "ASX",
                "currency": "AUD", "sector": ""}
    return {"ticker": symbol, "yahoo": yahoo_symbol_us(symbol), "name": "", "market": "US",
            "currency": "USD", "sector": ""}


def load_holdings(path: Path) -> tuple[list[dict], list[str]]:
    """Read the holdings file. Returns (rows, warnings). A missing or empty file gives no rows."""
    if not path.exists():
        return [], []
    rows, problems = parse_holdings(path.read_text(encoding="utf-8"))
    warnings = []
    if problems:
        warnings.append("Skipped entries in the holdings list that could not be read: " + ", ".join(problems) + ".")
    return rows, warnings
