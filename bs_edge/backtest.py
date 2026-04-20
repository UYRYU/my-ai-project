"""Bar-by-bar backtest of the digital-option edge strategy.

Given:
  * A Polymarket Up/Down market (``UpDownMarket``)
  * Its price history in probability units (one side; we work the Up side
    and invert for Down)
  * Binance 1m OHLCV covering at least ``[sigma_window, close_ts]``

we iterate forward through the price-history timestamps, estimating sigma
from the most recent ``window_min`` minutes of bars, computing the fair
Phi(d2), and recording any entry where |model - market| >= threshold.

The backtest is single-shot-per-market: on the first edge we enter, hold
until market close, and mark PnL against the binary realised outcome.
This matches the tweet's narrative ("find edge -> enter -> wait -> exit")
and avoids double-counting auto-correlated edges within one market.

No slippage model assumes depth; we use a simple half-spread to cross
and a flat fee bps, both configurable.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

from .config import Config
from .market_loader import UpDownMarket
from .pricing import quote_edge
from .volatility import estimate_sigma

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    condition_id: str
    slug: str
    side: str  # "UP" or "DOWN"
    entry_ts: int
    close_ts: int
    entry_market_price: float
    entry_model_price: float
    entry_edge: float
    sigma: float
    spot_at_entry: float
    strike: float
    time_to_expiry_s: int
    stake: float
    fill_price: float
    settle_price: float  # 1.0 if side wins, 0.0 otherwise
    pnl: float
    fees: float

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    skipped: int = 0
    considered: int = 0

    def to_frame(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(
                columns=list(Trade.__dataclass_fields__.keys())
            )
        return pd.DataFrame([t.to_dict() for t in self.trades])


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------


def backtest_market(
    market: UpDownMarket,
    btc_bars: pd.DataFrame,
    up_price_history: pd.DataFrame,
    cfg: Config,
    sigma_window_min: int,
    sigma_estimator: str,
    realised_outcome: str | None = None,
) -> list[Trade]:
    """Backtest a single market.

    ``up_price_history`` is a DataFrame indexed by UTC timestamp with a
    ``price`` column representing the Up side's market price in [0,1].
    ``realised_outcome`` is "UP" or "DOWN"; if omitted we infer it from
    the first BTC bar at/after ``market.close_ts`` relative to the strike.
    """
    if market.reference_price is None:
        logger.debug("skip %s: no reference price", market.slug)
        return []
    if up_price_history.empty:
        logger.debug("skip %s: empty price history", market.slug)
        return []

    outcome = realised_outcome or _infer_outcome(btc_bars, market.close_ts, market.reference_price)
    if outcome is None:
        logger.debug("skip %s: cannot infer outcome", market.slug)
        return []

    trades: list[Trade] = []
    for ts, row in up_price_history.iterrows():
        unix_ts = int(ts.timestamp())
        ttm_s = market.close_ts - unix_ts
        if ttm_s < cfg.min_time_to_expiry_s or ttm_s > cfg.max_time_to_expiry_s:
            continue
        bars_slice = btc_bars.loc[: ts]
        if len(bars_slice) < sigma_window_min + 2:
            continue
        try:
            sigma = estimate_sigma(
                bars_slice,
                window_min=sigma_window_min,
                estimator=sigma_estimator,
                minutes_per_year=cfg.minutes_per_year,
                sigma_floor=cfg.sigma_floor_annual,
            )
        except ValueError:
            continue

        spot = float(bars_slice["close"].iloc[-1])
        market_up = float(row["price"])
        ttm_years = ttm_s / (cfg.minutes_per_year * 60)

        quote_up = quote_edge(
            "UP",
            spot=spot,
            strike=market.reference_price,
            time_to_expiry=ttm_years,
            sigma=sigma,
            market_price=market_up,
            rate=cfg.risk_free_rate,
            drift=cfg.drift_override,
        )
        # The opposite side's edge is just the sign-flipped complement.
        quote_down = quote_edge(
            "DOWN",
            spot=spot,
            strike=market.reference_price,
            time_to_expiry=ttm_years,
            sigma=sigma,
            market_price=1.0 - market_up,
            rate=cfg.risk_free_rate,
            drift=cfg.drift_override,
        )

        picks = [q for q in (quote_up, quote_down) if q.edge > cfg.edge_threshold]
        if not picks:
            continue
        # Take the side with the largest positive edge. Enter once per market.
        best = max(picks, key=lambda q: q.edge)
        trade = _execute(
            market=market,
            side=best.side,
            entry_ts=unix_ts,
            cfg=cfg,
            model_price=best.model_price,
            market_price=best.market_price,
            edge=best.edge,
            sigma=sigma,
            spot=spot,
            ttm_s=ttm_s,
            outcome=outcome,
        )
        trades.append(trade)
        break  # single shot per market
    return trades


def backtest_many(
    markets: Iterable[UpDownMarket],
    btc_bars: pd.DataFrame,
    price_histories: dict[str, pd.DataFrame],
    cfg: Config,
    sigma_window_min: int,
    sigma_estimator: str,
) -> BacktestResult:
    result = BacktestResult()
    for mkt in markets:
        result.considered += 1
        hist = price_histories.get(mkt.condition_id)
        if hist is None or hist.empty:
            result.skipped += 1
            continue
        result.trades.extend(
            backtest_market(
                mkt,
                btc_bars,
                hist,
                cfg,
                sigma_window_min=sigma_window_min,
                sigma_estimator=sigma_estimator,
            )
        )
    logger.info(
        "backtest done: %d trades from %d markets (%d skipped)",
        len(result.trades),
        result.considered,
        result.skipped,
    )
    return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _infer_outcome(btc_bars: pd.DataFrame, close_ts: int, strike: float) -> str | None:
    ts = pd.Timestamp(close_ts, unit="s", tz="UTC")
    if btc_bars.empty or ts < btc_bars.index[0]:
        return None
    # First bar whose close is at or after market close.
    after = btc_bars.loc[ts:]
    if after.empty:
        return None
    settle = float(after["close"].iloc[0])
    return "UP" if settle > strike else "DOWN"


def _execute(
    market: UpDownMarket,
    side: str,
    entry_ts: int,
    cfg: Config,
    model_price: float,
    market_price: float,
    edge: float,
    sigma: float,
    spot: float,
    ttm_s: int,
    outcome: str,
) -> Trade:
    fill_price = min(1.0, max(0.0, market_price + cfg.half_spread))
    stake = _stake(cfg, model_price, fill_price)
    # Polymarket buys pay out $1 on win; cost is fill_price per share.
    contracts = stake / fill_price if fill_price > 0 else 0.0
    settle = 1.0 if side == outcome else 0.0
    gross = contracts * (settle - fill_price)
    fees = contracts * fill_price * (cfg.fee_bps * 1e-4)
    return Trade(
        condition_id=market.condition_id,
        slug=market.slug,
        side=side,
        entry_ts=entry_ts,
        close_ts=market.close_ts,
        entry_market_price=market_price,
        entry_model_price=model_price,
        entry_edge=edge,
        sigma=sigma,
        spot_at_entry=spot,
        strike=float(market.reference_price) if market.reference_price else float("nan"),
        time_to_expiry_s=ttm_s,
        stake=stake,
        fill_price=fill_price,
        settle_price=settle,
        pnl=gross - fees,
        fees=fees,
    )


def _stake(cfg: Config, model_price: float, market_price: float) -> float:
    if cfg.stake_mode == "flat":
        return cfg.flat_stake
    # Kelly for a binary bet with subjective prob p at fair payout 1/market_price:
    #   f* = (p * b - q) / b  where b = (1 - market_price)/market_price
    p = model_price
    q = 1.0 - p
    if market_price <= 0 or market_price >= 1:
        return 0.0
    b = (1.0 - market_price) / market_price
    f_star = (p * b - q) / b
    f = max(0.0, min(cfg.kelly_cap, cfg.kelly_fraction * f_star))
    return cfg.flat_stake * f if math.isfinite(f) else 0.0
