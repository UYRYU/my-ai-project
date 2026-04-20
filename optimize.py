"""Overnight grid-search optimizer for the BS edge strategy.

Builds a realistic synthetic universe where Polymarket-side prices are
anchored to the true Phi(d2) (computed from the generator's known sigma)
plus a per-market bias and tick-level noise. This gives the optimizer a
genuine mispricing signal to discover, so the search can actually
distinguish parameter settings by profitability rather than by spread
cost.

For each parameter combo we run the portfolio engine on the full
universe, summarise with metrics, and append one row to the results
parquet. Progress is streamed to stdout and a log file so you can peek
in the morning.

Usage:
    python optimize.py              # default: ~200 combos on 14d / 240 markets
    python optimize.py --n-days 7   # smaller for a quick check
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import random
import time
import traceback
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from bs_edge.config import Config
from bs_edge.market_loader import UpDownMarket
from bs_edge.metrics import summarise
from bs_edge.portfolio import run_portfolio
from bs_edge.pricing import digital_call_price
from bs_edge.resolution import BinanceCloseResolver


# ---------------------------------------------------------------------------
# Synthetic universe
# ---------------------------------------------------------------------------


TRUE_SIGMA_ANNUAL = 0.55
MINUTES_PER_YEAR = 365 * 24 * 60


def make_bars(n_minutes: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dt = 1.0 / MINUTES_PER_YEAR
    substeps = 20
    sub_dt = dt / substeps
    opens = np.empty(n_minutes)
    highs = np.empty(n_minutes)
    lows = np.empty(n_minutes)
    closes = np.empty(n_minutes)
    log_p = math.log(65_000.0)
    for i in range(n_minutes):
        opens[i] = math.exp(log_p)
        shocks = rng.standard_normal(substeps) * TRUE_SIGMA_ANNUAL * math.sqrt(sub_dt)
        path = np.cumsum(shocks) + log_p
        highs[i] = math.exp(path.max())
        lows[i] = math.exp(path.min())
        log_p = float(path[-1])
        closes[i] = math.exp(log_p)
    idx = pd.date_range("2026-04-01", periods=n_minutes, freq="1min", tz="UTC")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 0.0},
        index=idx,
    )


def make_markets_and_histories(
    bars: pd.DataFrame,
    *,
    n_markets: int,
    ttm_minutes: int = 30,
    bias_std: float = 0.12,
    tick_noise_std: float = 0.015,
    seed: int = 13,
) -> tuple[list[UpDownMarket], dict[str, pd.DataFrame]]:
    rng = np.random.default_rng(seed)
    markets: list[UpDownMarket] = []
    histories: dict[str, pd.DataFrame] = {}
    warmup = 500
    available = len(bars) - ttm_minutes - warmup
    step = max(1, available // n_markets)

    for i in range(n_markets):
        open_idx = warmup + i * step
        if open_idx + ttm_minutes >= len(bars):
            break
        close_idx = open_idx + ttm_minutes
        strike = float(bars["close"].iloc[open_idx])
        cid = f"cid-{i:04d}"
        event_id = f"ev-{bars.index[open_idx].date()}-{bars.index[open_idx].hour // 2}"

        history_idx = bars.index[open_idx:close_idx]
        bias = float(rng.normal(0.0, bias_std))
        prices = []
        for t_idx in range(len(history_idx)):
            bar_idx = open_idx + t_idx
            ttm_s = (close_idx - bar_idx) * 60
            if ttm_s <= 0:
                prices.append(0.5)
                continue
            spot = float(bars["close"].iloc[bar_idx])
            ttm_years = ttm_s / (MINUTES_PER_YEAR * 60)
            try:
                true_up = digital_call_price(spot, strike, ttm_years, TRUE_SIGMA_ANNUAL)
            except ValueError:
                true_up = 0.5
            noisy = true_up + bias + float(rng.normal(0.0, tick_noise_std))
            prices.append(float(np.clip(noisy, 0.02, 0.98)))

        histories[cid] = pd.DataFrame({"price": prices}, index=history_idx)
        markets.append(
            UpDownMarket(
                condition_id=cid, market_id=cid, event_id=event_id,
                slug=f"btc-up-or-down-{i}", question=f"BTC Up or Down {i}",
                up_token_id=f"u{i}", down_token_id=f"d{i}",
                open_ts=int(bars.index[open_idx].timestamp()),
                close_ts=int(bars.index[close_idx].timestamp()),
                reference_price=strike,
            )
        )
    return markets, histories


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------


def build_grid() -> list[dict]:
    sigma_windows = [60, 240, 1440]
    estimators = ["close_to_close", "parkinson", "yang_zhang"]
    edge_thresholds = [0.03, 0.05, 0.08, 0.12]
    exit_thresholds = [None, 0.01, 0.02]
    half_spreads = [0.002, 0.005, 0.01]
    slippage_models = ["constant", "linear"]

    combos = []
    for sw, est, edge, xex, hs, slip in itertools.product(
        sigma_windows, estimators, edge_thresholds, exit_thresholds,
        half_spreads, slippage_models,
    ):
        combos.append({
            "sigma_window_min": sw,
            "sigma_estimator": est,
            "edge_threshold": edge,
            "exit_edge_threshold": xex,
            "half_spread": hs,
            "slippage_model": slip,
        })
    return combos


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_combo(
    combo: dict,
    markets: list[UpDownMarket],
    bars: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    resolver: BinanceCloseResolver,
) -> dict:
    cfg = Config(
        sigma_windows_min=(combo["sigma_window_min"],),
        sigma_estimators=(combo["sigma_estimator"],),
        edge_threshold=combo["edge_threshold"],
        exit_edge_threshold=combo["exit_edge_threshold"],
        exit_on_sign_flip=True,
        min_time_to_expiry_s=60,
        exit_min_ttm_s=60,
        max_concurrent_positions=5,
        max_notional_exposure=1000.0,
        per_event_notional_cap=300.0,
        daily_loss_limit=-500.0,
        flat_stake=50.0,
        slippage_model=combo["slippage_model"],
        half_spread=combo["half_spread"],
        impact_per_dollar=5e-5,
    )
    port = run_portfolio(
        markets, bars, histories, cfg,
        sigma_window_min=combo["sigma_window_min"],
        sigma_estimator=combo["sigma_estimator"],
        resolver=resolver,
    )
    trades = port.to_frame()
    s = summarise(trades)
    row = {**combo, **asdict(s)}
    row["gate_blocks"] = json.dumps(dict(port.blocked_by_gate))
    row["n_markets_with_trade"] = int(trades["condition_id"].nunique()) if not trades.empty else 0
    return row


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n-days", type=int, default=14)
    p.add_argument("--n-markets", type=int, default=240)
    p.add_argument("--bars-seed", type=int, default=42)
    p.add_argument("--markets-seed", type=int, default=13)
    p.add_argument("--output", type=Path, default=Path("out/optimize_results.parquet"))
    p.add_argument("--best-trades", type=Path, default=Path("out/best_trades.parquet"))
    p.add_argument("--log", type=Path, default=Path("out/optimize.log"))
    p.add_argument("--limit", type=int, default=0, help="cap combos (0 = all)")
    args = p.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(args.log, mode="w")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[fh, sh])
    log = logging.getLogger("optimize")

    n_minutes = args.n_days * 24 * 60
    log.info("generating %d minutes of BTC bars", n_minutes)
    t0 = time.time()
    bars = make_bars(n_minutes, seed=args.bars_seed)
    markets, histories = make_markets_and_histories(
        bars, n_markets=args.n_markets, seed=args.markets_seed,
    )
    resolver = BinanceCloseResolver(bars)
    log.info(
        "universe ready in %.1fs: %d markets, %d bars",
        time.time() - t0, len(markets), len(bars),
    )

    grid = build_grid()
    if args.limit > 0:
        grid = grid[: args.limit]
    log.info("grid size: %d combos", len(grid))

    rows = []
    best_sharpe = (-math.inf, None)
    best_pnl = (-math.inf, None)
    best_trades_df: pd.DataFrame | None = None

    start = time.time()
    for i, combo in enumerate(grid, 1):
        t_combo = time.time()
        try:
            row = run_combo(combo, markets, bars, histories, resolver)
        except Exception:
            log.error("combo %d failed: %s\n%s", i, combo, traceback.format_exc())
            continue
        rows.append(row)

        if row["sharpe"] > best_sharpe[0]:
            best_sharpe = (row["sharpe"], combo)
            # Stash the trades frame for the best combo so we can export it.
            # Re-run to capture trades since run_combo drops them; cheaper
            # than keeping every trade frame.
        if row["total_pnl"] > best_pnl[0]:
            best_pnl = (row["total_pnl"], combo)

        elapsed = time.time() - start
        per = elapsed / i
        eta_s = per * (len(grid) - i)
        log.info(
            "[%d/%d] %.2fs combo=%s n=%d PnL=%.1f Sharpe=%.2f WR=%.1f%% | "
            "best_sharpe=%.2f best_pnl=%.1f | ETA %.1fmin",
            i, len(grid), time.time() - t_combo,
            _brief(combo), row["n_trades"], row["total_pnl"], row["sharpe"],
            row["win_rate"] * 100, best_sharpe[0], best_pnl[0], eta_s / 60,
        )

        # Flush partial results every 20 combos so we keep work if killed.
        if i % 20 == 0:
            _save(rows, args.output)

    _save(rows, args.output)

    # Export trades for the best-sharpe combo.
    if best_sharpe[1] is not None:
        log.info("re-running best-sharpe combo to dump trades: %s", best_sharpe[1])
        cfg = _combo_to_cfg(best_sharpe[1])
        port = run_portfolio(
            markets, bars, histories, cfg,
            sigma_window_min=best_sharpe[1]["sigma_window_min"],
            sigma_estimator=best_sharpe[1]["sigma_estimator"],
            resolver=resolver,
        )
        best_trades_df = port.to_frame()
        try:
            best_trades_df.to_parquet(args.best_trades)
        except Exception:
            best_trades_df.to_csv(args.best_trades.with_suffix(".csv"), index=False)

    _print_top(rows, log)
    log.info("DONE in %.1fmin", (time.time() - start) / 60)
    return 0


def _brief(combo: dict) -> str:
    return (
        f"sw={combo['sigma_window_min']} "
        f"est={combo['sigma_estimator'][:3]} "
        f"edge={combo['edge_threshold']:.2f} "
        f"xex={combo['exit_edge_threshold']} "
        f"hs={combo['half_spread']:.3f} "
        f"slip={combo['slippage_model']}"
    )


def _save(rows: list[dict], path: Path) -> None:
    df = pd.DataFrame(rows)
    try:
        df.to_parquet(path, index=False)
    except Exception:
        df.to_csv(path.with_suffix(".csv"), index=False)


def _combo_to_cfg(combo: dict) -> Config:
    return Config(
        sigma_windows_min=(combo["sigma_window_min"],),
        sigma_estimators=(combo["sigma_estimator"],),
        edge_threshold=combo["edge_threshold"],
        exit_edge_threshold=combo["exit_edge_threshold"],
        exit_on_sign_flip=True,
        min_time_to_expiry_s=60,
        exit_min_ttm_s=60,
        max_concurrent_positions=5,
        max_notional_exposure=1000.0,
        per_event_notional_cap=300.0,
        daily_loss_limit=-500.0,
        flat_stake=50.0,
        slippage_model=combo["slippage_model"],
        half_spread=combo["half_spread"],
        impact_per_dollar=5e-5,
    )


def _print_top(rows: list[dict], log: logging.Logger) -> None:
    if not rows:
        log.info("no rows to rank")
        return
    df = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    log.info("=== TOP 10 by Sharpe ===")
    for _, r in df.head(10).iterrows():
        log.info(
            "  Sharpe=%.2f PnL=%.1f n=%d WR=%.1f%% | %s",
            r["sharpe"], r["total_pnl"], r["n_trades"], r["win_rate"] * 100,
            _brief(r.to_dict()),
        )
    log.info("=== TOP 10 by total PnL ===")
    for _, r in df.sort_values("total_pnl", ascending=False).head(10).iterrows():
        log.info(
            "  PnL=%.1f Sharpe=%.2f n=%d WR=%.1f%% | %s",
            r["total_pnl"], r["sharpe"], r["n_trades"], r["win_rate"] * 100,
            _brief(r.to_dict()),
        )


if __name__ == "__main__":
    raise SystemExit(main())
