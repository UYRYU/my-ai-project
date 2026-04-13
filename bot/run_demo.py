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
from bot.portfolio import (
    load_state,
    calculate_position_size,
    record_entry,
    record_exit,
    print_dashboard,
    save_state,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    print("=" * 50)
    print("  Polymarket Arb Bot — DEMO MODE")
    print("  Portfolio auto-sizing (Kelly criterion)")
    print("=" * 50)

    # Initialize portfolio with 50万円 ≈ $3,145
    state = load_state(initial_capital=3145.0)
    # Reset for clean demo
    state.available_cash = state.initial_capital
    state.total_invested = 0.0
    state.total_realized_pnl = 0.0
    state.positions = []
    state.trade_count = 0
    save_state(state)

    print(f"\n  Starting capital: ${state.initial_capital:,.0f} (≈¥50万)")
    print_dashboard(state)

    events = generate_demo_events()
    all_markets = [m for e in events for m in e.markets]

    # Simulate 3 scan cycles, then resolve positions
    for cycle in range(1, 4):
        t0 = time.time()
        print(f"\n{'─'*50}")
        print(f"  Scan cycle {cycle}")
        print(f"{'─'*50}")

        # Detect
        opps = detect_single_condition_arbitrage(all_markets)
        opps.extend(detect_negrisk_arbitrage(events))

        # Filter profitable
        opps = [o for o in opps if o.net_profit_per_dollar >= 0.015]

        elapsed = time.time() - t0

        if opps:
            print(f"  Found {len(opps)} opportunities ({elapsed*1000:.0f}ms)\n")
            for opp in opps:
                # Portfolio manager decides size
                size = calculate_position_size(state, opp)
                if size is None:
                    print(f"  SKIP: {opp.markets[0].question[:50]}... (risk limit)")
                    continue

                print(_format_alert(opp))
                print(f"  Kelly optimal size: ${size:.2f}")
                print(f"  Expected profit: ${size * opp.net_profit_per_dollar:.4f}")

                # Record entry
                pos = record_entry(state, opp, size)
                print(f"  Recorded as {pos.id}\n")

                _log_opportunity(opp)
        else:
            print(f"  No opportunities above threshold ({elapsed*1000:.0f}ms)")

        print_dashboard(state)

        if cycle < 3:
            print("  Waiting 2s...")
            time.sleep(2)

    # Simulate resolution — all arbs pay out
    print(f"\n{'='*50}")
    print("  Simulating market resolution (all arbs succeed)")
    print(f"{'='*50}")

    for pos in list(state.open_positions):
        record_exit(state, pos.id)
        print(f"  {pos.id} closed: +${pos.expected_profit:.4f}")

    print(f"\n  Final portfolio:")
    print_dashboard(state)

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
