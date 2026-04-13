"""Polymarket arb scanner — continuous polling loop.

50万円 all-in on Polymarket. Scans every INTERVAL seconds for:
  1. NegRisk arbs: sum(YES) deviates from $1 across multi-outcome events
  2. Single-condition arbs: YES + NO deviates from $1
  3. (Optional) Cross-event complement/subset arbs

When an opportunity is found:
  - Log it with full details
  - Send alert (console + optional webhook)
  - If auto_execute=True, place orders via CLOB API
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from polymarket_arbitrage.api.gamma_client import GammaClient
from polymarket_arbitrage.arbitrage.intra_market import (
    detect_single_condition_arbitrage,
    detect_negrisk_arbitrage,
)
from polymarket_arbitrage.config import MIN_ARBITRAGE_THRESHOLD
from polymarket_arbitrage.models.market import ArbitrageOpportunity, Event

logger = logging.getLogger(__name__)

# Bot config — override via env vars
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", "60"))        # seconds
MIN_PROFIT = float(os.environ.get("MIN_PROFIT", "0.015"))         # 1.5% minimum
MIN_VOLUME = float(os.environ.get("MIN_VOLUME", "50000"))         # $50K min liquidity
MAX_EVENTS = int(os.environ.get("MAX_EVENTS", "500"))             # cap per scan
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")                   # Discord/Telegram
LOG_DIR = Path(os.environ.get("LOG_DIR", "bot_logs"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _filter_liquid(events: list[Event]) -> list[Event]:
    """Keep only events with sufficient liquidity."""
    filtered = []
    for event in events:
        liquid_markets = [m for m in event.markets if m.volume >= MIN_VOLUME]
        if liquid_markets:
            event.markets = liquid_markets
            filtered.append(event)
    return filtered


def _format_alert(opp: ArbitrageOpportunity) -> str:
    """Format an opportunity into a human-readable alert."""
    lines = []
    lines.append(f"{'='*50}")
    lines.append(f"ARB FOUND | {_now()}")
    lines.append(f"Type: {opp.arb_type.value} | Direction: {opp.direction.value.upper()}")
    lines.append(f"Net profit: ${opp.net_profit_per_dollar:.4f} per $1")

    if opp.events:
        lines.append(f"Event: {opp.events[0].title}")

    for m in opp.markets:
        lines.append(f"  Market: {m.question[:60]}")
        lines.append(f"    YES={m.yes_price:.4f}  NO={m.no_price:.4f}  "
                      f"Vol=${m.volume:,.0f}")

    lines.append(f"Price sum: {opp.price_sum:.4f}")
    lines.append(f"Description: {opp.description[:100]}")
    lines.append(f"{'='*50}")
    return "\n".join(lines)


async def _send_webhook(text: str) -> None:
    """Send alert to Discord/Telegram webhook."""
    if not WEBHOOK_URL:
        return
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            if "discord" in WEBHOOK_URL:
                await client.post(WEBHOOK_URL, json={"content": f"```\n{text}\n```"})
            else:
                # Generic / Telegram-style
                await client.post(WEBHOOK_URL, json={"text": text})
    except Exception as e:
        logger.warning("Webhook failed: %s", e)


def _log_opportunity(opp: ArbitrageOpportunity) -> None:
    """Append opportunity to JSON log file."""
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"arbs_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"

    record = {
        "timestamp": _now(),
        "type": opp.arb_type.value,
        "direction": opp.direction.value,
        "price_sum": opp.price_sum,
        "raw_profit": opp.raw_profit_per_dollar,
        "net_profit": opp.net_profit_per_dollar,
        "markets": [
            {"id": m.id, "question": m.question, "yes": m.yes_price, "no": m.no_price}
            for m in opp.markets
        ],
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def scan_once(client: GammaClient) -> list[ArbitrageOpportunity]:
    """Run one full scan cycle."""
    # Fetch active events
    events = await client.fetch_all_events(active=True, max_events=MAX_EVENTS)
    events = _filter_liquid(events)

    all_markets = [m for e in events for m in e.markets]

    # Detect arbs
    opps: list[ArbitrageOpportunity] = []
    opps.extend(detect_single_condition_arbitrage(all_markets))
    opps.extend(detect_negrisk_arbitrage(events))

    # Filter by minimum profit
    opps = [o for o in opps if o.net_profit_per_dollar >= MIN_PROFIT]

    return opps


async def run_bot(
    *,
    interval: int = SCAN_INTERVAL,
    auto_execute: bool = False,
    max_cycles: Optional[int] = None,
) -> None:
    """Main bot loop."""
    logger.info("Bot starting | interval=%ds | min_profit=%.2f%% | min_vol=$%s",
                interval, MIN_PROFIT * 100, f"{MIN_VOLUME:,.0f}")

    cycle = 0
    total_found = 0
    seen_ids: set[str] = set()  # avoid duplicate alerts within session

    async with GammaClient() as client:
        while True:
            cycle += 1
            t0 = time.time()

            try:
                opps = await scan_once(client)
            except Exception as e:
                logger.error("Scan failed: %s", e)
                await asyncio.sleep(interval)
                continue

            elapsed = time.time() - t0

            # Filter out already-seen opportunities
            new_opps = []
            for opp in opps:
                opp_id = "|".join(sorted(m.id for m in opp.markets))
                if opp_id not in seen_ids:
                    seen_ids.add(opp_id)
                    new_opps.append(opp)

            if new_opps:
                total_found += len(new_opps)
                for opp in new_opps:
                    alert = _format_alert(opp)
                    print(alert)
                    _log_opportunity(opp)
                    await _send_webhook(alert)

                    if auto_execute:
                        from bot.executor import execute_arb
                        await execute_arb(opp)
            else:
                logger.info(
                    "Cycle %d: %d events scanned, %d opps (0 new) [%.1fs]",
                    cycle, MAX_EVENTS, len(opps), elapsed,
                )

            # Auto-exit: check for resolved markets every 10 cycles
            if cycle % 10 == 0:
                try:
                    from bot.resolver import check_resolutions, check_stale_positions
                    from bot.executor import get_state
                    state = get_state()
                    closed = await check_resolutions(client, state)
                    if closed:
                        logger.info("Auto-closed %d positions: %s", len(closed), closed)
                        await _send_webhook(
                            f"AUTO-EXIT: {len(closed)} positions resolved: {closed}"
                        )
                    stale = check_stale_positions(state)
                    if stale:
                        logger.warning("%d stale positions: %s", len(stale), stale)
                except Exception as e:
                    logger.warning("Resolution check failed: %s", e)

            # Clear seen_ids periodically (every 100 cycles)
            if cycle % 100 == 0:
                seen_ids.clear()

            if max_cycles and cycle >= max_cycles:
                break

            await asyncio.sleep(interval)

    logger.info("Bot stopped after %d cycles, %d total opportunities found", cycle, total_found)
