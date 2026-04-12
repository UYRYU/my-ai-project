"""Combinatorial (inter-market) arbitrage detection.

Combinatorial arbitrage spans multiple related markets.  When two markets A and
B have a logical dependency (e.g. A ⊂ B: "A implies B"), then an arbitrage
exists if the prices violate that dependency.

Key insight from the paper: resolution vectors define the set of logically
possible joint outcomes.  If we can construct a portfolio across the resolution
vectors that guarantees profit regardless of which vector materialises, that
portfolio is an arbitrage.

Examples:
- If A ⊂ B (A's YES implies B's YES), then P(A_YES) <= P(B_YES) must hold.
  If P(A_YES) > P(B_YES), buy B_YES and sell A_YES for guaranteed profit.
- If A and B are complements, P(A_YES) + P(B_YES) = 1.  Deviations are
  arbitrage, similar to intra-market but across different events.
- If A and B are mutually exclusive, P(A_YES) + P(B_YES) <= 1.  If the sum
  exceeds 1, sell both YES tokens.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from polymarket_arbitrage.config import MIN_ARBITRAGE_THRESHOLD, TRADING_FEE_RATE
from polymarket_arbitrage.models.market import (
    ArbitrageDirection,
    ArbitrageOpportunity,
    ArbitrageType,
    MarketRelationship,
)

logger = logging.getLogger(__name__)


def _net_profit(raw: float) -> float:
    return raw * (1 - TRADING_FEE_RATE)


def detect_subset_arbitrage(
    rel: MarketRelationship,
) -> list[ArbitrageOpportunity]:
    """Detect arbitrage from subset/superset relationships.

    If A ⊂ B  (A implies B), then P(A_YES) <= P(B_YES).
    Violation: P(A_YES) > P(B_YES)
      -> Buy B_YES at P(B), Sell A_YES at P(A)
      -> If A=YES (so B=YES): pay out A (+$1-P(A)), receive B (+$1-P(B)), net neutral
      -> If A=NO, B=YES: lose A_NO cost, gain B_YES payout
      -> If A=NO, B=NO: both NO tokens pay out

    Simplified profit: P(A_YES) - P(B_YES) (before fees)
    """
    results: list[ArbitrageOpportunity] = []

    # Determine which is subset, which is superset
    if rel.relationship_type == "subset":
        sub_market = rel.market_a  # A ⊂ B
        sup_market = rel.market_b
    elif rel.relationship_type == "superset":
        sub_market = rel.market_b
        sup_market = rel.market_a
    else:
        return results

    sub_yes = sub_market.yes_price
    sup_yes = sup_market.yes_price
    if sub_yes is None or sup_yes is None:
        return results

    # Violation: subset price > superset price
    if sub_yes > sup_yes + MIN_ARBITRAGE_THRESHOLD:
        raw_profit = sub_yes - sup_yes
        net = _net_profit(raw_profit)
        if net > 0:
            results.append(ArbitrageOpportunity(
                arb_type=ArbitrageType.COMBINATORIAL,
                direction=ArbitrageDirection.LONG,
                events=[],
                markets=[sub_market, sup_market],
                price_sum=sub_yes + sup_yes,
                raw_profit_per_dollar=raw_profit,
                net_profit_per_dollar=net,
                description=(
                    f"Subset arb: '{sub_market.question[:50]}' (YES={sub_yes:.4f}) "
                    f"⊂ '{sup_market.question[:50]}' (YES={sup_yes:.4f}). "
                    f"Sub price > Sup price by {raw_profit:.4f}"
                ),
                timestamp=datetime.now(timezone.utc),
            ))
    return results


def detect_complement_arbitrage(
    rel: MarketRelationship,
) -> list[ArbitrageOpportunity]:
    """Detect arbitrage from complement relationships.

    If A and B are complements, P(A_YES) + P(B_YES) = 1.
    This is equivalent to intra-market arbitrage but across two events.
    """
    results: list[ArbitrageOpportunity] = []

    a_yes = rel.market_a.yes_price
    b_yes = rel.market_b.yes_price
    if a_yes is None or b_yes is None:
        return results

    price_sum = a_yes + b_yes
    deviation = price_sum - 1.0

    if abs(deviation) < MIN_ARBITRAGE_THRESHOLD:
        return results

    direction = ArbitrageDirection.SHORT if deviation > 0 else ArbitrageDirection.LONG
    raw_profit = abs(deviation)
    net = _net_profit(raw_profit)
    if net <= 0:
        return results

    results.append(ArbitrageOpportunity(
        arb_type=ArbitrageType.COMBINATORIAL,
        direction=direction,
        events=[],
        markets=[rel.market_a, rel.market_b],
        price_sum=price_sum,
        raw_profit_per_dollar=raw_profit,
        net_profit_per_dollar=net,
        description=(
            f"Complement arb: '{rel.market_a.question[:50]}' (YES={a_yes:.4f}) + "
            f"'{rel.market_b.question[:50]}' (YES={b_yes:.4f}) = {price_sum:.4f} "
            f"(should be 1.0, deviation={deviation:+.4f})"
        ),
        timestamp=datetime.now(timezone.utc),
    ))
    return results


def detect_mutual_exclusion_arbitrage(
    rel: MarketRelationship,
) -> list[ArbitrageOpportunity]:
    """Detect arbitrage from mutually exclusive relationships.

    If A and B are mutually exclusive, P(A_YES) + P(B_YES) <= 1.
    If the sum exceeds 1, sell both YES tokens for risk-free profit.
    """
    results: list[ArbitrageOpportunity] = []

    a_yes = rel.market_a.yes_price
    b_yes = rel.market_b.yes_price
    if a_yes is None or b_yes is None:
        return results

    price_sum = a_yes + b_yes
    if price_sum <= 1.0 + MIN_ARBITRAGE_THRESHOLD:
        return results

    raw_profit = price_sum - 1.0
    net = _net_profit(raw_profit)
    if net <= 0:
        return results

    results.append(ArbitrageOpportunity(
        arb_type=ArbitrageType.COMBINATORIAL,
        direction=ArbitrageDirection.SHORT,
        events=[],
        markets=[rel.market_a, rel.market_b],
        price_sum=price_sum,
        raw_profit_per_dollar=raw_profit,
        net_profit_per_dollar=net,
        description=(
            f"Mutual exclusion arb: '{rel.market_a.question[:50]}' (YES={a_yes:.4f}) + "
            f"'{rel.market_b.question[:50]}' (YES={b_yes:.4f}) = {price_sum:.4f} "
            f"(should be <=1.0, excess={raw_profit:.4f})"
        ),
        timestamp=datetime.now(timezone.utc),
    ))
    return results


def detect_resolution_vector_arbitrage(
    rel: MarketRelationship,
) -> list[ArbitrageOpportunity]:
    """General arbitrage detection using resolution vectors.

    For any relationship with resolution vectors, check if there exists a
    portfolio (combination of buying/selling YES/NO tokens on each market)
    that guarantees profit across all possible resolution outcomes.

    Given resolution vectors V = {v_1, ..., v_k} where v_i = [a_i, b_i]:
    - For each vector, compute the payout of a candidate portfolio
    - If minimum payout across all vectors > cost, arbitrage exists
    """
    results: list[ArbitrageOpportunity] = []

    if not rel.resolution_vectors:
        return results

    a_yes = rel.market_a.yes_price
    a_no = rel.market_a.no_price
    b_yes = rel.market_b.yes_price
    b_no = rel.market_b.no_price
    if any(p is None for p in [a_yes, a_no, b_yes, b_no]):
        return results

    vectors = rel.resolution_vectors

    # Strategy: buy all YES tokens
    # Cost = a_yes + b_yes
    # Payout for vector [a, b] = a * 1 + b * 1  (each YES pays $1 if true)
    buy_all_cost = a_yes + b_yes
    min_payout = min(sum(v) for v in vectors)
    if min_payout > buy_all_cost + MIN_ARBITRAGE_THRESHOLD:
        raw = min_payout - buy_all_cost
        net = _net_profit(raw)
        if net > 0:
            results.append(ArbitrageOpportunity(
                arb_type=ArbitrageType.COMBINATORIAL,
                direction=ArbitrageDirection.LONG,
                events=[],
                markets=[rel.market_a, rel.market_b],
                price_sum=buy_all_cost,
                raw_profit_per_dollar=raw,
                net_profit_per_dollar=net,
                description=(
                    f"Resolution vector arb (buy all YES): cost={buy_all_cost:.4f}, "
                    f"min payout={min_payout}, profit={raw:.4f}. "
                    f"Rel: {rel.relationship_type}"
                ),
                timestamp=datetime.now(timezone.utc),
            ))

    # Strategy: buy all NO tokens
    buy_no_cost = a_no + b_no
    min_no_payout = min((1 - v[0]) + (1 - v[1]) for v in vectors)
    if min_no_payout > buy_no_cost + MIN_ARBITRAGE_THRESHOLD:
        raw = min_no_payout - buy_no_cost
        net = _net_profit(raw)
        if net > 0:
            results.append(ArbitrageOpportunity(
                arb_type=ArbitrageType.COMBINATORIAL,
                direction=ArbitrageDirection.LONG,
                events=[],
                markets=[rel.market_a, rel.market_b],
                price_sum=buy_no_cost,
                raw_profit_per_dollar=raw,
                net_profit_per_dollar=net,
                description=(
                    f"Resolution vector arb (buy all NO): cost={buy_no_cost:.4f}, "
                    f"min payout={min_no_payout}, profit={raw:.4f}. "
                    f"Rel: {rel.relationship_type}"
                ),
                timestamp=datetime.now(timezone.utc),
            ))

    # Strategy: buy A_YES + B_NO
    cost_a_yes_b_no = a_yes + b_no
    min_payout_mixed1 = min(v[0] + (1 - v[1]) for v in vectors)
    if min_payout_mixed1 > cost_a_yes_b_no + MIN_ARBITRAGE_THRESHOLD:
        raw = min_payout_mixed1 - cost_a_yes_b_no
        net = _net_profit(raw)
        if net > 0:
            results.append(ArbitrageOpportunity(
                arb_type=ArbitrageType.COMBINATORIAL,
                direction=ArbitrageDirection.LONG,
                events=[],
                markets=[rel.market_a, rel.market_b],
                price_sum=cost_a_yes_b_no,
                raw_profit_per_dollar=raw,
                net_profit_per_dollar=net,
                description=(
                    f"Resolution vector arb (A_YES + B_NO): cost={cost_a_yes_b_no:.4f}, "
                    f"min payout={min_payout_mixed1}, profit={raw:.4f}. "
                    f"Rel: {rel.relationship_type}"
                ),
                timestamp=datetime.now(timezone.utc),
            ))

    # Strategy: buy A_NO + B_YES
    cost_a_no_b_yes = a_no + b_yes
    min_payout_mixed2 = min((1 - v[0]) + v[1] for v in vectors)
    if min_payout_mixed2 > cost_a_no_b_yes + MIN_ARBITRAGE_THRESHOLD:
        raw = min_payout_mixed2 - cost_a_no_b_yes
        net = _net_profit(raw)
        if net > 0:
            results.append(ArbitrageOpportunity(
                arb_type=ArbitrageType.COMBINATORIAL,
                direction=ArbitrageDirection.LONG,
                events=[],
                markets=[rel.market_a, rel.market_b],
                price_sum=cost_a_no_b_yes,
                raw_profit_per_dollar=raw,
                net_profit_per_dollar=net,
                description=(
                    f"Resolution vector arb (A_NO + B_YES): cost={cost_a_no_b_yes:.4f}, "
                    f"min payout={min_payout_mixed2}, profit={raw:.4f}. "
                    f"Rel: {rel.relationship_type}"
                ),
                timestamp=datetime.now(timezone.utc),
            ))

    return results


def detect_combinatorial_arbitrage(
    relationships: list[MarketRelationship],
) -> list[ArbitrageOpportunity]:
    """Run all combinatorial arbitrage detectors on discovered relationships."""
    all_opps: list[ArbitrageOpportunity] = []

    for rel in relationships:
        # Type-specific detectors
        if rel.relationship_type in ("subset", "superset"):
            all_opps.extend(detect_subset_arbitrage(rel))
        elif rel.relationship_type == "complement":
            all_opps.extend(detect_complement_arbitrage(rel))
        elif rel.relationship_type == "mutually_exclusive":
            all_opps.extend(detect_mutual_exclusion_arbitrage(rel))

        # General resolution-vector-based detector (works for all types)
        all_opps.extend(detect_resolution_vector_arbitrage(rel))

    # Deduplicate by market pair
    seen = set()
    unique: list[ArbitrageOpportunity] = []
    for opp in all_opps:
        key = frozenset(m.id for m in opp.markets)
        if key not in seen:
            seen.add(key)
            unique.append(opp)

    logger.info(
        "Combinatorial scan: %d relationships -> %d unique opportunities",
        len(relationships), len(unique),
    )
    return unique
