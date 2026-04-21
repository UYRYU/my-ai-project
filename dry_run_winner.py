"""Dry run the optimizer's robust winner on unseen synthetic universes.

The iterative optimizer picked parameters on seed 42 (bars) + seed 13
(markets), then cross-validated on seeds 101..105. This script runs the
final winner on three *new* seeds (200/201/202) so we can see how it
behaves on data it has never touched -- the closest synthetic proxy to
'how will it do on next week's Polymarket?'.

Each seed is run through all three engines (per-market, portfolio,
walk-forward) and the combined PnL / Sharpe / WR is reported.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import pandas as pd

from bs_edge.backtest import backtest_many
from bs_edge.metrics import summarise
from bs_edge.portfolio import run_portfolio
from bs_edge.resolution import BinanceCloseResolver
from bs_edge.walkforward import walk_forward

from iterate_optimize import build_cfg
from optimize import make_bars, make_markets_and_histories

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logging.getLogger("bs_edge.portfolio").setLevel(logging.WARNING)
logging.getLogger("bs_edge.backtest").setLevel(logging.WARNING)
logging.getLogger("bs_edge.walkforward").setLevel(logging.WARNING)
log = logging.getLogger("dry_run_winner")


def load_winner() -> dict:
    data = json.loads(Path("out/iterative_best.json").read_text())
    combo = data["robust_best"]["combo"]
    # JSON-NaN survives load as float('nan'); normalise to None.
    if isinstance(combo.get("exit_edge_threshold"), float) and math.isnan(
        combo["exit_edge_threshold"]
    ):
        combo["exit_edge_threshold"] = None
    return combo


def run_universe(seed: int, combo: dict, n_days: int, n_markets: int) -> dict:
    bars = make_bars(n_days * 24 * 60, seed=seed)
    markets, hist = make_markets_and_histories(bars, n_markets=n_markets, seed=seed + 1000)
    resolver = BinanceCloseResolver(bars)
    cfg = build_cfg(combo)

    # 1. per-market
    res = backtest_many(
        markets, bars, hist, cfg,
        sigma_window_min=combo["sigma_window_min"],
        sigma_estimator=combo["sigma_estimator"],
        resolver=resolver,
    )
    s_per = summarise(res.to_frame())

    # 2. portfolio
    port = run_portfolio(
        markets, bars, hist, cfg,
        sigma_window_min=combo["sigma_window_min"],
        sigma_estimator=combo["sigma_estimator"],
        resolver=resolver,
    )
    s_port = summarise(port.to_frame())
    gates = dict(port.blocked_by_gate)

    # 3. walk-forward (with the winner as a single-candidate inner grid)
    cfg_wf = build_cfg(combo)
    wf = walk_forward(markets, bars, hist, cfg_wf, resolver=resolver,
                      train_days=max(2, n_days // 3), test_days=max(1, n_days // 7))
    s_wf = summarise(wf.all_trades)

    return {
        "seed": seed,
        "per_market": s_per.to_dict(),
        "portfolio": s_port.to_dict(),
        "walkforward": s_wf.to_dict(),
        "gates": gates,
    }


def main() -> None:
    combo = load_winner()
    log.info("robust winner: sw=%d est=%s edge=%.2f stake=%s kf=%.2f kc=%.2f",
             combo["sigma_window_min"], combo["sigma_estimator"],
             combo["edge_threshold"], combo["stake_mode"],
             combo["kelly_fraction"], combo["kelly_cap"])

    rows = []
    n_days, n_markets = 14, 240
    for seed in (200, 201, 202):
        log.info("--- seed %d (%dd, %d markets) ---", seed, n_days, n_markets)
        r = run_universe(seed, combo, n_days, n_markets)
        rows.append(r)
        for engine in ("per_market", "portfolio", "walkforward"):
            s = r[engine]
            log.info(
                "  [%-12s] n=%4d  WR=%4.1f%%  PnL=%7.1f  Sharpe=%5.2f  PF=%4.2f  MDD=%7.1f",
                engine, s["n_trades"], s["win_rate"] * 100, s["total_pnl"],
                s["sharpe"], s["profit_factor"], s["max_drawdown"],
            )
        if r["gates"]:
            log.info("  gates blocked: %s", r["gates"])

    # Aggregate across seeds.
    log.info("")
    log.info("=== AGGREGATE across %d seeds ===", len(rows))
    for engine in ("per_market", "portfolio", "walkforward"):
        pnls = [r[engine]["total_pnl"] for r in rows]
        sharpes = [r[engine]["sharpe"] for r in rows]
        wrs = [r[engine]["win_rate"] for r in rows]
        log.info(
            "  [%-12s] mean PnL=%7.1f (std %5.1f)  mean Sharpe=%4.2f  mean WR=%4.1f%%",
            engine, sum(pnls) / len(pnls),
            (sum((p - sum(pnls) / len(pnls)) ** 2 for p in pnls) / (len(pnls) - 1)) ** 0.5,
            sum(sharpes) / len(sharpes), 100 * sum(wrs) / len(wrs),
        )


if __name__ == "__main__":
    main()
