"""Portfolio-level backtest over many markets with cross-market gates.

The per-market backtester (``backtest.backtest_market``) answers "would
this strategy have entered here?" in isolation. That is fine for signal
research, but ignores capital constraints: two strongly correlated
edges at the same minute are *not* independent, and unbounded
concurrency inflates apparent returns.

``PortfolioBacktester`` replays all markets on a single chronological
timeline and applies four classes of gates before each entry:

1. ``max_concurrent_positions`` -- hard cap on open positions.
2. ``max_notional_exposure`` -- dollar cap on simultaneous stake.
3. ``per_event_notional_cap`` -- dollar cap per Polymarket event (all
   strikes of one "Bitcoin Up or Down - <date>" event combined).
4. ``daily_loss_limit`` -- if cumulative realised PnL for a UTC day
   falls below this, new entries are blocked for the rest of the day.

Exits, sigma estimation, pricing, and slippage reuse the per-market
primitives; this module only adds the orchestration and gating.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from .backtest import (
    Trade,
    _close_early,
    _close_settle,
    _exit_reason,
    _open,
    _Position,
    _stake,
)
from .config import Config
from .market_loader import UpDownMarket
from .pricing import quote_edge
from .resolution import BinanceCloseResolver, OutcomeResolver
from .slippage import SlippageModel, build_from_config
from .volatility import estimate_sigma

logger = logging.getLogger(__name__)


@dataclass
class PortfolioResult:
    trades: list[Trade] = field(default_factory=list)
    considered_markets: int = 0
    blocked_by_gate: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def to_frame(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(columns=list(Trade.__dataclass_fields__.keys()))
        return pd.DataFrame([t.__dict__ for t in self.trades])


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_portfolio(
    markets: Iterable[UpDownMarket],
    btc_bars: pd.DataFrame,
    price_histories: dict[str, pd.DataFrame],
    cfg: Config,
    sigma_window_min: int,
    sigma_estimator: str,
    resolver: OutcomeResolver | None = None,
    slippage: SlippageModel | None = None,
) -> PortfolioResult:
    slip = slippage if slippage is not None else build_from_config(cfg)
    timeline = _build_timeline(markets, price_histories)
    if not timeline:
        return PortfolioResult()

    open_positions: dict[str, _Position] = {}
    per_event_notional: dict[str, float] = defaultdict(float)
    daily_pnl: dict[str, float] = defaultdict(float)
    market_lookup = {m.condition_id: m for m in markets}
    closed_markets: set[str] = set()
    result = PortfolioResult()
    result.considered_markets = len(market_lookup)

    for ts, cid, price_row in timeline:
        market = market_lookup[cid]
        unix_ts = int(ts.timestamp())
        ttm_s = market.close_ts - unix_ts

        # 1) Process exits for the market we're ticking on (and any open
        #    position whose market has closed by now).
        _force_settle_closed(
            open_positions, per_event_notional, daily_pnl, market_lookup, unix_ts,
            closed_markets, result, cfg, resolver, btc_bars,
        )

        if ttm_s < cfg.min_time_to_expiry_s:
            pos = open_positions.pop(cid, None)
            if pos is not None:
                outcome = _resolve_outcome(market, resolver, btc_bars)
                if outcome is not None:
                    trade = _close_settle(pos, outcome, cfg)
                    result.trades.append(trade)
                    per_event_notional[pos.market.event_id or ""] -= pos.stake
                    daily_pnl[_utc_date(unix_ts)] += trade.pnl
            closed_markets.add(cid)
            continue
        if ttm_s > cfg.max_time_to_expiry_s:
            continue

        bars_slice = btc_bars.loc[: ts]
        if len(bars_slice) < sigma_window_min + 2:
            continue
        try:
            sigma = estimate_sigma(
                bars_slice, window_min=sigma_window_min,
                estimator=sigma_estimator,
                minutes_per_year=cfg.minutes_per_year,
                sigma_floor=cfg.sigma_floor_annual,
            )
        except ValueError:
            continue

        spot = float(bars_slice["close"].iloc[-1])
        market_up = float(price_row["price"])
        ttm_years = ttm_s / (cfg.minutes_per_year * 60)

        quote_up = quote_edge(
            "UP", spot, market.reference_price, ttm_years, sigma,
            market_price=market_up, rate=cfg.risk_free_rate, drift=cfg.drift_override,
        )
        quote_down = quote_edge(
            "DOWN", spot, market.reference_price, ttm_years, sigma,
            market_price=1.0 - market_up, rate=cfg.risk_free_rate, drift=cfg.drift_override,
        )

        pos = open_positions.get(cid)
        if pos is not None:
            current = quote_up if pos.side == "UP" else quote_down
            reason = _exit_reason(pos, current, unix_ts, ttm_s, cfg)
            if reason is not None:
                trade = _close_early(pos, current, unix_ts, reason, cfg, slip)
                result.trades.append(trade)
                open_positions.pop(cid, None)
                per_event_notional[pos.market.event_id or ""] -= pos.stake
                daily_pnl[_utc_date(unix_ts)] += trade.pnl
            continue

        if cid in closed_markets:
            continue
        if market.reference_price is None:
            continue

        best = max((quote_up, quote_down), key=lambda q: q.edge)
        if best.edge <= cfg.edge_threshold:
            continue

        # Candidate entry -- consult portfolio gates.
        candidate_stake = _stake(cfg, best.model_price, best.market_price + cfg.half_spread)
        block_reason = _gate_check(
            cfg, candidate_stake, market, open_positions, per_event_notional, daily_pnl, unix_ts,
        )
        if block_reason is not None:
            result.blocked_by_gate[block_reason] += 1
            continue

        new_pos = _open(market, best, spot, sigma, ttm_s, unix_ts, cfg, slip)
        if new_pos.contracts <= 0:
            continue
        open_positions[cid] = new_pos
        per_event_notional[market.event_id or ""] += new_pos.stake

    # Timeline exhausted -- settle anything still open.
    for cid, pos in list(open_positions.items()):
        outcome = _resolve_outcome(pos.market, resolver, btc_bars)
        if outcome is None:
            continue
        trade = _close_settle(pos, outcome, cfg)
        result.trades.append(trade)
        per_event_notional[pos.market.event_id or ""] -= pos.stake
        daily_pnl[_utc_date(pos.market.close_ts)] += trade.pnl
    logger.info(
        "portfolio run: %d trades, gates=%s",
        len(result.trades), dict(result.blocked_by_gate),
    )
    return result


# ---------------------------------------------------------------------------
# Gates and helpers
# ---------------------------------------------------------------------------


def _gate_check(
    cfg: Config,
    candidate_stake: float,
    market: UpDownMarket,
    open_positions: dict[str, _Position],
    per_event_notional: dict[str, float],
    daily_pnl: dict[str, float],
    now_ts: int,
) -> str | None:
    if candidate_stake <= 0:
        return "zero_stake"
    if len(open_positions) >= cfg.max_concurrent_positions:
        return "concurrency"
    current_exposure = sum(p.stake for p in open_positions.values())
    if current_exposure + candidate_stake > cfg.max_notional_exposure:
        return "notional_exposure"
    event_id = market.event_id or ""
    if per_event_notional.get(event_id, 0.0) + candidate_stake > cfg.per_event_notional_cap:
        return "per_event_cap"
    today = _utc_date(now_ts)
    if daily_pnl.get(today, 0.0) <= cfg.daily_loss_limit:
        return "daily_loss_limit"
    return None


def _build_timeline(
    markets: Iterable[UpDownMarket],
    price_histories: dict[str, pd.DataFrame],
) -> list[tuple[pd.Timestamp, str, pd.Series]]:
    timeline: list[tuple[pd.Timestamp, str, pd.Series]] = []
    for m in markets:
        hist = price_histories.get(m.condition_id)
        if hist is None or hist.empty:
            continue
        for ts, row in hist.iterrows():
            timeline.append((ts, m.condition_id, row))
    timeline.sort(key=lambda r: r[0])
    return timeline


def _force_settle_closed(
    open_positions: dict[str, _Position],
    per_event_notional: dict[str, float],
    daily_pnl: dict[str, float],
    market_lookup: dict[str, UpDownMarket],
    now_ts: int,
    closed_markets: set[str],
    result: PortfolioResult,
    cfg: Config,
    resolver: OutcomeResolver | None,
    btc_bars: pd.DataFrame,
) -> None:
    """Settle any open positions whose markets have already closed.

    This matters when the unified timeline has a gap covering one market's
    close -- without this we'd hold a phantom position indefinitely.
    """
    to_settle = [
        cid for cid, pos in open_positions.items()
        if pos.market.close_ts <= now_ts and cid not in closed_markets
    ]
    for cid in to_settle:
        pos = open_positions.pop(cid)
        outcome = _resolve_outcome(pos.market, resolver, btc_bars)
        if outcome is None:
            # Keep exposure zeroed even if we can't mark -- position is gone.
            per_event_notional[pos.market.event_id or ""] -= pos.stake
            closed_markets.add(cid)
            continue
        trade = _close_settle(pos, outcome, cfg)
        result.trades.append(trade)
        per_event_notional[pos.market.event_id or ""] -= pos.stake
        daily_pnl[_utc_date(pos.market.close_ts)] += trade.pnl
        closed_markets.add(cid)


def _resolve_outcome(
    market: UpDownMarket,
    resolver: OutcomeResolver | None,
    btc_bars: pd.DataFrame,
) -> str | None:
    if resolver is not None:
        out = resolver.resolve(market)
        if out is not None:
            return out
    return BinanceCloseResolver(btc_bars).resolve(market)


def _utc_date(unix_ts: int) -> str:
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d")
