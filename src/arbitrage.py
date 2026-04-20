from dataclasses import dataclass
from .polymarket import Market


@dataclass(frozen=True)
class Opportunity:
    kind: str
    market: Market
    legs: tuple[tuple[str, float], ...]
    edge: float
    note: str


def scan_single_market(market: Market, min_edge: float) -> Opportunity | None:
    """Binary/multi-outcome same-market arb: sum of best asks < 1 - min_edge.

    Buying every outcome at its ask guarantees a $1 payout on exactly one
    winner, so any shortfall below 1.0 is risk-free profit (minus fees).
    """
    asks = [o.best_ask for o in market.outcomes]
    if any(a <= 0 or a >= 1 for a in asks):
        return None
    total_cost = sum(asks)
    edge = 1.0 - total_cost
    if edge < min_edge:
        return None
    return Opportunity(
        kind="same_market_sum_under_one",
        market=market,
        legs=tuple((o.token_id, o.best_ask) for o in market.outcomes),
        edge=edge,
        note=f"asks sum to {total_cost:.4f}, guaranteed edge {edge:.4f}",
    )


def scan_overround(market: Market, min_edge: float) -> Opportunity | None:
    """Inverse case: sum of best bids > 1 + min_edge → sell every outcome short.

    Only useful if you already hold (or can short via No tokens) each side.
    We surface it as information; execution is left to the caller.
    """
    bids = [o.best_bid for o in market.outcomes]
    if any(b <= 0 for b in bids):
        return None
    total = sum(bids)
    edge = total - 1.0
    if edge < min_edge:
        return None
    return Opportunity(
        kind="same_market_sum_over_one",
        market=market,
        legs=tuple((o.token_id, o.best_bid) for o in market.outcomes),
        edge=edge,
        note=f"bids sum to {total:.4f}, sell-all edge {edge:.4f}",
    )


def scan(markets: list[Market], min_edge: float) -> list[Opportunity]:
    out: list[Opportunity] = []
    for m in markets:
        for fn in (scan_single_market, scan_overround):
            opp = fn(m, min_edge)
            if opp is not None:
                out.append(opp)
    return out
