#!/usr/bin/env python3
"""Bot demo — simulates scanning with demo data.

Since we can't hit the live Polymarket API from this environment,
this demonstrates the bot's scanning + alerting logic using synthetic data.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from polymarket_arbitrage.demo import generate_demo_events
from polymarket_arbitrage.arbitrage.intra_market import (
    detect_single_condition_arbitrage,
    detect_negrisk_arbitrage,
)
from polymarket_arbitrage.models.market import ArbitrageOpportunity
from bot.scanner import _format_alert, _log_opportunity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    print("=" * 50)
    print("  Polymarket Arb Bot — DEMO MODE")
    print("=" * 50)
    print("  Simulating 3 scan cycles with demo data\n")

    events = generate_demo_events()
    all_markets = [m for e in events for m in e.markets]

    for cycle in range(1, 4):
        t0 = time.time()
        print(f"\n--- Scan cycle {cycle} ---")

        # Detect
        opps = detect_single_condition_arbitrage(all_markets)
        opps.extend(detect_negrisk_arbitrage(events))

        # Filter profitable
        opps = [o for o in opps if o.net_profit_per_dollar >= 0.015]

        elapsed = time.time() - t0

        if opps:
            print(f"  Found {len(opps)} opportunities ({elapsed*1000:.0f}ms)")
            for opp in opps:
                print(_format_alert(opp))

                # Simulate dry-run execution
                size = 50.0  # $50 per trade
                profit = size * opp.net_profit_per_dollar
                print(f"  [DRY RUN] Size: ${size:.2f} → Profit: ${profit:.4f}")
                print()

                _log_opportunity(opp)
        else:
            print(f"  No opportunities above threshold ({elapsed*1000:.0f}ms)")

        if cycle < 3:
            print("  Waiting 2s for next cycle...")
            time.sleep(2)

    # Show log
    log_dir = Path("bot_logs")
    if log_dir.exists():
        log_files = list(log_dir.glob("*.jsonl"))
        if log_files:
            print(f"\n{'='*50}")
            print(f"  Logged to: {log_files[0]}")
            with open(log_files[0]) as f:
                lines = f.readlines()
            print(f"  {len(lines)} records saved")

    print(f"\n{'='*50}")
    print("  Demo complete. To run against live Polymarket:")
    print("    python -m bot.run")
    print("=" * 50)


if __name__ == "__main__":
    main()
