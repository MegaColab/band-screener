"""Command line entry point: ``python -m bandscreener run``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .pipeline import build_payload
from .report import write_outputs


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)

    if args.demo:
        from .sample_data import demo_universe, synthetic_prices

        universe = demo_universe()
        warnings = ["DEMO MODE: synthetic prices and invented companies. Not real data."]
        asx_meta: dict = {}
        prices = synthetic_prices([u["yahoo"] for u in universe])
        out_dir = Path(args.out) if args.out else cfg.root / "demo_out"
    else:
        from .data import download_prices
        from .universe import load_universe

        universe, warnings, asx_meta = load_universe(cfg)
        print(f"Universe: {len(universe)} stocks", file=sys.stderr)
        prices = download_prices([u["yahoo"] for u in universe], cfg.history_years, cfg.batch_size)
        out_dir = Path(args.out) if args.out else cfg.out_dir

    ratio = len(prices) / len(universe) if universe else 0
    if not args.demo and ratio < cfg.min_success_ratio:
        print(
            f"ABORT: only {len(prices)} of {len(universe)} stocks loaded ({ratio:.0%}); "
            f"need {cfg.min_success_ratio:.0%}. The existing dashboard was left untouched.",
            file=sys.stderr,
        )
        return 2

    payload = build_payload(cfg, universe, prices, warnings, asx_meta)
    written = write_outputs(payload, out_dir, cfg.keep_history)

    counts = payload["counts"]
    print(f"Prices to {payload['as_of']}. Loaded {counts['loaded']} of {counts['universe']}.", file=sys.stderr)
    print(f"Status counts: {counts['by_status']}", file=sys.stderr)
    for path in written:
        print(f"  wrote {path}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bandscreener", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="screen the universe and write the dashboard")
    p_run.add_argument("--config", default="config.toml")
    p_run.add_argument("--out", help="output folder (default: from config; demo mode uses demo_out/)")
    p_run.add_argument("--demo", action="store_true", help="use synthetic data, no network")
    p_run.set_defaults(func=run)
    args = parser.parse_args(argv)
    return args.func(args)
