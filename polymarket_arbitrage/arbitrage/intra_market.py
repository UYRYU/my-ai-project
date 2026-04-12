"""Intra-market arbitrage detection.

Two types of intra-market arbitrage (from the paper):

1. **Single-Condition Arbitrage**
   Each condition has YES and NO tokens.  By design YES + NO = $1.
   When YES + NO < 1  -> LONG arbitrage  (buy both, redeem $1)
   When YES + NO > 1  -> SHORT arbitrage (sell/split for > $1)
   Raw profit per $1 = |YES + NO - 1|

2. **NegRisk Intra-Market Arbitrage**
   A NegRisk event groups N mutually-exclusive conditions so that exactly
   one resolves YES.  Sum of all YES prices should equal $1.
   When sum(YES_i) < 1  -> LONG  (buy all YES tokens, guaranteed one pays $1)
   When sum(YES_i) > 1  -> SHORT (sell YES / buy NO positions)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from polymarket_arbitrage.config import MIN_ARBITRAGE_THRESHOLD, TRADING_FEE_RATE
from polymarket_arbitrage.models.market import (
    ArbitrageDirection,
    ArbitrageOpportunity,
    ArbitrageType,
    Event,
    Market,
)

logger = logging.getLogger(__name__)


def _compute_net_profit(raw_profit: float, direction: ArbitrageDirection) -> float:
    """Apply Polymarket's fee structure.

    Polymarket charges ~2% on *winnings* (not on the invested amount).
    For a long arb buying all outcomes for $C where C < 1:
      gross payout = $1, winnings = 1 - C, fee = 0.02 * (1 - C)
      net profit = (1 - C) - 0.02 * (1 - C) = 0.98 * (1 - C)
    For a short arb selling all outcomes for $C where C > 1:
      gross payout = $C, winnings = C - 1, fee = 0.02 * (C - 1)
      net profit = (C - 1) - 0.02 * (C - 1) = 0.98 * (C - 1)
    """
    return raw_profit * (1 - TRADING_FEE_RATE)


# ------------------------------------------------------------------
# Single-condition arbitrage
# ------------------------------------------------------------------

def detect_single_condition_arbitrage(
    markets: list[Market],
) -> list[ArbitrageOpportunity]:
    """Detect arbitrage within individual binary markets.

    For each market, check if YES + NO deviates from $1.00 beyond the
    threshold.
    """
    opportunities: list[ArbitrageOpportunity] = []

    for market in markets:
        price_sum = market.price_sum
        if price_sum is None:
            continue

        deviation = price_sum - 1.0

        if abs(deviation) < MIN_ARBITRAGE_THRESHOLD:
            continue

        direction = ArbitrageDirection.SHORT if deviation > 0 else ArbitrageDirection.LONG
        raw_profit = abs(deviation)
        net_profit = _compute_net_profit(raw_profit, direction)

        if net_profit <= 0:
            continue

        opp = ArbitrageOpportunity(
            arb_type=ArbitrageType.SINGLE_CONDITION,
            direction=direction,
            events=[],
            markets=[market],
            price_sum=price_sum,
            raw_profit_per_dollar=raw_profit,
            net_profit_per_dollar=net_profit,
            description=(
                f"Single-condition arb on '{market.question}': "
                f"YES={market.yes_price:.4f} + NO={market.no_price:.4f} = "
                f"{price_sum:.4f} (deviation={deviation:+.4f})"
            ),
            timestamp=datetime.now(timezone.utc),
        )
        opportunities.append(opp)

    logger.info(
        "Single-condition scan: %d markets -> %d opportunities",
        len(markets), len(opportunities),
    )
    return opportunities


# ------------------------------------------------------------------
# NegRisk intra-event arbitrage
# ------------------------------------------------------------------

def detect_negrisk_arbitrage(events: list[Event]) -> list[ArbitrageOpportunity]:
    """Detect arbitrage within NegRisk events (multi-condition).

    For NegRisk events, the sum of YES prices across all conditions
    should equal $1.  Any deviation is an arbitrage opportunity.
    """
    opportunities: list[ArbitrageOpportunity] = []

    for event in events:
        if not event.neg_risk:
            continue
        if len(event.markets) < 2:
            continue

        yes_prices = []
        valid = True
        for m in event.markets:
            yp = m.yes_price
            if yp is None:
                valid = False
                break
            yes_prices.append(yp)

        if not valid:
            continue

        price_sum = sum(yes_prices)
        deviation = price_sum - 1.0

        if abs(deviation) < MIN_ARBITRAGE_THRESHOLD:
            continue

        direction = ArbitrageDirection.SHORT if deviation > 0 else ArbitrageDirection.LONG
        raw_profit = abs(deviation)
        net_profit = _compute_net_profit(raw_profit, direction)

        if net_profit <= 0:
            continue

        price_detail = ", ".join(
            f"{m.question[:40]}={m.yes_price:.4f}" for m in event.markets
        )
        opp = ArbitrageOpportunity(
            arb_type=ArbitrageType.NEGRISK_INTRA,
            direction=direction,
            events=[event],
            markets=event.markets,
            price_sum=price_sum,
            raw_profit_per_dollar=raw_profit,
            net_profit_per_dollar=net_profit,
            description=(
                f"NegRisk arb on '{event.title}': "
                f"sum(YES)={price_sum:.4f} across {len(event.markets)} markets "
                f"(deviation={deviation:+.4f}). [{price_detail}]"
            ),
            timestamp=datetime.now(timezone.utc),
        )
        opportunities.append(opp)

    logger.info(
        "NegRisk scan: %d events -> %d opportunities",
        len(events), len(opportunities),
    )
    return opportunities


def detect_all_intra_market(
    events: list[Event],
) -> list[ArbitrageOpportunity]:
    """Run all intra-market arbitrage detectors."""
    all_markets = [m for e in events for m in e.markets]
    results = detect_single_condition_arbitrage(all_markets)
    results.extend(detect_negrisk_arbitrage(events))
    return results
