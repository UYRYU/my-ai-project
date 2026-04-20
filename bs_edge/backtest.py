"""Bar-by-bar backtest of the digital-option edge strategy.

Lifecycle of a single market:

1. Walk forward through the Up-side price history.
2. On each timestamp, estimate sigma from the trailing ``window_min``
   minutes of BTC bars, compute ``Phi(d2)``, and compare to the market
   price on both sides.
3. When the larger-edge side exceeds ``edge_threshold``, open a long
   position on that side at ``market + half_spread``.
4. Continue iterating. At each subsequent bar, recompute the model and
   decide whether to exit early:

   - edge collapse: |current_edge| < ``exit_edge_threshold``
   - sign flip: model now disagrees with our side
   - hold-time cap: seconds since entry exceeds ``max_hold_s``
   - approach to expiry: time-to-expiry < ``exit_min_ttm_s``

   Early exit sells at ``market - half_spread``.
5. If none of those fire, the position settles at expiry against the
   outcome provided by the resolver.

The engine takes at most one position per market (the tweet's "find
edge -> enter -> wait -> exit" flow). Follow-on entries after an exit
are deliberately disabled to avoid double-counting autocorrelated signals
within one market.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

import pandas as pd

from .config import Config
from .market_loader import UpDownMarket
from .pricing import quote_edge
from .resolution import BinanceCloseResolver, OutcomeResolver
from .slippage import SlippageModel, build_from_config
from .volatility import estimate_sigma

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    condition_id: str
    slug: str
    side: str  # "UP" or "DOWN"
    entry_ts: int
    exit_ts: int
    close_ts: int
    exit_reason: str  # "settle" | "edge_collapse" | "sign_flip" | "max_hold" | "near_expiry"
    entry_market_price: float
    entry_model_price: float
    entry_edge: float
    exit_model_price: float
    exit_market_price: float
    exit_edge: float
    sigma: float
    spot_at_entry: float
    strike: float
    time_to_expiry_s: int
    stake: float
    contracts: float
    fill_price: float
    exit_price: float
    settle_price: float  # 1.0 if side wins, 0.0 otherwise, NaN if early exit
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
            return pd.DataFrame(columns=list(Trade.__dataclass_fields__.keys()))
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
    resolver: OutcomeResolver | None = None,
    realised_outcome: str | None = None,
    slippage: SlippageModel | None = None,
) -> list[Trade]:
    """Backtest a single market.

    Either ``resolver`` (preferred, composable) or ``realised_outcome``
    (for tests) must produce a verdict. If neither does, we fall back to
    a Binance close on ``btc_bars``.
    """
    if market.reference_price is None:
        logger.debug("skip %s: no reference price", market.slug)
        return []
    if up_price_history.empty:
        logger.debug("skip %s: empty price history", market.slug)
        return []

    outcome = realised_outcome
    if outcome is None and resolver is not None:
        outcome = resolver.resolve(market)
    if outcome is None:
        outcome = BinanceCloseResolver(btc_bars).resolve(market)
    if outcome is None:
        logger.debug("skip %s: cannot determine outcome", market.slug)
        return []

    slip = slippage if slippage is not None else build_from_config(cfg)
    history = up_price_history
    state: Optional[_Position] = None
    trades: list[Trade] = []

    for ts, row in history.iterrows():
        unix_ts = int(ts.timestamp())
        ttm_s = market.close_ts - unix_ts
        if ttm_s < cfg.min_time_to_expiry_s:
            if state is not None:
                trades.append(_close_settle(state, outcome, cfg))
                state = None
            break
        if ttm_s > cfg.max_time_to_expiry_s:
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
            "UP", spot, market.reference_price, ttm_years, sigma,
            market_price=market_up, rate=cfg.risk_free_rate, drift=cfg.drift_override,
        )
        quote_down = quote_edge(
            "DOWN", spot, market.reference_price, ttm_years, sigma,
            market_price=1.0 - market_up, rate=cfg.risk_free_rate, drift=cfg.drift_override,
        )

        if state is None:
            best = max((quote_up, quote_down), key=lambda q: q.edge)
            if best.edge <= cfg.edge_threshold:
                continue
            state = _open(market, best, spot, sigma, ttm_s, unix_ts, cfg, slip)
            continue

        # Already in a position -- check exit conditions.
        current = quote_up if state.side == "UP" else quote_down
        reason = _exit_reason(state, current, unix_ts, ttm_s, cfg)
        if reason is not None:
            trades.append(_close_early(state, current, unix_ts, reason, cfg, slip))
            state = None
            break  # one position per market

    # End of history: either forced settle or no entry at all.
    if state is not None:
        trades.append(_close_settle(state, outcome, cfg))
    return trades


def backtest_many(
    markets: Iterable[UpDownMarket],
    btc_bars: pd.DataFrame,
    price_histories: dict[str, pd.DataFrame],
    cfg: Config,
    sigma_window_min: int,
    sigma_estimator: str,
    resolver: OutcomeResolver | None = None,
    slippage: SlippageModel | None = None,
) -> BacktestResult:
    slip = slippage if slippage is not None else build_from_config(cfg)
    result = BacktestResult()
    for mkt in markets:
        result.considered += 1
        hist = price_histories.get(mkt.condition_id)
        if hist is None or hist.empty:
            result.skipped += 1
            continue
        result.trades.extend(
            backtest_market(
                mkt, btc_bars, hist, cfg,
                sigma_window_min=sigma_window_min,
                sigma_estimator=sigma_estimator,
                resolver=resolver,
                slippage=slip,
            )
        )
    logger.info(
        "backtest done: %d trades from %d markets (%d skipped)",
        len(result.trades), result.considered, result.skipped,
    )
    return result


# ---------------------------------------------------------------------------
# Internal position state
# ---------------------------------------------------------------------------


@dataclass
class _Position:
    market: UpDownMarket
    side: str
    entry_ts: int
    ttm_s_at_entry: int
    entry_market_price: float
    entry_model_price: float
    entry_edge: float
    fill_price: float
    stake: float
    contracts: float
    sigma: float
    spot_at_entry: float
    entry_fee: float


def _open(
    market: UpDownMarket, q, spot: float, sigma: float, ttm_s: int,
    unix_ts: int, cfg: Config, slip: SlippageModel,
) -> _Position:
    stake_estimate = _stake(cfg, q.model_price, q.market_price + cfg.half_spread)
    fill_price = slip.buy_price(q.market_price, stake_estimate, ts=unix_ts)
    stake = _stake(cfg, q.model_price, fill_price)
    contracts = stake / fill_price if fill_price > 0 else 0.0
    entry_fee = contracts * fill_price * (cfg.fee_bps * 1e-4)
    return _Position(
        market=market, side=q.side,
        entry_ts=unix_ts, ttm_s_at_entry=ttm_s,
        entry_market_price=q.market_price,
        entry_model_price=q.model_price,
        entry_edge=q.edge,
        fill_price=fill_price, stake=stake, contracts=contracts,
        sigma=sigma, spot_at_entry=spot, entry_fee=entry_fee,
    )


def _exit_reason(pos: _Position, current, now_ts: int, ttm_s: int, cfg: Config) -> str | None:
    if cfg.max_hold_s is not None and (now_ts - pos.entry_ts) >= cfg.max_hold_s:
        return "max_hold"
    if ttm_s <= cfg.exit_min_ttm_s:
        return "near_expiry"
    if cfg.exit_on_sign_flip and current.edge < 0:
        return "sign_flip"
    if cfg.exit_edge_threshold is not None and abs(current.edge) < cfg.exit_edge_threshold:
        return "edge_collapse"
    return None


def _close_early(
    pos: _Position, current, now_ts: int, reason: str, cfg: Config, slip: SlippageModel,
) -> Trade:
    exit_notional = pos.contracts * current.market_price
    exit_price = slip.sell_price(current.market_price, exit_notional, ts=now_ts)
    exit_fee = pos.contracts * exit_price * (cfg.fee_bps * 1e-4)
    gross = pos.contracts * (exit_price - pos.fill_price)
    return Trade(
        condition_id=pos.market.condition_id, slug=pos.market.slug, side=pos.side,
        entry_ts=pos.entry_ts, exit_ts=now_ts, close_ts=pos.market.close_ts,
        exit_reason=reason,
        entry_market_price=pos.entry_market_price,
        entry_model_price=pos.entry_model_price,
        entry_edge=pos.entry_edge,
        exit_model_price=current.model_price,
        exit_market_price=current.market_price,
        exit_edge=current.edge,
        sigma=pos.sigma, spot_at_entry=pos.spot_at_entry,
        strike=float(pos.market.reference_price) if pos.market.reference_price else float("nan"),
        time_to_expiry_s=pos.ttm_s_at_entry,
        stake=pos.stake, contracts=pos.contracts,
        fill_price=pos.fill_price, exit_price=exit_price,
        settle_price=float("nan"),
        pnl=gross - pos.entry_fee - exit_fee,
        fees=pos.entry_fee + exit_fee,
    )


def _close_settle(pos: _Position, outcome: str, cfg: Config) -> Trade:
    settle = 1.0 if pos.side == outcome else 0.0
    gross = pos.contracts * (settle - pos.fill_price)
    return Trade(
        condition_id=pos.market.condition_id, slug=pos.market.slug, side=pos.side,
        entry_ts=pos.entry_ts, exit_ts=pos.market.close_ts, close_ts=pos.market.close_ts,
        exit_reason="settle",
        entry_market_price=pos.entry_market_price,
        entry_model_price=pos.entry_model_price,
        entry_edge=pos.entry_edge,
        exit_model_price=pos.entry_model_price,  # unchanged at settle
        exit_market_price=settle,
        exit_edge=pos.entry_model_price - settle,
        sigma=pos.sigma, spot_at_entry=pos.spot_at_entry,
        strike=float(pos.market.reference_price) if pos.market.reference_price else float("nan"),
        time_to_expiry_s=pos.ttm_s_at_entry,
        stake=pos.stake, contracts=pos.contracts,
        fill_price=pos.fill_price, exit_price=settle,
        settle_price=settle,
        pnl=gross - pos.entry_fee,
        fees=pos.entry_fee,
    )


def _stake(cfg: Config, model_price: float, market_price: float) -> float:
    if cfg.stake_mode == "flat":
        return cfg.flat_stake
    p = model_price
    q = 1.0 - p
    if market_price <= 0 or market_price >= 1:
        return 0.0
    b = (1.0 - market_price) / market_price
    f_star = (p * b - q) / b
    f = max(0.0, min(cfg.kelly_cap, cfg.kelly_fraction * f_star))
    return cfg.flat_stake * f if math.isfinite(f) else 0.0
