"""Fee/slippage-aware edge calculation and Kelly sizing.

Polymarket has no trading fees as of writing, but:
- Crossing the spread costs you ~half the bid-ask spread per leg
- Large baskets push into deeper (worse) levels = slippage
- Partial fills require unwind at a loss

This module adjusts the raw edge downward to reflect actual expected
P&L, and sizes positions using fractional Kelly so drawdowns don't
bankrupt you.
"""

from __future__ import annotations

from dataclasses import dataclass
from .orderbook import FillQuote


@dataclass(frozen=True)
class EdgeAssessment:
    raw_edge_usd: float
    fee_adjusted_edge_usd: float
    slippage_estimate_usd: float
    unwind_risk_usd: float
    net_edge_pct: float
    recommend_trade: bool


def assess(
    quotes: list[FillQuote],
    target_payout_usd: float,
    *,
    partial_fill_prob: float = 0.05,
    unwind_loss_on_partial: float = 0.02,
    min_net_edge_pct: float = 0.002,
) -> EdgeAssessment:
    """Compute the realistic edge after fees/slippage/unwind risk.

    - quotes: VWAP quotes for each leg
    - target_payout_usd: winning leg payout target
    - partial_fill_prob: probability any leg fails to fully fill (~5% in practice)
    - unwind_loss_on_partial: avg cost to unwind as % of basket (~2%)
    - min_net_edge_pct: threshold below which we skip
    """
    total_cost = sum(q.avg_price * target_payout_usd for q in quotes)
    raw_edge = target_payout_usd - total_cost

    # Slippage: assume next level is ~0.5% worse, already baked into VWAP
    # but add a small buffer for latency between quote and fill
    slippage = total_cost * 0.002

    # Expected unwind loss: prob × avg cost × basket size
    unwind_risk = partial_fill_prob * unwind_loss_on_partial * total_cost

    fee_adjusted = raw_edge - slippage - unwind_risk
    net_pct = fee_adjusted / target_payout_usd if target_payout_usd > 0 else 0.0

    return EdgeAssessment(
        raw_edge_usd=raw_edge,
        fee_adjusted_edge_usd=fee_adjusted,
        slippage_estimate_usd=slippage,
        unwind_risk_usd=unwind_risk,
        net_edge_pct=net_pct,
        recommend_trade=net_pct >= min_net_edge_pct,
    )


def kelly_size(
    bankroll_usd: float,
    edge_pct: float,
    *,
    fraction: float = 0.25,
    max_pos_pct_of_bankroll: float = 0.10,
) -> float:
    """Fractional Kelly for arb-style bets (near-guaranteed edge).

    Pure Kelly for an arb = edge / 1 (basket returns ~1 always).
    Fractional Kelly (1/4) keeps drawdowns manageable without sacrificing
    too much growth.

    Capped at max_pos_pct_of_bankroll so one basket can never exceed 10%
    of bankroll — protects against edge mis-estimation.
    """
    if bankroll_usd <= 0 or edge_pct <= 0:
        return 0.0
    raw_kelly = fraction * edge_pct
    capped = min(raw_kelly, max_pos_pct_of_bankroll)
    return bankroll_usd * capped
