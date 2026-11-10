"""Render the dashboard page and write the output files.

The page has two tabs, Buy and Sell. Each is produced by a different run (weekly screen and
daily holdings watch), so each run re-reads the other tab's latest data file from disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .pipeline import history_snapshot

TEMPLATE_DIR = Path(__file__).parent / "templates"

# side -> (latest data file, history file prefix)
FILES = {
    "lower": ("latest.json", ""),
    "upper": ("sell_latest.json", "sell-"),
}


def render_dashboard(buy: dict | None, sell: dict | None = None) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    return env.get_template("dashboard.html.j2").render(buy=buy, sell=sell)


def _dump(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=False, allow_nan=False)


def read_latest(out_dir: Path, side: str) -> dict | None:
    """The most recently published data for one tab, or None if it has not run yet."""
    path = Path(out_dir) / "data" / FILES[side][0]
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_outputs(payload: dict, out_dir: Path, keep_history: bool = True) -> list[Path]:
    """Write this run's data file, its history record, and the page (served by GitHub Pages)."""
    out_dir = Path(out_dir)
    side = payload.get("side", "lower")
    latest_name, history_prefix = FILES[side]
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    written = []

    latest = out_dir / "data" / latest_name
    latest.write_text(_dump(payload), encoding="utf-8")
    written.append(latest)

    if keep_history and payload.get("as_of"):
        hist_dir = out_dir / "data" / "history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        hist = hist_dir / f"{history_prefix}{payload['as_of']}.json"
        hist.write_text(_dump(history_snapshot(payload)), encoding="utf-8")
        written.append(hist)

    buy = payload if side == "lower" else read_latest(out_dir, "lower")
    sell = payload if side == "upper" else read_latest(out_dir, "upper")
    page = out_dir / "index.html"
    page.write_text(render_dashboard(buy, sell), encoding="utf-8")
    written.append(page)

    nojekyll = out_dir / ".nojekyll"  # tell GitHub Pages to serve files as they are
    nojekyll.touch()
    written.append(nojekyll)
    return written
