"""Command line entry point.

  python -m bandscreener run    weekly Buy screen of the S&P 500 and ASX 200
  python -m bandscreener sell   daily Sell watch of the stocks listed in data/holdings.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .pipeline import build_empty_payload, build_payload, mark_new
from .report import read_previous_snapshot, write_outputs
from .targets import load_targets
from .universe import load_etfs


def _targets(cfg) -> dict:
    return load_targets(cfg.targets_file, cfg.targets_edit_url)


def _finish(cfg, args, universe, prices, warnings, asx_meta, side: str, out_dir: Path) -> int:
    ratio = len(prices) / len(universe) if universe else 0
    if not args.demo and ratio < cfg.min_success_ratio:
        print(
            f"ABORT: only {len(prices)} of {len(universe)} stocks loaded ({ratio:.0%}); "
            f"need {cfg.min_success_ratio:.0%}. The existing dashboard was left untouched.",
            file=sys.stderr,
        )
        return 2

    payload = build_payload(cfg, universe, prices, warnings, asx_meta, side=side, etfs=load_etfs(cfg.etf_file))
    mark_new(payload, read_previous_snapshot(out_dir, side, payload["as_of"]))
    written = write_outputs(payload, out_dir, cfg.keep_history, targets=_targets(cfg))

    counts = payload["counts"]
    print(f"Prices to {payload['as_of']}. Loaded {counts['loaded']} of {counts['universe']}.", file=sys.stderr)
    print(f"Status counts: {counts['by_status']}", file=sys.stderr)
    for path in written:
        print(f"  wrote {path}", file=sys.stderr)
    return 0


def run_buy(args: argparse.Namespace) -> int:
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

    return _finish(cfg, args, universe, prices, warnings, asx_meta, "lower", out_dir)


def run_sell(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)

    if args.demo:
        from .sample_data import demo_holdings, synthetic_prices

        universe = demo_holdings()
        warnings = ["DEMO MODE: synthetic prices and invented companies. Not real data."]
        prices = synthetic_prices([u["yahoo"] for u in universe])
        out_dir = Path(args.out) if args.out else cfg.root / "demo_out"
    else:
        from .data import download_prices
        from .universe import load_holdings

        universe, warnings = load_holdings(cfg.holdings_file)
        out_dir = Path(args.out) if args.out else cfg.out_dir
        if not universe:
            payload = build_empty_payload(cfg, "upper", warnings)
            write_outputs(payload, out_dir, cfg.keep_history, targets=_targets(cfg))
            print("No holdings listed yet; wrote an empty Sell tab.", file=sys.stderr)
            return 0
        print(f"Holdings: {len(universe)} stocks", file=sys.stderr)
        prices = download_prices([u["yahoo"] for u in universe], cfg.history_years, cfg.batch_size)

    return _finish(cfg, args, universe, prices, warnings, {}, "upper", out_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bandscreener", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, help_text in (
        ("run", run_buy, "weekly Buy screen: S&P 500 and ASX 200 near the lower band"),
        ("sell", run_sell, "daily Sell watch: your listed holdings near the upper band"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--config", default="config.toml")
        p.add_argument("--out", help="output folder (default: from config; demo mode uses demo_out/)")
        p.add_argument("--demo", action="store_true", help="use synthetic data, no network")
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)
