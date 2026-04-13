"""Options adapter — Put-Call Parity violation detector.

Core insight (same constraint-violation logic as the paper):
  Put-Call Parity states:  C - P = S - K * e^(-rT)
  Or equivalently:         C + K*e^(-rT) = P + S

  When this equality is violated across exchanges or strike prices,
  a risk-free arbitrage exists.  This is the options analogue of
  "sum of outcome prices should equal $1" from prediction markets.

Mapping to core primitives:
  Instrument = one option chain (call + put at same strike/expiry)
  Outcome[0] = call price, Outcome[1] = put price
  Constraint = PARITY (C - P = S - K*e^(-rT))

Detection modes:
  1. Put-Call Parity violation at single strike
  2. Cross-exchange: same option, different prices
  3. Box spread: two put-call parities that should net to a known value
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from polymarket_arbitrage.core.primitives import (
    ConstraintKind,
    Direction,
    Instrument,
    Opportunity,
    Outcome,
    Relationship,
    RelationshipKind,
)
from polymarket_arbitrage.core.detectors import (
    detect_relationship_violation,
    flat_fee,
)

DOMAIN = "options"
# Options trading fee (per contract, simplified as % of premium)
OPTIONS_FEE = flat_fee(0.01)  # 1% commission


def parity_value(
    spot: float, strike: float,
    risk_free_rate: float, time_to_expiry_years: float,
) -> float:
    """Compute the theoretical C - P = S - K*e^(-rT)."""
    return spot - strike * math.exp(-risk_free_rate * time_to_expiry_years)


def _build_chain_instrument(
    underlying: str,
    strike: float,
    expiry_label: str,
    call_price: float,
    put_price: float,
    exchange: str = "",
    end_date: datetime | None = None,
) -> Instrument:
    return Instrument(
        id=f"{underlying}_{strike}_{expiry_label}@{exchange}",
        name=f"{underlying} {strike} {expiry_label}",
        outcomes=[
            Outcome(id=f"call_{strike}", label="call", price=call_price, venue=exchange),
            Outcome(id=f"put_{strike}", label="put", price=put_price, venue=exchange),
        ],
        constraint=ConstraintKind.PARITY,
        venue=exchange,
        category="options",
        end_date=end_date,
        metadata={
            "underlying": underlying,
            "strike": strike,
            "expiry": expiry_label,
        },
    )


def detect_parity_violations(
    instruments: list[Instrument],
    spot_prices: dict[str, float],
    risk_free_rate: float = 0.05,
    threshold: float = 0.50,
) -> list[Opportunity]:
    """Detect put-call parity violations.

    C - P should equal S - K*e^(-rT).  Violations → arb.
    """
    opps: list[Opportunity] = []
    now = datetime.now(timezone.utc)

    for inst in instruments:
        underlying = inst.metadata.get("underlying", "")
        strike = inst.metadata.get("strike", 0.0)
        spot = spot_prices.get(underlying, 0.0)
        if not spot or not strike:
            continue

        call_price = next((o.price for o in inst.outcomes if o.label == "call"), None)
        put_price = next((o.price for o in inst.outcomes if o.label == "put"), None)
        if call_price is None or put_price is None:
            continue

        # Time to expiry
        if inst.end_date:
            tte = max((inst.end_date - now).total_seconds() / (365.25 * 86400), 0.001)
        else:
            tte = 0.25  # default 3 months

        theoretical = parity_value(spot, strike, risk_free_rate, tte)
        observed = call_price - put_price
        violation = observed - theoretical

        if abs(violation) < threshold:
            continue

        if violation > 0:
            # Call overpriced relative to put: sell call, buy put + stock
            direction = Direction.SHORT
            desc = (
                f"[options] {inst.name}@{inst.venue}: Call overpriced. "
                f"C-P={observed:.2f}, theoretical={theoretical:.2f}, "
                f"violation={violation:+.2f}"
            )
        else:
            # Put overpriced relative to call: sell put, buy call + short stock
            direction = Direction.LONG
            desc = (
                f"[options] {inst.name}@{inst.venue}: Put overpriced. "
                f"C-P={observed:.2f}, theoretical={theoretical:.2f}, "
                f"violation={violation:+.2f}"
            )

        raw = abs(violation)
        net = raw * 0.99  # 1% fee
        if net <= 0:
            continue

        opps.append(Opportunity(
            domain=DOMAIN, direction=direction,
            instruments=[inst],
            constraint_violated=ConstraintKind.PARITY,
            price_sum=call_price + put_price,
            raw_profit=raw, net_profit=net,
            description=desc,
            timestamp=now,
        ))

    return opps


def detect_cross_exchange(
    instruments: list[Instrument],
    threshold: float = 0.30,
) -> list[Opportunity]:
    """Detect cross-exchange mispricing for the same option."""
    opps: list[Opportunity] = []

    # Group by (underlying, strike, expiry)
    groups: dict[tuple, list[Instrument]] = {}
    for inst in instruments:
        key = (
            inst.metadata.get("underlying"),
            inst.metadata.get("strike"),
            inst.metadata.get("expiry"),
        )
        groups.setdefault(key, []).append(inst)

    for key, group in groups.items():
        if len(group) < 2:
            continue
        for leg in ["call", "put"]:
            prices = []
            for inst in group:
                p = next((o.price for o in inst.outcomes if o.label == leg), None)
                if p is not None:
                    prices.append((p, inst))
            if len(prices) < 2:
                continue

            prices.sort(key=lambda x: x[0])
            cheapest_price, cheapest_inst = prices[0]
            most_expensive_price, most_expensive_inst = prices[-1]

            spread = most_expensive_price - cheapest_price
            if spread < threshold:
                continue

            raw = spread
            net = raw * 0.99
            if net <= 0:
                continue

            opps.append(Opportunity(
                domain=DOMAIN, direction=Direction.LONG,
                instruments=[cheapest_inst, most_expensive_inst],
                constraint_violated=ConstraintKind.CUSTOM,
                price_sum=cheapest_price + most_expensive_price,
                raw_profit=raw, net_profit=net,
                description=(
                    f"[options] Cross-exchange {leg}: buy "
                    f"{cheapest_inst.name}@{cheapest_inst.venue} "
                    f"(${cheapest_price:.2f}), sell "
                    f"{most_expensive_inst.name}@{most_expensive_inst.venue} "
                    f"(${most_expensive_price:.2f}), spread=${spread:.2f}"
                ),
                timestamp=datetime.now(timezone.utc),
            ))

    return opps


def detect_box_spread(
    instruments: list[Instrument],
    risk_free_rate: float = 0.05,
    threshold: float = 0.50,
) -> list[Opportunity]:
    """Detect box-spread arbitrage.

    A box spread combines a bull call spread and bear put spread at
    strikes K1 < K2.  The payoff is always K2 - K1 at expiry.
    Cost should = (K2 - K1) * e^(-rT).  Deviations → arb.
    """
    opps: list[Opportunity] = []
    now = datetime.now(timezone.utc)

    # Group by (underlying, expiry, venue)
    groups: dict[tuple, list[Instrument]] = {}
    for inst in instruments:
        key = (
            inst.metadata.get("underlying"),
            inst.metadata.get("expiry"),
            inst.venue,
        )
        groups.setdefault(key, []).append(inst)

    for (underlying, expiry, venue), group in groups.items():
        if len(group) < 2:
            continue
        # Sort by strike
        group.sort(key=lambda x: x.metadata.get("strike", 0))
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                lo, hi = group[i], group[j]
                k1 = lo.metadata.get("strike", 0)
                k2 = hi.metadata.get("strike", 0)
                if k2 <= k1:
                    continue

                c1 = next((o.price for o in lo.outcomes if o.label == "call"), None)
                p1 = next((o.price for o in lo.outcomes if o.label == "put"), None)
                c2 = next((o.price for o in hi.outcomes if o.label == "call"), None)
                p2 = next((o.price for o in hi.outcomes if o.label == "put"), None)
                if any(v is None for v in [c1, p1, c2, p2]):
                    continue

                if lo.end_date:
                    tte = max((lo.end_date - now).total_seconds() / (365.25 * 86400), 0.001)
                else:
                    tte = 0.25

                # Box spread cost = (C1 - C2) + (P2 - P1)
                box_cost = (c1 - c2) + (p2 - p1)
                fair_value = (k2 - k1) * math.exp(-risk_free_rate * tte)
                deviation = box_cost - fair_value

                if abs(deviation) < threshold:
                    continue

                if deviation > 0:
                    direction = Direction.SHORT  # box overpriced, sell it
                    desc = f"Box overpriced"
                else:
                    direction = Direction.LONG  # box underpriced, buy it
                    desc = f"Box underpriced"

                raw = abs(deviation)
                net = raw * 0.99
                if net <= 0:
                    continue

                opps.append(Opportunity(
                    domain=DOMAIN, direction=direction,
                    instruments=[lo, hi],
                    constraint_violated=ConstraintKind.PARITY,
                    price_sum=box_cost,
                    raw_profit=raw, net_profit=net,
                    description=(
                        f"[options] Box spread {underlying} {k1}/{k2} {expiry}@{venue}: "
                        f"cost=${box_cost:.2f}, fair=${fair_value:.2f}, "
                        f"{desc} by ${abs(deviation):.2f}"
                    ),
                    timestamp=datetime.now(timezone.utc),
                ))

    return opps


def generate_demo_data() -> tuple[list[Instrument], dict[str, float]]:
    """Generate synthetic options data with arb opportunities."""
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=30)
    expiry_label = "Jun2026"

    spot_prices = {"AAPL": 195.0, "TSLA": 250.0, "SPY": 530.0}

    instruments = []

    # AAPL options — parity violation on CBOE
    instruments.append(_build_chain_instrument(
        "AAPL", 195.0, expiry_label,
        call_price=8.50, put_price=7.20,  # C-P=1.30, but S-K*e^(-rT) ≈ 195-194.19=0.81
        exchange="CBOE", end_date=expiry,  # violation ≈ +0.49 → Call overpriced
    ))
    instruments.append(_build_chain_instrument(
        "AAPL", 195.0, expiry_label,
        call_price=8.20, put_price=7.50,  # C-P=0.70, theoretical=0.81 → violation=-0.11 (small)
        exchange="NASDAQ_Options", end_date=expiry,
    ))
    instruments.append(_build_chain_instrument(
        "AAPL", 200.0, expiry_label,
        call_price=5.80, put_price=10.20,  # For box spread with 195 strike
        exchange="CBOE", end_date=expiry,
    ))

    # TSLA options — cross-exchange mispricing
    instruments.append(_build_chain_instrument(
        "TSLA", 250.0, expiry_label,
        call_price=15.00, put_price=14.20,
        exchange="CBOE", end_date=expiry,
    ))
    instruments.append(_build_chain_instrument(
        "TSLA", 250.0, expiry_label,
        call_price=15.80, put_price=13.50,  # call is $0.80 more expensive
        exchange="ISE", end_date=expiry,
    ))
    instruments.append(_build_chain_instrument(
        "TSLA", 260.0, expiry_label,
        call_price=10.50, put_price=19.80,
        exchange="CBOE", end_date=expiry,
    ))

    # SPY options — relatively efficient (small violations)
    instruments.append(_build_chain_instrument(
        "SPY", 530.0, expiry_label,
        call_price=12.00, put_price=9.80,
        exchange="CBOE", end_date=expiry,
    ))
    instruments.append(_build_chain_instrument(
        "SPY", 535.0, expiry_label,
        call_price=9.50, put_price=12.30,
        exchange="CBOE", end_date=expiry,
    ))

    return instruments, spot_prices


def detect(
    instruments: list[Instrument],
    spot_prices: dict[str, float],
    risk_free_rate: float = 0.05,
) -> list[Opportunity]:
    """Run all options arbitrage detectors."""
    opps = detect_parity_violations(
        instruments, spot_prices, risk_free_rate,
    )
    opps.extend(detect_cross_exchange(instruments))
    opps.extend(detect_box_spread(instruments, risk_free_rate))
    return opps
