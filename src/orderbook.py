"""Depth-aware arb evaluation.

Gamma's snapshot prices lie about executable cost. Real arb requires the
CLOB orderbook: walk the ask side to compute the average fill price for
the size you actually want to buy.
"""

from dataclasses import dataclass
from typing import Any
from . import polymarket


@dataclass(frozen=True)
class FillQuote:
    token_id: str
    avg_price: float
    filled_size: float
    levels_used: int
    limit_price: float | None = None


def average_fill_cost(
    book: dict[str, Any], side: str, target_size: float
) -> FillQuote | None:
    levels = book.get(side) or []
    if not levels or target_size <= 0:
        return None
    remaining = target_size
    cost = 0.0
    used = 0
    limit_price = 0.0
    for lvl in levels:
        try:
            price = float(lvl["price"])
            size = float(lvl["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if size <= 0:
            continue
        take = min(remaining, size)
        cost += take * price
        remaining -= take
        used += 1
        limit_price = price
        if remaining <= 1e-9:
            break
    if remaining > 1e-9:
        return None
    token_id = str(book.get("asset_id") or book.get("token_id") or "")
    return FillQuote(
        token_id=token_id,
        avg_price=cost / target_size,
        filled_size=target_size,
        levels_used=used,
        limit_price=limit_price,
    )


def quote_basket_cost(
    clob_host: str, leg_token_ids: list[str], target_payout_usd: float
) -> tuple[float, list[FillQuote]] | None:
    """Compute the executable cost of buying the same share count on all legs."""
    quotes: list[FillQuote] = []
    total_cost = 0.0
    for token_id in leg_token_ids:
        book = polymarket.fetch_orderbook(clob_host, token_id)
        q = average_fill_cost(book, "asks", target_payout_usd)
        if q is None:
            return None
        quotes.append(q)
        total_cost += q.avg_price * target_payout_usd
    return total_cost, quotes
