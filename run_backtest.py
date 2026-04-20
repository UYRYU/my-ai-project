"""Entry point: run the Polymarket BTC Up/Down BS-edge backtest.

Example::

    python run_backtest.py --since 2025-10-01 --until 2025-11-01 \
        --edge-threshold 0.05 --train-days 30 --test-days 7 \
        --output out/trades.parquet

If Polymarket / Binance can be reached, data is pulled and cached under
``bs_edge/cache``. Subsequent runs read from cache and run fully offline.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bs_edge.backtest import backtest_many
from bs_edge.binance_client import BinanceClient
from bs_edge.config import load_config
from bs_edge.market_loader import load_up_down_markets
from bs_edge.metrics import summarise
from bs_edge.polymarket_client import PolymarketClient
from bs_edge.resolution import (
    BinanceCloseResolver,
    ChainedResolver,
    PolymarketNativeResolver,
)
from bs_edge.walkforward import walk_forward

logger = logging.getLogger("run_backtest")


def _parse_date(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", required=True, help="ISO date, inclusive lower bound")
    p.add_argument("--until", required=True, help="ISO date, exclusive upper bound")
    p.add_argument("--config", default=None, help="Optional JSON/YAML config file")
    p.add_argument("--edge-threshold", type=float, default=None)
    p.add_argument("--train-days", type=int, default=None)
    p.add_argument("--test-days", type=int, default=None)
    p.add_argument("--walk-forward", action="store_true")
    p.add_argument("--output", type=Path, default=Path("out/trades.parquet"))
    p.add_argument("--summary", type=Path, default=Path("out/summary.json"))
    args = p.parse_args()

    overrides: dict = {}
    if args.edge_threshold is not None:
        overrides["edge_threshold"] = args.edge_threshold
    if args.train_days is not None:
        overrides["train_days"] = args.train_days
    if args.test_days is not None:
        overrides["test_days"] = args.test_days
    cfg = load_config(args.config, **overrides)

    since_ts = _parse_date(args.since)
    until_ts = _parse_date(args.until)

    poly = PolymarketClient(
        cache_dir=cfg.cache_dir,
        gamma_url=cfg.polymarket_base_url,
        data_url=cfg.polymarket_data_url,
        clob_url=cfg.polymarket_clob_url,
        timeout_s=cfg.http_timeout_s,
        max_retries=cfg.http_max_retries,
    )
    binance = BinanceClient(
        cache_dir=cfg.cache_dir,
        symbol=cfg.binance_symbol,
        timeframe=cfg.binance_timeframe,
        timeout_s=cfg.http_timeout_s,
        max_retries=cfg.http_max_retries,
    )

    logger.info("loading markets %s -> %s", args.since, args.until)
    markets = load_up_down_markets(poly, since_ts=since_ts, until_ts=until_ts)
    if not markets:
        logger.warning("no markets returned; aborting")
        return 1

    # Pull BTC bars covering the longest sigma window BEFORE since_ts.
    max_window_min = max(cfg.sigma_windows_min)
    start_ms = (since_ts - (max_window_min + 120) * 60) * 1000
    end_ms = until_ts * 1000
    logger.info("fetching BTC bars %s -> %s", start_ms, end_ms)
    btc = binance.fetch_ohlcv(start_ms, end_ms)

    # Pull Up-side price history for each market.
    histories: dict[str, pd.DataFrame] = {}
    for m in markets:
        if m.up_token_id is None:
            continue
        try:
            hist = poly.price_history(m.up_token_id, start_ts=m.open_ts, end_ts=m.close_ts)
        except Exception as exc:
            logger.warning("price_history failed for %s: %s", m.slug, exc)
            continue
        histories[m.condition_id] = hist

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)

    resolver = ChainedResolver([
        PolymarketNativeResolver(poly),
        BinanceCloseResolver(btc),
    ])

    if args.walk_forward:
        report = walk_forward(markets, btc, histories, cfg, resolver=resolver)
        trades = report.all_trades
    else:
        window = cfg.sigma_windows_min[len(cfg.sigma_windows_min) // 2]
        estimator = cfg.sigma_estimators[0]
        res = backtest_many(
            markets, btc, histories, cfg,
            sigma_window_min=window, sigma_estimator=estimator,
            resolver=resolver,
        )
        trades = res.to_frame()

    if trades.empty:
        logger.warning("no trades generated")
        return 0

    try:
        trades.to_parquet(args.output)
    except Exception:
        trades.to_csv(args.output.with_suffix(".csv"), index=False)
    summary = summarise(trades)
    import json
    args.summary.write_text(json.dumps(summary.to_dict(), indent=2))
    logger.info("summary: %s", summary.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
