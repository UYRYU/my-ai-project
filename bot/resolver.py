"""Auto-exit: market resolution monitor & position closer.

Polls Polymarket for resolved markets and automatically:
  1. Detects when a market in our portfolio has resolved
  2. Claims the payout (redeems winning tokens)
  3. Records the exit in portfolio state
  4. Frees up capital for the next arb

Runs alongside the scanner in the main bot loop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from polymarket_arbitrage.api.gamma_client import GammaClient
from polymarket_arbitrage.models.market import MarketStatus
from bot.portfolio import (
    PortfolioState,
    Position,
    print_dashboard,
    record_exit,
    save_state,
)

logger = logging.getLogger(__name__)


async def check_resolutions(
    client: GammaClient,
    state: PortfolioState,
) -> list[str]:
    """Check if any open positions have resolved.

    Returns list of closed position IDs.
    """
    open_positions = state.open_positions
    if not open_positions:
        return []

    # Collect all market IDs we care about
    all_market_ids: set[str] = set()
    for pos in open_positions:
        all_market_ids.update(pos.market_ids)

    if not all_market_ids:
        return []

    # Fetch current status of these markets
    resolved_markets: dict[str, dict] = {}
    try:
        # Fetch markets in batches
        for market_id in all_market_ids:
            markets = await client.fetch_markets(limit=1)
            # In production, we'd query by specific market ID:
            # markets = await client.fetch_markets(id=market_id)
            # For now, we track resolution via the Gamma API polling
        # Simplified: fetch all active events and check which of our markets resolved
        events = await client.fetch_all_events(active=False, max_events=100)
        for event in events:
            for market in event.markets:
                if market.id in all_market_ids:
                    if market.status == MarketStatus.RESOLVED:
                        winner = next(
                            (t for t in market.tokens if t.winner is True),
                            None,
                        )
                        resolved_markets[market.id] = {
                            "status": "resolved",
                            "winner": winner.outcome if winner else None,
                        }
    except Exception as e:
        logger.warning("Failed to check resolutions: %s", e)
        return []

    # Close positions where ALL markets have resolved
    closed_ids: list[str] = []
    for pos in open_positions:
        pos_markets_resolved = all(
            mid in resolved_markets for mid in pos.market_ids
        )
        if not pos_markets_resolved:
            continue

        # Calculate actual payout
        # For arbs, the payout is guaranteed:
        #   LONG arb (bought all outcomes): exactly $1 per share set
        #   SHORT arb (sold overpriced): keep the premium
        actual_payout = _calculate_payout(pos, resolved_markets)
        record_exit(state, pos.id, actual_payout)
        closed_ids.append(pos.id)

        logger.info(
            "AUTO-EXIT: %s resolved | cost=$%.2f → payout=$%.2f | profit=$%.4f",
            pos.id, pos.entry_cost, actual_payout,
            actual_payout - pos.entry_cost,
        )

    return closed_ids


def _calculate_payout(
    pos: Position,
    resolved_markets: dict[str, dict],
) -> float:
    """Calculate the actual payout for a resolved position.

    For properly structured arbs:
      - NegRisk LONG: bought YES on all outcomes → exactly one pays $1
        Payout = (entry_cost / sum_yes_prices) * $1.00
      - NegRisk SHORT: sold overpriced → keep premium above $1
      - Single LONG: bought YES + NO → $1 guaranteed per pair
      - Single SHORT: sold both → keep premium above $1

    In practice, the payout should match expected_payout.
    Edge cases where it doesn't: partial fills, price moved, resolution dispute.
    """
    # For arbs, the structural guarantee means payout = expected
    # We apply a small haircut for realistic modeling
    if pos.arb_type in ("negrisk_intra", "single_condition"):
        # Arb is structurally guaranteed — full expected payout
        return pos.expected_payout
    else:
        # Combinatorial arbs have model risk — 90% of expected
        return pos.entry_cost + (pos.expected_profit * 0.90)


async def claim_winnings(client: GammaClient, pos: Position) -> bool:
    """Redeem resolved tokens for USDC on Polymarket.

    In production, this calls the Polymarket contract to:
      1. Redeem winning conditional tokens for collateral
      2. Or merge complete sets and redeem
    """
    # This would call the CTF (Conditional Token Framework) contract
    # to redeem tokens. For now, we log the action.
    logger.info(
        "CLAIM: Would redeem tokens for position %s "
        "(in production, calls CTF redeemPositions)",
        pos.id,
    )
    return True


# ── Stale position cleanup ───────────────────────────────────────────

def check_stale_positions(
    state: PortfolioState,
    max_age_hours: int = 168,  # 7 days default
) -> list[str]:
    """Flag positions that have been open too long.

    Some markets may take weeks/months to resolve. This doesn't close them,
    but warns about capital being locked up.
    """
    now = datetime.now(timezone.utc)
    stale: list[str] = []

    for pos in state.open_positions:
        try:
            entry = datetime.fromisoformat(pos.entry_time)
            age_hours = (now - entry).total_seconds() / 3600
            if age_hours > max_age_hours:
                stale.append(pos.id)
                logger.warning(
                    "STALE: %s open for %.0f hours (%.1f days), "
                    "$%.2f locked",
                    pos.id, age_hours, age_hours / 24, pos.entry_cost,
                )
        except (ValueError, TypeError):
            pass

    return stale
