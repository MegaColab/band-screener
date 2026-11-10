"""Manual target buy / target sell prices and per-tab hiding, read from data/targets.txt.

One stock per line, ticker first (same formats as holdings.txt), then any of:

  buy=40.50        target buy price, in the stock's own currency
  sell=55          target sell price
  hide=buy         hide the stock on the Buy tab ("hide=sell" for the Sell tab, "hide=buy,sell" for both)

Example:  ASX:BHP buy=40.5 sell=55 hide=sell

Lines starting with '#' are comments. Anything that cannot be read is reported on the page
instead of being dropped silently. The file is public, like the rest of the repository.
"""

from __future__ import annotations

from pathlib import Path

from .universe import _holding_row

TABS = ("buy", "sell")


def _price(text: str) -> float | None:
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 and value == value and value != float("inf") else None


def parse_targets(text: str) -> tuple[dict[str, dict], list[str]]:
    """Returns ({"MARKET:TICKER": {"buy", "sell", "hide"}}, problems)."""
    entries: dict[str, dict] = {}
    problems: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        tokens = line.split()
        stock = _holding_row(tokens[0])
        if stock is None:
            problems.append(line)
            continue

        entry = {"buy": None, "sell": None, "hide": []}
        bad = False
        for token in tokens[1:]:
            key, sep, value = token.partition("=")
            key = key.lower()
            if sep and key in ("buy", "sell") and _price(value) is not None:
                entry[key] = _price(value)
            elif sep and key == "hide":
                tabs = [t.strip().lower() for t in value.split(",") if t.strip()]
                if tabs and all(t in TABS for t in tabs):
                    entry["hide"] = sorted(set(entry["hide"]) | set(tabs))
                else:
                    bad = True
            else:
                bad = True
        if bad:
            problems.append(line)
            continue
        entries[f"{stock['market']}:{stock['ticker']}"] = entry

    return entries, problems


def load_targets(path: Path | None, edit_url: str = "") -> dict:
    """What the page needs: entries, a list of warnings, and the link to edit the file."""
    entries: dict[str, dict] = {}
    warnings: list[str] = []
    if path is not None and Path(path).exists():
        entries, problems = parse_targets(Path(path).read_text(encoding="utf-8"))
        if problems:
            warnings.append("Skipped lines in data/targets.txt that could not be read: " + "; ".join(problems) + ".")
    return {"entries": entries, "warnings": warnings, "edit_url": edit_url}
