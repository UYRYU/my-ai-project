"""DeFi adapter — cross-DEX token price arbitrage.

Core insight (same mathematical structure as the paper):
  On a single DEX, buy price + sell price for a pair should be consistent.
  Across DEXes, the same token pair can have different prices → arb.
  Triangular arbitrage: A→B→C→A across three pairs should be neutral.

Mapping to core primitives:
  Instrument = a token pair on one DEX (e.g. ETH/USDC on Uniswap)
  Outcome    = bid/ask prices
  Constraint = PAIR_EQUALS_ONE (bid ≈ 1/ask for inverse pair)
               TRIANGLE (A→B→C→A ≈ 1)

Detection modes:
  1. Cross-DEX: same pair, different prices on different exchanges
  2. Triangular: three pairs forming a cycle
"""

from __future__ import annotations

from datetime import datetime, timezone

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

DOMAIN = "defi"
# DEX swap fee (typical 0.3% per swap)
SWAP_FEE_RATE = 0.003
# For cross-DEX arbs, two swaps (buy + sell)
CROSS_DEX_FEE = flat_fee(SWAP_FEE_RATE * 2)


def _pair_instrument(
    pair: str, dex: str, bid: float, ask: float,
) -> Instrument:
    """Create an instrument for a token pair on a DEX.

    bid = best buy price, ask = best sell price.
    We normalise to store the mid price as outcome[0].
    """
    mid = (bid + ask) / 2
    spread = ask - bid
    return Instrument(
        id=f"{pair}@{dex}",
        name=f"{pair} @ {dex}",
        outcomes=[
            Outcome(id=f"{pair}_{dex}_bid", label="bid", price=bid, venue=dex),
            Outcome(id=f"{pair}_{dex}_ask", label="ask", price=ask, venue=dex),
        ],
        constraint=ConstraintKind.CUSTOM,
        venue=dex,
        category="defi",
        metadata={"pair": pair, "mid": mid, "spread": spread},
    )


def detect_cross_dex_arb(
    instruments: list[Instrument],
    threshold: float = 0.0001,
) -> list[Opportunity]:
    """Detect cross-DEX arbitrage for the same pair.

    If DEX_A's ask < DEX_B's bid for the same pair → buy on A, sell on B.
    """
    opps: list[Opportunity] = []

    # Group by pair
    by_pair: dict[str, list[Instrument]] = {}
    for inst in instruments:
        pair = inst.metadata.get("pair", "")
        by_pair.setdefault(pair, []).append(inst)

    for pair, insts in by_pair.items():
        for i, a in enumerate(insts):
            a_ask = next((o.price for o in a.outcomes if o.label == "ask"), None)
            for j in range(i + 1, len(insts)):
                b = insts[j]
                b_bid = next((o.price for o in b.outcomes if o.label == "bid"), None)
                b_ask = next((o.price for o in b.outcomes if o.label == "ask"), None)
                a_bid = next((o.price for o in a.outcomes if o.label == "bid"), None)

                if a_ask is not None and b_bid is not None and b_bid > a_ask:
                    raw = b_bid - a_ask
                    fee = raw * SWAP_FEE_RATE * 2
                    net = raw - fee
                    if net > threshold:
                        opps.append(Opportunity(
                            domain=DOMAIN, direction=Direction.LONG,
                            instruments=[a, b],
                            constraint_violated=ConstraintKind.CUSTOM,
                            price_sum=a_ask + b_bid,
                            raw_profit=raw, net_profit=net,
                            description=(
                                f"[defi] Cross-DEX {pair}: buy@{a.venue} "
                                f"(ask={a_ask:.6f}), sell@{b.venue} "
                                f"(bid={b_bid:.6f}), spread={raw:.6f}"
                            ),
                            timestamp=datetime.now(timezone.utc),
                        ))

                if b_ask is not None and a_bid is not None and a_bid > b_ask:
                    raw = a_bid - b_ask
                    fee = raw * SWAP_FEE_RATE * 2
                    net = raw - fee
                    if net > threshold:
                        opps.append(Opportunity(
                            domain=DOMAIN, direction=Direction.LONG,
                            instruments=[b, a],
                            constraint_violated=ConstraintKind.CUSTOM,
                            price_sum=b_ask + a_bid,
                            raw_profit=raw, net_profit=net,
                            description=(
                                f"[defi] Cross-DEX {pair}: buy@{b.venue} "
                                f"(ask={b_ask:.6f}), sell@{a.venue} "
                                f"(bid={a_bid:.6f}), spread={raw:.6f}"
                            ),
                            timestamp=datetime.now(timezone.utc),
                        ))

    return opps


def detect_triangular_arb(
    instruments: list[Instrument],
    threshold: float = 0.001,
) -> list[Opportunity]:
    """Detect triangular arbitrage across three token pairs.

    If A/B * B/C * C/A != 1 (within threshold), there's an arb.
    Uses mid prices for simplicity.
    """
    opps: list[Opportunity] = []

    # Build lookup: (base, quote) -> mid_price per DEX
    pair_prices: dict[str, dict[str, float]] = {}  # pair -> {dex -> mid}
    for inst in instruments:
        pair = inst.metadata.get("pair", "")
        mid = inst.metadata.get("mid", 0.0)
        if pair and mid:
            pair_prices.setdefault(pair, {})[inst.venue] = mid

    # Parse pairs into (base, quote) tuples
    parsed: dict[str, tuple[str, str]] = {}
    for pair in pair_prices:
        parts = pair.split("/")
        if len(parts) == 2:
            parsed[pair] = (parts[0], parts[1])

    pair_list = list(parsed.keys())

    # Find triangles: A/B, B/C, C/A
    for i, p1 in enumerate(pair_list):
        b1, q1 = parsed[p1]
        for j, p2 in enumerate(pair_list):
            if j == i:
                continue
            b2, q2 = parsed[p2]
            # p2 must continue from p1: q1 == b2
            if q1 != b2:
                continue
            # Find p3 that closes: q2 -> b1
            target = f"{q2}/{b1}"
            if target in parsed:
                p3 = target
                # Find a common DEX or use any
                for dex in pair_prices.get(p1, {}):
                    mid1 = pair_prices.get(p1, {}).get(dex)
                    mid2 = pair_prices.get(p2, {}).get(dex)
                    mid3 = pair_prices.get(p3, {}).get(dex)
                    if mid1 and mid2 and mid3:
                        # Product should = 1
                        product = mid1 * mid2 * mid3
                        deviation = abs(product - 1.0)
                        if deviation > threshold:
                            raw = deviation
                            fee = raw * SWAP_FEE_RATE * 3
                            net = raw - fee
                            if net > 0:
                                opps.append(Opportunity(
                                    domain=DOMAIN, direction=Direction.LONG,
                                    instruments=[],
                                    constraint_violated=ConstraintKind.TRIANGLE,
                                    price_sum=product,
                                    raw_profit=raw, net_profit=net,
                                    description=(
                                        f"[defi] Triangle@{dex}: "
                                        f"{p1}({mid1:.4f}) × {p2}({mid2:.4f}) × "
                                        f"{p3}({mid3:.4f}) = {product:.6f}"
                                    ),
                                    timestamp=datetime.now(timezone.utc),
                                ))
    return opps


def generate_demo_data() -> list[Instrument]:
    """Generate synthetic DEX price data with arb opportunities."""
    instruments = []

    # ETH/USDC across 3 DEXes — cross-DEX arb exists
    instruments.append(_pair_instrument("ETH/USDC", "Uniswap",  bid=3412.50, ask=3415.20))
    instruments.append(_pair_instrument("ETH/USDC", "SushiSwap", bid=3410.00, ask=3413.80))
    instruments.append(_pair_instrument("ETH/USDC", "Curve",     bid=3416.00, ask=3418.50))
    # Arb: buy on SushiSwap (ask=3413.80), sell on Curve (bid=3416.00) → spread=2.20

    # BTC/USDC — no arb (tight spreads, aligned)
    instruments.append(_pair_instrument("BTC/USDC", "Uniswap",  bid=104250, ask=104320))
    instruments.append(_pair_instrument("BTC/USDC", "SushiSwap", bid=104240, ask=104310))

    # SOL/USDC — cross-DEX arb
    instruments.append(_pair_instrument("SOL/USDC", "Raydium", bid=178.50, ask=179.10))
    instruments.append(_pair_instrument("SOL/USDC", "Orca",    bid=179.80, ask=180.20))
    instruments.append(_pair_instrument("SOL/USDC", "Jupiter", bid=178.80, ask=179.30))
    # Arb: buy on Raydium (ask=179.10), sell on Orca (bid=179.80) → spread=0.70

    # Triangle: ETH/USDC, USDC/DAI, DAI/ETH on Uniswap
    instruments.append(_pair_instrument("USDC/DAI", "Uniswap", bid=0.9998, ask=1.0002))
    instruments.append(_pair_instrument("DAI/ETH",  "Uniswap", bid=0.000291, ask=0.000293))
    # ETH/USDC=3413.85(mid), USDC/DAI=1.0000(mid), DAI/ETH=0.000292(mid)
    # Product: 3413.85 * 1.0000 * 0.000292 = 0.9968 → deviation ~0.003

    return instruments


def detect(instruments: list[Instrument]) -> list[Opportunity]:
    """Run all DeFi arbitrage detectors."""
    opps = detect_cross_dex_arb(instruments)
    opps.extend(detect_triangular_arb(instruments))
    return opps
