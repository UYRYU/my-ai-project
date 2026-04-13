"""Portfolio & position manager — 資金とポジションの自動最適化.

3つの仕事:
  1. 資金管理: 残高追跡、最大リスク制限、利益の自動再投資
  2. ポジションサイジング: Kelly基準でarb品質に応じた最適ベットサイズ
  3. ポジション追跡: 何をいくら持ってるか、いつ回収できるか
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from polymarket_arbitrage.models.market import ArbitrageOpportunity, ArbitrageType

logger = logging.getLogger(__name__)

STATE_FILE = Path(os.environ.get("STATE_FILE", "bot_state.json"))


# ── Data classes ─────────────────────────────────────────────────────

@dataclass
class Position:
    """An active arb position."""
    id: str
    arb_type: str
    direction: str
    market_ids: list[str]
    market_names: list[str]
    entry_cost: float        # total USD invested
    expected_payout: float   # what we get if arb resolves correctly
    expected_profit: float   # payout - cost
    entry_time: str
    status: str = "open"     # open / closed / expired


@dataclass
class PortfolioState:
    """Full portfolio state — persisted to disk."""
    initial_capital: float = 3145.0      # 50万円 ≈ $3,145
    available_cash: float = 3145.0       # free cash for new trades
    total_invested: float = 0.0          # locked in open positions
    total_realized_pnl: float = 0.0      # closed profits
    positions: list[Position] = field(default_factory=list)
    trade_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    @property
    def total_equity(self) -> float:
        """Cash + invested (at cost)."""
        return self.available_cash + self.total_invested

    @property
    def utilization(self) -> float:
        """% of capital currently deployed."""
        eq = self.total_equity
        return self.total_invested / eq if eq > 0 else 0.0

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "open"]

    @property
    def roi(self) -> float:
        return self.total_realized_pnl / self.initial_capital if self.initial_capital > 0 else 0.0


# ── Persistence ──────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_state(state: PortfolioState) -> None:
    state.updated_at = _now()
    data = {
        "initial_capital": state.initial_capital,
        "available_cash": state.available_cash,
        "total_invested": state.total_invested,
        "total_realized_pnl": state.total_realized_pnl,
        "trade_count": state.trade_count,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "positions": [
            {
                "id": p.id,
                "arb_type": p.arb_type,
                "direction": p.direction,
                "market_ids": p.market_ids,
                "market_names": p.market_names,
                "entry_cost": p.entry_cost,
                "expected_payout": p.expected_payout,
                "expected_profit": p.expected_profit,
                "entry_time": p.entry_time,
                "status": p.status,
            }
            for p in state.positions
        ],
    }
    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_state(initial_capital: float = 3145.0) -> PortfolioState:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        state = PortfolioState(
            initial_capital=data.get("initial_capital", initial_capital),
            available_cash=data.get("available_cash", initial_capital),
            total_invested=data.get("total_invested", 0.0),
            total_realized_pnl=data.get("total_realized_pnl", 0.0),
            trade_count=data.get("trade_count", 0),
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
        )
        for p in data.get("positions", []):
            state.positions.append(Position(**p))
        return state

    state = PortfolioState(
        initial_capital=initial_capital,
        available_cash=initial_capital,
        created_at=_now(),
    )
    save_state(state)
    return state


# ── Kelly criterion for position sizing ──────────────────────────────

def kelly_size(
    bankroll: float,
    win_prob: float,
    win_ratio: float,
    fraction: float = 0.25,
) -> float:
    """Modified Kelly criterion for arb sizing.

    Standard Kelly: f* = (bp - q) / b
      b = net odds (profit / stake)
      p = probability of win
      q = 1 - p

    For arbs, win_prob is very high (0.95-0.99) because the trade is
    structurally guaranteed. The main risk is execution failure,
    liquidity issues, or market resolution edge cases.

    We use fractional Kelly (default 25%) for safety.

    Args:
        bankroll: available cash
        win_prob: probability the arb succeeds (0.90-0.99)
        win_ratio: profit/cost ratio (e.g., 0.05 for 5% arb)
        fraction: Kelly fraction (0.25 = quarter Kelly for safety)
    """
    if win_ratio <= 0 or win_prob <= 0:
        return 0.0

    b = win_ratio
    p = win_prob
    q = 1.0 - p

    kelly_f = (b * p - q) / b
    kelly_f = max(kelly_f, 0.0)  # never negative

    raw_size = bankroll * kelly_f * fraction
    return raw_size


# ── Position sizing engine ───────────────────────────────────────────

# Risk limits
MAX_SINGLE_TRADE_PCT = 0.15    # max 15% of equity in one trade
MAX_UTILIZATION = 0.70         # max 70% of equity deployed
MAX_PER_MARKET = 0.10          # max 10% of equity in one market
MAX_CONCURRENT_POSITIONS = 10  # max 10 open positions


def calculate_position_size(
    state: PortfolioState,
    opp: ArbitrageOpportunity,
) -> Optional[float]:
    """Calculate optimal position size for an opportunity.

    Returns None if the trade should be skipped (risk limits exceeded).
    Returns USD amount to invest.
    """
    equity = state.total_equity

    # --- Gate checks ---

    # 1. Max utilization
    if state.utilization >= MAX_UTILIZATION:
        logger.info("SKIP: utilization %.0f%% >= %.0f%% limit",
                     state.utilization * 100, MAX_UTILIZATION * 100)
        return None

    # 2. Max concurrent positions
    if len(state.open_positions) >= MAX_CONCURRENT_POSITIONS:
        logger.info("SKIP: %d open positions >= %d limit",
                     len(state.open_positions), MAX_CONCURRENT_POSITIONS)
        return None

    # 3. Cash available
    if state.available_cash < 10.0:  # minimum $10
        logger.info("SKIP: cash $%.2f < $10 minimum", state.available_cash)
        return None

    # 4. Duplicate check — already have position in same markets?
    opp_market_ids = {m.id for m in opp.markets}
    for pos in state.open_positions:
        if opp_market_ids & set(pos.market_ids):
            logger.info("SKIP: already have position in overlapping markets")
            return None

    # --- Kelly sizing ---

    margin = opp.net_profit_per_dollar

    # Estimate win probability based on arb type
    if opp.arb_type == ArbitrageType.NEGRISK_INTRA:
        win_prob = 0.97  # NegRisk is structurally guaranteed
    elif opp.arb_type == ArbitrageType.SINGLE_CONDITION:
        win_prob = 0.95  # slightly less certain (execution risk)
    else:
        win_prob = 0.85  # combinatorial has model risk

    # Adjust win probability by market liquidity
    min_liquidity = min((m.liquidity for m in opp.markets), default=0)
    if min_liquidity < 10_000:
        win_prob *= 0.90  # low liquidity penalty
    elif min_liquidity < 50_000:
        win_prob *= 0.95

    kelly = kelly_size(
        bankroll=state.available_cash,
        win_prob=win_prob,
        win_ratio=margin,
        fraction=0.25,  # quarter Kelly
    )

    # --- Apply hard limits ---

    max_by_equity = equity * MAX_SINGLE_TRADE_PCT
    max_by_market = equity * MAX_PER_MARKET
    max_by_cash = state.available_cash * 0.90  # keep 10% reserve
    max_by_utilization = equity * (MAX_UTILIZATION - state.utilization)

    size = min(kelly, max_by_equity, max_by_market, max_by_cash, max_by_utilization)
    size = max(size, 0.0)

    # Minimum trade size
    if size < 10.0:
        logger.info("SKIP: calculated size $%.2f < $10 minimum", size)
        return None

    return round(size, 2)


# ── Trade recording ──────────────────────────────────────────────────

def record_entry(
    state: PortfolioState,
    opp: ArbitrageOpportunity,
    size: float,
) -> Position:
    """Record a new position entry."""
    margin = opp.net_profit_per_dollar
    payout = size * (1 + margin)
    profit = size * margin

    pos = Position(
        id=f"trade_{state.trade_count + 1:04d}",
        arb_type=opp.arb_type.value,
        direction=opp.direction.value,
        market_ids=[m.id for m in opp.markets],
        market_names=[m.question[:50] for m in opp.markets],
        entry_cost=size,
        expected_payout=payout,
        expected_profit=profit,
        entry_time=_now(),
    )

    state.positions.append(pos)
    state.available_cash -= size
    state.total_invested += size
    state.trade_count += 1
    save_state(state)

    logger.info(
        "ENTRY: %s | $%.2f invested | expected profit $%.4f (%.2f%%) | "
        "cash=$%.2f, invested=$%.2f, equity=$%.2f",
        pos.id, size, profit, margin * 100,
        state.available_cash, state.total_invested, state.total_equity,
    )
    return pos


def record_exit(
    state: PortfolioState,
    position_id: str,
    actual_payout: Optional[float] = None,
) -> None:
    """Record a position exit (market resolved)."""
    pos = next((p for p in state.positions if p.id == position_id), None)
    if pos is None:
        logger.warning("Position %s not found", position_id)
        return

    if actual_payout is None:
        actual_payout = pos.expected_payout  # assume arb worked

    actual_profit = actual_payout - pos.entry_cost
    pos.status = "closed"

    state.total_invested -= pos.entry_cost
    state.available_cash += actual_payout
    state.total_realized_pnl += actual_profit
    save_state(state)

    logger.info(
        "EXIT: %s | payout=$%.2f | profit=$%.4f | total PnL=$%.2f | equity=$%.2f",
        pos.id, actual_payout, actual_profit,
        state.total_realized_pnl, state.total_equity,
    )


# ── Dashboard ────────────────────────────────────────────────────────

def print_dashboard(state: PortfolioState) -> str:
    """Print portfolio status dashboard."""
    lines = []
    lines.append("┌─────────────────────────────────────────────┐")
    lines.append("│           PORTFOLIO DASHBOARD                │")
    lines.append("├─────────────────────────────────────────────┤")
    lines.append(f"│  初期資金:     ${state.initial_capital:>10,.2f}               │")
    lines.append(f"│  現在資産:     ${state.total_equity:>10,.2f}  "
                 f"({state.roi*100:>+6.1f}%)     │")
    lines.append(f"│  利用可能:     ${state.available_cash:>10,.2f}               │")
    lines.append(f"│  投資中:       ${state.total_invested:>10,.2f}  "
                 f"({state.utilization*100:>5.1f}%)     │")
    lines.append(f"│  確定損益:     ${state.total_realized_pnl:>10,.2f}               │")
    lines.append(f"│  取引回数:     {state.trade_count:>10d}               │")
    lines.append(f"│  オープン:     {len(state.open_positions):>10d}               │")
    lines.append("├─────────────────────────────────────────────┤")

    if state.open_positions:
        lines.append("│  Open Positions:                            │")
        for pos in state.open_positions:
            lines.append(f"│    {pos.id}: ${pos.entry_cost:.2f} → "
                         f"+${pos.expected_profit:.4f} ({pos.arb_type})│")

    lines.append("└─────────────────────────────────────────────┘")

    text = "\n".join(lines)
    print(text)
    return text
