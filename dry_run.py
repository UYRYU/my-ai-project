"""End-to-end dry run on synthetic data.

Does not hit the network. Fabricates BTC 1m bars, a universe of Up/Down
markets covering several days, and Polymarket-side price histories with
a mix of mispriced and fair markets. Runs all three engines:

1. backtest_many (per-market, single shot)
2. run_portfolio (chronological with risk gates)
3. walk_forward (rolling (train, test) parameter selection)

Prints summary metrics and per-gate rejection counts so we can verify
the whole pipeline is wired correctly.
"""

from __future__ import annotations

import logging
import math
import random

import numpy as np
import pandas as pd

from bs_edge.backtest import backtest_many
from bs_edge.config import Config
from bs_edge.market_loader import UpDownMarket
from bs_edge.metrics import summarise
from bs_edge.portfolio import run_portfolio
from bs_edge.resolution import BinanceCloseResolver
from bs_edge.walkforward import walk_forward

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dry_run")


def make_bars(n_minutes: int, sigma_annual: float = 0.55, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dt = 1.0 / (365 * 24 * 60)
    substeps = 30
    sub_dt = dt / substeps
    opens = np.empty(n_minutes)
    highs = np.empty(n_minutes)
    lows = np.empty(n_minutes)
    closes = np.empty(n_minutes)
    log_p = math.log(65_000.0)
    for i in range(n_minutes):
        opens[i] = math.exp(log_p)
        shocks = rng.standard_normal(substeps) * sigma_annual * math.sqrt(sub_dt)
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
    n_markets: int = 80,
    ttm_minutes: int = 30,
    seed: int = 7,
) -> tuple[list[UpDownMarket], dict[str, pd.DataFrame]]:
    """Create markets every ~2h. Each gets a noisy price history that
    sometimes drifts from the 'fair' probability (to produce edges) and
    sometimes tracks it (no edge).
    """
    rng = random.Random(seed)
    markets: list[UpDownMarket] = []
    histories: dict[str, pd.DataFrame] = {}

    # Space markets across the available BTC window.
    step = (len(bars) - ttm_minutes - 300) // n_markets
    start_idx = 300  # let sigma warm up

    for i in range(n_markets):
        open_idx = start_idx + i * step
        if open_idx + ttm_minutes >= len(bars):
            break
        close_idx = open_idx + ttm_minutes
        strike = float(bars["close"].iloc[open_idx])
        event_id = f"ev-{bars.index[open_idx].date()}"
        cid = f"cid-{i:03d}"
        markets.append(
            UpDownMarket(
                condition_id=cid, market_id=cid, event_id=event_id,
                slug=f"btc-up-or-down-{i}", question=f"BTC Up or Down test {i}",
                up_token_id=f"u{i}", down_token_id=f"d{i}",
                open_ts=int(bars.index[open_idx].timestamp()),
                close_ts=int(bars.index[close_idx].timestamp()),
                reference_price=strike,
            )
        )

        # Generate a noisy price path for the Up side.
        # 1/3: heavily mispriced cheap UP (edge UP), 1/3: expensive (edge DOWN),
        # 1/3: near-fair. Add small noise to stress exit logic.
        regime = rng.choice(["cheap", "rich", "fair"])
        base = {"cheap": 0.10, "rich": 0.90, "fair": 0.50}[regime]
        history_idx = bars.index[open_idx:close_idx]
        noise = np.array([rng.gauss(0, 0.015) for _ in range(len(history_idx))])
        # Drift towards 0.5 late in the life, simulating edge decay.
        decay = np.linspace(0.0, 0.25 if regime != "fair" else 0.0, len(history_idx))
        sign = -1 if regime == "cheap" else (1 if regime == "rich" else 0)
        prices = np.clip(base + sign * decay + noise, 0.01, 0.99)
        histories[cid] = pd.DataFrame({"price": prices}, index=history_idx)

    return markets, histories


def main() -> None:
    # ~7 days of 1m bars.
    bars = make_bars(n_minutes=7 * 24 * 60)
    markets, histories = make_markets_and_histories(bars, n_markets=80)
    log.info("synthetic universe: %d markets, %d BTC bars", len(markets), len(bars))

    cfg = Config(
        sigma_windows_min=(60, 240, 1440),
        sigma_estimators=("close_to_close", "parkinson"),
        edge_threshold=0.05,
        exit_edge_threshold=0.02,
        exit_on_sign_flip=True,
        min_time_to_expiry_s=60,
        exit_min_ttm_s=60,
        max_concurrent_positions=5,
        max_notional_exposure=500.0,
        per_event_notional_cap=200.0,
        daily_loss_limit=-200.0,
        flat_stake=50.0,
        slippage_model="linear",
        half_spread=0.005,
        impact_per_dollar=5e-5,
        train_days=2,
        test_days=1,
    )
    resolver = BinanceCloseResolver(bars)

    # 1) Per-market single-shot
    log.info("=== engine 1: backtest_many (per-market) ===")
    res = backtest_many(
        markets, bars, histories, cfg,
        sigma_window_min=240, sigma_estimator="close_to_close",
        resolver=resolver,
    )
    _dump("per-market", res.to_frame())

    # 2) Portfolio with risk gates
    log.info("=== engine 2: run_portfolio (chronological) ===")
    port = run_portfolio(
        markets, bars, histories, cfg,
        sigma_window_min=240, sigma_estimator="close_to_close",
        resolver=resolver,
    )
    _dump("portfolio", port.to_frame())
    log.info("gate blocks: %s", dict(port.blocked_by_gate))

    # 3) Walk-forward
    log.info("=== engine 3: walk_forward (train=%d / test=%d days) ===",
             cfg.train_days, cfg.test_days)
    wf = walk_forward(markets, bars, histories, cfg, resolver=resolver)
    _dump("walk-forward", wf.all_trades)
    for f in wf.folds:
        log.info(
            "  fold %s window=%d est=%s train_sharpe=%.3f trades=%d",
            pd.to_datetime(f.test_start, unit="s", utc=True).date(),
            f.best_window_min, f.best_estimator, f.train_metric, len(f.trades),
        )


def _dump(tag: str, trades: pd.DataFrame) -> None:
    if trades.empty:
        log.info("[%s] no trades", tag)
        return
    s = summarise(trades)
    log.info(
        "[%s] n=%d win_rate=%.1f%% total_pnl=%.2f avg_edge=%.3f "
        "sharpe=%.2f PF=%.2f brier=%.3f mdd=%.2f",
        tag, s.n_trades, s.win_rate * 100, s.total_pnl, s.avg_edge,
        s.sharpe, s.profit_factor, s.brier, s.max_drawdown,
    )
    if "exit_reason" in trades.columns:
        reasons = trades["exit_reason"].value_counts().to_dict()
        log.info("[%s] exit_reasons: %s", tag, reasons)


if __name__ == "__main__":
    main()
