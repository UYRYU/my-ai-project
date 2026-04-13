#!/usr/bin/env python3
"""Polymarket Arb Bot — Entry point.

50万円 all-in Polymarket. Scans for arbitrage every 60 seconds.

Usage:
  # Dry run (scan only, no trades)
  python -m bot.run

  # With alerts to Discord
  WEBHOOK_URL=https://discord.com/api/webhooks/... python -m bot.run

  # Live trading (requires py-clob-client + API keys)
  EXECUTION_MODE=live POLY_API_KEY=... python -m bot.run

  # Custom scan interval
  SCAN_INTERVAL=30 python -m bot.run

Environment variables:
  SCAN_INTERVAL    Seconds between scans (default: 60)
  MIN_PROFIT       Minimum profit % to alert (default: 0.015 = 1.5%)
  MIN_VOLUME       Minimum market volume (default: 50000)
  MAX_EVENTS       Max events to fetch per scan (default: 500)
  WEBHOOK_URL      Discord/Telegram webhook for alerts
  EXECUTION_MODE   "dry_run" (default) or "live"
  POSITION_SIZE    USD per trade (default: 50)
  MAX_POSITION     Max USD per trade (default: 200)
  POLY_API_KEY     Polymarket API key (for live trading)
  LOG_DIR          Directory for log files (default: bot_logs)
"""

import asyncio
import logging
import os
import sys


def main():
    # Setup logging
    log_level = logging.DEBUG if os.environ.get("DEBUG") else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    mode = os.environ.get("EXECUTION_MODE", "dry_run")
    interval = int(os.environ.get("SCAN_INTERVAL", "60"))

    print("=" * 50)
    print("  Polymarket Arb Bot")
    print("=" * 50)
    print(f"  Mode:      {mode}")
    print(f"  Interval:  {interval}s")
    print(f"  Min profit: {float(os.environ.get('MIN_PROFIT', '0.015'))*100:.1f}%")
    print(f"  Min volume: ${int(os.environ.get('MIN_VOLUME', '50000')):,}")
    print(f"  Webhook:   {'✓' if os.environ.get('WEBHOOK_URL') else '✗'}")
    print("=" * 50)

    if mode == "live":
        if not os.environ.get("POLY_API_KEY"):
            print("\n  ERROR: POLY_API_KEY required for live mode")
            print("  Set: export POLY_API_KEY=your_key")
            sys.exit(1)
        print("\n  ⚠ LIVE MODE — real money will be traded!")
        print("  Press Ctrl+C within 5s to cancel...")
        try:
            import time
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n  Cancelled.")
            sys.exit(0)

    print("\n  Starting scanner...\n")

    from bot.scanner import run_bot
    asyncio.run(run_bot(
        interval=interval,
        auto_execute=(mode == "live"),
    ))


if __name__ == "__main__":
    main()
