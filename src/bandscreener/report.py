"""Render the dashboard page and write the output files."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .pipeline import history_snapshot

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_dashboard(payload: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    return env.get_template("dashboard.html.j2").render(payload=payload)


def _dump(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=False, allow_nan=False)


def write_outputs(payload: dict, out_dir: Path, keep_history: bool = True) -> list[Path]:
    """Write index.html and the data files under ``out_dir`` (served by GitHub Pages)."""
    out_dir = Path(out_dir)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    written = []

    page = out_dir / "index.html"
    page.write_text(render_dashboard(payload), encoding="utf-8")
    written.append(page)

    latest = out_dir / "data" / "latest.json"
    latest.write_text(_dump(payload), encoding="utf-8")
    written.append(latest)

    if keep_history:
        hist_dir = out_dir / "data" / "history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        hist = hist_dir / f"{payload['as_of']}.json"
        hist.write_text(_dump(history_snapshot(payload)), encoding="utf-8")
        written.append(hist)

    nojekyll = out_dir / ".nojekyll"  # tell GitHub Pages to serve files as they are
    nojekyll.touch()
    written.append(nojekyll)
    return written
