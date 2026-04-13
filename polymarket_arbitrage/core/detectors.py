"""Generic constraint-violation detectors.

Each detector takes a list of Instruments (or Relationships) and returns
Opportunities.  They encode the *mathematical* logic only — no domain
knowledge about Polymarket, bookmakers, or DEXes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from .primitives import (
    ConstraintKind,
    Direction,
    Instrument,
    Opportunity,
    Relationship,
    RelationshipKind,
)

logger = logging.getLogger(__name__)


# ── Fee model ────────────────────────────────────────────────────────

FeeFunc = Callable[[float, Direction], float]


def flat_fee(rate: float) -> FeeFunc:
    """Return a fee function that takes a flat % of raw profit."""
    def _fee(raw: float, _dir: Direction) -> float:
        return raw * (1 - rate)
    return _fee


NO_FEE: FeeFunc = lambda raw, _d: raw


# ── 1. Sum-constraint detector (the paper's core insight) ────────────

def detect_sum_constraint(
    instruments: list[Instrument],
    *,
    target: float = 1.0,
    threshold: float = 0.01,
    fee_func: FeeFunc = NO_FEE,
    domain: str = "generic",
) -> list[Opportunity]:
    """Detect violations of a sum constraint on outcome prices.

    Works for:
      - Polymarket: sum(YES_i) should = 1 for NegRisk events
      - Sports betting: sum(1/odds_i) should = 1 for a fair book
      - Binary markets: YES + NO should = 1
      - Any exhaustive/exclusive outcome set

    Args:
        instruments: each Instrument's outcomes are checked.
        target: the expected sum (default 1.0).
        threshold: minimum deviation to flag.
        fee_func: maps (raw_profit, direction) -> net_profit.
        domain: label for the domain.
    """
    opps: list[Opportunity] = []

    for inst in instruments:
        if not inst.outcomes:
            continue

        price_sum = inst.price_sum
        deviation = price_sum - target

        if abs(deviation) < threshold:
            continue

        direction = Direction.SHORT if deviation > 0 else Direction.LONG
        raw = abs(deviation)
        net = fee_func(raw, direction)
        if net <= 0:
            continue

        opps.append(Opportunity(
            domain=domain,
            direction=direction,
            instruments=[inst],
            constraint_violated=inst.constraint,
            price_sum=price_sum,
            raw_profit=raw,
            net_profit=net,
            description=(
                f"[{domain}] {inst.name}: "
                f"sum={price_sum:.4f} (target={target:.2f}, "
                f"deviation={deviation:+.4f})"
            ),
            timestamp=datetime.now(timezone.utc),
        ))

    return opps


# ── 2. Cross-instrument relationship detector ───────────────────────

def detect_relationship_violation(
    relationships: list[Relationship],
    *,
    threshold: float = 0.01,
    fee_func: FeeFunc = NO_FEE,
    domain: str = "generic",
) -> list[Opportunity]:
    """Detect arbitrage from violated cross-instrument relationships.

    Dispatches to specialised logic per RelationshipKind.
    """
    opps: list[Opportunity] = []
    for rel in relationships:
        opps.extend(_check_relationship(rel, threshold, fee_func, domain))
    return opps


def _check_relationship(
    rel: Relationship,
    threshold: float,
    fee_func: FeeFunc,
    domain: str,
) -> list[Opportunity]:
    """Check a single relationship for violations."""
    handler = _RELATIONSHIP_HANDLERS.get(rel.kind)
    if handler is None:
        return []
    return handler(rel, threshold, fee_func, domain)


def _check_complement(
    rel: Relationship, threshold: float,
    fee_func: FeeFunc, domain: str,
) -> list[Opportunity]:
    """Complement: P(A) + P(B) should = 1."""
    pa = rel.instrument_a.outcomes[0].price if rel.instrument_a.outcomes else None
    pb = rel.instrument_b.outcomes[0].price if rel.instrument_b.outcomes else None
    if pa is None or pb is None:
        return []

    s = pa + pb
    dev = s - 1.0
    if abs(dev) < threshold:
        return []

    direction = Direction.SHORT if dev > 0 else Direction.LONG
    raw = abs(dev)
    net = fee_func(raw, direction)
    if net <= 0:
        return []

    return [Opportunity(
        domain=domain, direction=direction,
        instruments=[rel.instrument_a, rel.instrument_b],
        constraint_violated=ConstraintKind.PAIR_EQUALS_ONE,
        price_sum=s, raw_profit=raw, net_profit=net,
        description=(
            f"[{domain}] Complement: {rel.instrument_a.name} ({pa:.4f}) + "
            f"{rel.instrument_b.name} ({pb:.4f}) = {s:.4f}"
        ),
        timestamp=datetime.now(timezone.utc),
    )]


def _check_equivalent(
    rel: Relationship, threshold: float,
    fee_func: FeeFunc, domain: str,
) -> list[Opportunity]:
    """Equivalent instruments on different venues: prices should match."""
    pa = rel.instrument_a.outcomes[0].price if rel.instrument_a.outcomes else None
    pb = rel.instrument_b.outcomes[0].price if rel.instrument_b.outcomes else None
    if pa is None or pb is None:
        return []

    spread = abs(pa - pb)
    if spread < threshold:
        return []

    # Buy cheap, sell expensive
    if pa < pb:
        buy_inst, sell_inst = rel.instrument_a, rel.instrument_b
    else:
        buy_inst, sell_inst = rel.instrument_b, rel.instrument_a

    raw = spread
    net = fee_func(raw, Direction.LONG)
    if net <= 0:
        return []

    return [Opportunity(
        domain=domain, direction=Direction.LONG,
        instruments=[buy_inst, sell_inst],
        constraint_violated=ConstraintKind.CUSTOM,
        price_sum=pa + pb, raw_profit=raw, net_profit=net,
        description=(
            f"[{domain}] Cross-venue: buy {buy_inst.name}@{buy_inst.venue} "
            f"({min(pa,pb):.4f}), sell {sell_inst.name}@{sell_inst.venue} "
            f"({max(pa,pb):.4f}), spread={spread:.4f}"
        ),
        timestamp=datetime.now(timezone.utc),
    )]


def _check_subset(
    rel: Relationship, threshold: float,
    fee_func: FeeFunc, domain: str,
) -> list[Opportunity]:
    """Subset: P(A) <= P(B) when A ⊂ B."""
    if rel.kind == RelationshipKind.SUBSET:
        sub, sup = rel.instrument_a, rel.instrument_b
    else:
        sub, sup = rel.instrument_b, rel.instrument_a

    ps = sub.outcomes[0].price if sub.outcomes else None
    pp = sup.outcomes[0].price if sup.outcomes else None
    if ps is None or pp is None:
        return []

    if ps <= pp + threshold:
        return []

    raw = ps - pp
    net = fee_func(raw, Direction.LONG)
    if net <= 0:
        return []

    return [Opportunity(
        domain=domain, direction=Direction.LONG,
        instruments=[sub, sup],
        constraint_violated=ConstraintKind.CUSTOM,
        price_sum=ps + pp, raw_profit=raw, net_profit=net,
        description=(
            f"[{domain}] Subset violation: {sub.name} ({ps:.4f}) > "
            f"{sup.name} ({pp:.4f})"
        ),
        timestamp=datetime.now(timezone.utc),
    )]


def _check_mutual_exclusion(
    rel: Relationship, threshold: float,
    fee_func: FeeFunc, domain: str,
) -> list[Opportunity]:
    """Mutual exclusion: P(A) + P(B) <= 1."""
    pa = rel.instrument_a.outcomes[0].price if rel.instrument_a.outcomes else None
    pb = rel.instrument_b.outcomes[0].price if rel.instrument_b.outcomes else None
    if pa is None or pb is None:
        return []

    s = pa + pb
    if s <= 1.0 + threshold:
        return []

    raw = s - 1.0
    net = fee_func(raw, Direction.SHORT)
    if net <= 0:
        return []

    return [Opportunity(
        domain=domain, direction=Direction.SHORT,
        instruments=[rel.instrument_a, rel.instrument_b],
        constraint_violated=ConstraintKind.SUM_LESS_EQUAL_ONE,
        price_sum=s, raw_profit=raw, net_profit=net,
        description=(
            f"[{domain}] Mutex violation: {rel.instrument_a.name} ({pa:.4f}) + "
            f"{rel.instrument_b.name} ({pb:.4f}) = {s:.4f} > 1"
        ),
        timestamp=datetime.now(timezone.utc),
    )]


# ── 3. Resolution-vector portfolio scanner ───────────────────────────

def detect_resolution_vector_arb(
    relationships: list[Relationship],
    *,
    threshold: float = 0.01,
    fee_func: FeeFunc = NO_FEE,
    domain: str = "generic",
) -> list[Opportunity]:
    """Scan all 4 two-leg portfolios against resolution vectors.

    For instruments A, B with outcomes priced (a_yes, a_no, b_yes, b_no),
    check all combinations of (buy/sell) x (A_yes/no, B_yes/no) for
    guaranteed profit over every resolution vector.
    """
    opps: list[Opportunity] = []

    for rel in relationships:
        if not rel.resolution_vectors:
            continue
        a = rel.instrument_a
        b = rel.instrument_b
        if len(a.outcomes) < 2 or len(b.outcomes) < 2:
            continue

        prices = {
            (1, 1): a.outcomes[0].price + b.outcomes[0].price,   # buy A_yes + B_yes
            (1, 0): a.outcomes[0].price + b.outcomes[1].price,   # buy A_yes + B_no
            (0, 1): a.outcomes[1].price + b.outcomes[0].price,   # buy A_no  + B_yes
            (0, 0): a.outcomes[1].price + b.outcomes[1].price,   # buy A_no  + B_no
        }

        for (leg_a, leg_b), cost in prices.items():
            # Payout for each resolution vector
            payouts = []
            for v in rel.resolution_vectors:
                pa = 1.0 if v[0] == leg_a else 0.0
                pb = 1.0 if v[1] == leg_b else 0.0
                payouts.append(pa + pb)

            min_payout = min(payouts)
            if min_payout > cost + threshold:
                raw = min_payout - cost
                net = fee_func(raw, Direction.LONG)
                if net > 0:
                    labels = {1: "YES", 0: "NO"}
                    opps.append(Opportunity(
                        domain=domain, direction=Direction.LONG,
                        instruments=[a, b],
                        constraint_violated=ConstraintKind.CUSTOM,
                        price_sum=cost, raw_profit=raw, net_profit=net,
                        description=(
                            f"[{domain}] Res-vector: buy {a.name[:30]}/{labels[leg_a]} + "
                            f"{b.name[:30]}/{labels[leg_b]}, "
                            f"cost={cost:.4f}, min_payout={min_payout}"
                        ),
                        timestamp=datetime.now(timezone.utc),
                    ))

    return opps


# ── Handler dispatch ─────────────────────────────────────────────────

_RELATIONSHIP_HANDLERS = {
    RelationshipKind.COMPLEMENT: _check_complement,
    RelationshipKind.EQUIVALENT: _check_equivalent,
    RelationshipKind.SUBSET: _check_subset,
    RelationshipKind.SUPERSET: _check_subset,
    RelationshipKind.MUTUALLY_EXCLUSIVE: _check_mutual_exclusion,
}
