import json
import re

from bandscreener.cli import main
from bandscreener.config import load_config
from bandscreener.pipeline import build_payload, history_snapshot
from bandscreener.report import render_dashboard, write_outputs
from bandscreener.sample_data import demo_universe, synthetic_prices

from pathlib import Path

ROOT = Path(__file__).parent.parent


def demo_payload():
    cfg = load_config(ROOT / "config.toml")
    universe = demo_universe()
    prices = synthetic_prices([u["yahoo"] for u in universe])
    return cfg, build_payload(cfg, universe, prices, ["demo warning"])


def test_payload_is_valid_json_and_has_every_status():
    _, payload = demo_payload()
    json.dumps(payload, allow_nan=False)  # raises on NaN/inf
    statuses = payload["counts"]["by_status"]
    assert statuses.get("ok", 0) > 0
    assert payload["counts"]["universe"] == 100
    assert "insufficient_history" in statuses
    assert "stale" in statuses


def test_hits_have_gap_at_or_below_threshold():
    cfg, payload = demo_payload()
    t = cfg.signal.threshold
    for r in payload["rows"]:
        if r["status"] == "ok":
            assert r["week_hit"] == (r["week_dist"] <= t)


def test_history_snapshot_contains_only_hits():
    _, payload = demo_payload()
    snap = history_snapshot(payload)
    hit_tickers = {r["ticker"] for r in payload["rows"] if r["status"] == "ok" and (r["week_hit"] or r["qtd_hit"])}
    assert {h["ticker"] for h in snap["hits"]} == hit_tickers


def test_dashboard_renders_and_embeds_data():
    _, payload = demo_payload()
    html = render_dashboard(payload)
    assert "<title>Lower Band Screener</title>" in html
    assert 'id="payload"' in html
    start = html.index('id="payload">') + len('id="payload">')
    embedded = json.loads(html[start : html.index("</script>", start)])
    assert embedded["as_of"] == payload["as_of"]
    assert len(embedded["rows"]) == len(payload["rows"])


def test_write_outputs_creates_expected_files(tmp_path):
    _, payload = demo_payload()
    write_outputs(payload, tmp_path, keep_history=True)
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "data" / "latest.json").exists()
    assert (tmp_path / "data" / "history" / f"{payload['as_of']}.json").exists()
    assert (tmp_path / ".nojekyll").exists()


def test_cli_demo_run(tmp_path):
    code = main(["run", "--config", str(ROOT / "config.toml"), "--demo", "--out", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "index.html").exists()


def test_no_email_addresses_in_output(tmp_path):
    _, payload = demo_payload()
    write_outputs(payload, tmp_path)
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", f.read_text(encoding="utf-8")), f


def test_low_liquidity_flag_uses_currency_specific_thresholds():
    from dataclasses import replace

    cfg, _ = demo_payload()
    strict = replace(cfg, liq_min_us=1e15, liq_min_au=0.0)  # everything US is thin, nothing ASX is
    universe = demo_universe()
    prices = synthetic_prices([u["yahoo"] for u in universe])
    payload = build_payload(strict, universe, prices, [])
    scored = [r for r in payload["rows"] if r["status"] in ("ok", "negative_band")]
    assert all(r["low_liquidity"] for r in scored if r["market"] == "US")
    assert not any(r["low_liquidity"] for r in scored if r["market"] == "ASX")
