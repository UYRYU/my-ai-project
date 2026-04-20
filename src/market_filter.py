"""Filter out markets that aren't worth scanning.

Most "arbs" the naive scanner surfaces are false positives: wide bid-ask
spreads on illiquid markets, near-resolution markets where one side is
drying up, or markets where the mid price is stale. Filtering these out
is the single biggest quality win before going live.
"""

from __future__ import annotations

from datetime import datetime, timezone
from .polymarket import Market


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_tradeable(
    market: Market,
    *,
    max_spread: float = 0.05,
    min_hours_to_close: float = 0.25,
    max_hours_to_close: float = 72.0,
) -> tuple[bool, str]:
    """Return (ok, reason). Reason is empty on ok."""
    if not market.outcomes:
        return False, "no outcomes"

    # Wide spread → snapshot is noise, real price undefined
    for o in market.outcomes:
        if o.best_ask <= 0 or o.best_bid <= 0:
            return False, f"zero quote on {o.label}"
        if o.best_ask - o.best_bid > max_spread:
            return False, f"spread {o.best_ask - o.best_bid:.3f} > {max_spread}"

    # Degenerate probabilities — pending resolution, one side collapsed
    for o in market.outcomes:
        if o.best_ask < 0.02 or o.best_ask > 0.98:
            return False, f"{o.label} ask {o.best_ask:.3f} at boundary"

    end = _parse_iso(market.end_date)
    if end is not None:
        hours_left = (end - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_left < min_hours_to_close:
            return False, f"closes in {hours_left:.2f}h"
        if hours_left > max_hours_to_close:
            return False, f"closes in {hours_left:.0f}h (too far out)"

    return True, ""


def filter_tradeable(markets: list[Market], **kwargs) -> tuple[list[Market], dict[str, int]]:
    keep: list[Market] = []
    rejected: dict[str, int] = {}
    for m in markets:
        ok, reason = is_tradeable(m, **kwargs)
        if ok:
            keep.append(m)
        else:
            key = reason.split()[0] if reason else "unknown"
            rejected[key] = rejected.get(key, 0) + 1
    return keep, rejected
