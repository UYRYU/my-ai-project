"""Trade executor for Polymarket CLOB API.

When the scanner finds an arb, this module:
  1. Asks portfolio manager for optimal position size (Kelly criterion)
  2. Checks risk limits (max utilization, max per trade, etc.)
  3. Places orders via CLOB API (or logs dry run)
  4. Records the position for tracking

Setup:
  pip install py-clob-client
  export POLY_API_KEY=...
  export POLY_API_SECRET=...
  export POLY_PASSPHRASE=...
  export EXECUTION_MODE=live   # or "dry_run"
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from polymarket_arbitrage.models.market import ArbitrageOpportunity, ArbitrageType
from bot.portfolio import (
    PortfolioState,
    calculate_position_size,
    load_state,
    print_dashboard,
    record_entry,
    save_state,
)

logger = logging.getLogger(__name__)

EXECUTION_MODE = os.environ.get("EXECUTION_MODE", "dry_run")  # "dry_run" or "live"

# Portfolio state — loaded once, persisted across restarts
_state: Optional[PortfolioState] = None


def get_state() -> PortfolioState:
    global _state
    if _state is None:
        initial = float(os.environ.get("INITIAL_CAPITAL", "3145"))  # 50万円
        _state = load_state(initial_capital=initial)
    return _state


def _get_clob_client():
    """Lazy-load the Polymarket CLOB client."""
    try:
        from py_clob_client.client import ClobClient
        host = "https://clob.polymarket.com"
        key = os.environ.get("POLY_API_KEY", "")
        chain_id = 137  # Polygon mainnet

        if not key:
            logger.warning("POLY_API_KEY not set, cannot execute trades")
            return None

        client = ClobClient(
            host,
            key=key,
            chain_id=chain_id,
        )
        return client
    except ImportError:
        logger.warning("py-clob-client not installed. Run: pip install py-clob-client")
        return None


async def execute_arb(opp: ArbitrageOpportunity) -> bool:
    """Execute an arbitrage trade with automatic position sizing.

    Flow:
      1. Portfolio manager calculates Kelly-optimal size
      2. Risk limits are checked (max utilization, duplicates, etc.)
      3. Trade is executed (or dry-run logged)
      4. Position is recorded for tracking
    """
    state = get_state()

    # Ask portfolio manager for optimal size
    size = calculate_position_size(state, opp)
    if size is None:
        return False  # risk limits say skip

    if EXECUTION_MODE == "dry_run":
        logger.info(
            "DRY RUN: Would execute %s %s on %d markets, size=$%.2f, "
            "expected profit=$%.4f",
            opp.direction.value.upper(),
            opp.arb_type.value,
            len(opp.markets),
            size,
            size * opp.net_profit_per_dollar,
        )
        # Record position even in dry run for tracking simulation
        record_entry(state, opp, size)
        _log_dry_run(opp, size)
        print_dashboard(state)
        return True

    # LIVE execution
    client = _get_clob_client()
    if client is None:
        logger.error("Cannot execute: CLOB client not available")
        return False

    try:
        if opp.arb_type == ArbitrageType.NEGRISK_INTRA:
            success = await _execute_negrisk(client, opp, size)
        elif opp.arb_type == ArbitrageType.SINGLE_CONDITION:
            success = await _execute_single_condition(client, opp, size)
        else:
            logger.warning("Unsupported arb type for execution: %s", opp.arb_type)
            return False

        if success:
            record_entry(state, opp, size)
            # Auto-merge to immediately reclaim capital (no wait for resolution)
            await _auto_merge(opp, size)
            print_dashboard(state)
        return success
    except Exception as e:
        logger.error("Execution failed: %s", e)
        return False


async def _auto_merge(opp: ArbitrageOpportunity, size: float) -> None:
    """Merge complete set immediately → reclaim capital."""
    try:
        from bot.merger import merge_complete_set
    except ImportError:
        return

    is_negrisk = opp.arb_type == ArbitrageType.NEGRISK_INTRA
    condition_id = opp.markets[0].condition_id
    if not condition_id:
        logger.warning("No condition_id — skipping auto-merge")
        return

    # Amount = number of shares in the complete set (size / price_sum)
    # For NegRisk LONG: size / sum_yes
    # For single LONG: size / (yes + no)
    shares = size / opp.price_sum
    amount_wei = int(shares * 1_000_000)  # USDC 6 decimals

    logger.info("AUTO-MERGE: %.2f shares of %s (negrisk=%s)",
                shares, condition_id[:12] + "...", is_negrisk)
    ok = await merge_complete_set(condition_id, amount_wei, neg_risk=is_negrisk)
    if ok:
        # Immediately mark position as closed (capital returned)
        pos = next((p for p in _state.positions if p.status == "open"
                    and condition_id in p.market_ids[0]), None)
        if pos:
            from bot.portfolio import record_exit
            record_exit(_state, pos.id, actual_payout=size + size * opp.net_profit_per_dollar)
            logger.info("AUTO-MERGE complete: capital recycled")


async def _execute_negrisk(client, opp: ArbitrageOpportunity, size: float) -> bool:
    """Execute NegRisk arb.

    LONG: buy YES on every market in the event.
          Allocate $size across all markets proportionally.
    SHORT: buy NO on every market (or sell YES if available).
    """
    n_markets = len(opp.markets)
    per_market = size / n_markets

    for market in opp.markets:
        yes_token = next((t for t in market.tokens if t.outcome.lower() == "yes"), None)
        no_token = next((t for t in market.tokens if t.outcome.lower() == "no"), None)

        if opp.direction.value == "long" and yes_token:
            token_id = yes_token.token_id
            price = yes_token.price
            side = "BUY"
        elif opp.direction.value == "short" and no_token:
            token_id = no_token.token_id
            price = no_token.price
            side = "BUY"
        else:
            continue

        amount = per_market / price if price > 0 else 0
        logger.info(
            "LIVE ORDER: %s %s %.2f shares @ $%.4f on '%s' (token=%s)",
            side, "YES" if opp.direction.value == "long" else "NO",
            amount, price, market.question[:40], token_id,
        )

        # Place limit order slightly above best ask for immediate fill
        try:
            order = client.create_and_post_order({
                "tokenID": token_id,
                "price": round(price + 0.001, 4),  # 0.1 cent above for fill
                "size": round(amount, 2),
                "side": side,
            })
            logger.info("Order placed: %s", order)
        except Exception as e:
            logger.error("Order failed for %s: %s", market.question[:30], e)
            return False

    return True


async def _execute_single_condition(client, opp: ArbitrageOpportunity, size: float) -> bool:
    """Execute single-condition arb.

    LONG (YES+NO < 1): buy both YES and NO tokens.
    SHORT (YES+NO > 1): more complex, may need to sell/split.
    """
    market = opp.markets[0]
    yes_token = next((t for t in market.tokens if t.outcome.lower() == "yes"), None)
    no_token = next((t for t in market.tokens if t.outcome.lower() == "no"), None)

    if not yes_token or not no_token:
        return False

    if opp.direction.value == "long":
        # Buy both YES and NO → guaranteed $1 payout
        cost = yes_token.price + no_token.price
        shares = size / cost

        for token, label in [(yes_token, "YES"), (no_token, "NO")]:
            logger.info(
                "LIVE ORDER: BUY %s %.2f shares @ $%.4f on '%s'",
                label, shares, token.price, market.question[:40],
            )
            try:
                order = client.create_and_post_order({
                    "tokenID": token.token_id,
                    "price": round(token.price + 0.001, 4),
                    "size": round(shares, 2),
                    "side": "BUY",
                })
                logger.info("Order placed: %s", order)
            except Exception as e:
                logger.error("Order failed: %s", e)
                return False
    else:
        # SHORT: sell both (needs existing position or minting)
        logger.warning("SHORT single-condition requires minting. Skipping auto-execute.")
        return False

    return True


def _log_dry_run(opp: ArbitrageOpportunity, size: float) -> None:
    """Log what would have been executed."""
    profit = size * opp.net_profit_per_dollar
    print(f"  [DRY RUN] {opp.direction.value.upper()} {opp.arb_type.value}")
    print(f"  Size: ${size:.2f} → Expected profit: ${profit:.4f}")
    for m in opp.markets:
        print(f"    {m.question[:50]} YES={m.yes_price:.4f} NO={m.no_price:.4f}")
