"""
Fetch BTCUSDT OHLCV data from Bitget
=====================================
Download historical candle data and save to CSV.

Usage:
    python -m btc_trend_bot.fetch_data
    python -m btc_trend_bot.fetch_data --timeframe 1h --start 2023-01-01 --end 2024-12-31
    python -m btc_trend_bot.fetch_data --all-timeframes --start 2023-01-01
"""

import argparse
import os
import sys
from pathlib import Path

from loguru import logger


def _load_env():
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())
        logger.info("Loaded .env from {}", env_path)


def main():
    parser = argparse.ArgumentParser(description="Fetch BTCUSDT data from Bitget")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Trading pair")
    parser.add_argument("--timeframe", type=str, default="1h",
                        choices=["5m", "15m", "1h", "4h", "1d"],
                        help="Candle timeframe")
    parser.add_argument("--all-timeframes", action="store_true",
                        help="Fetch all timeframes (5m, 15m, 1h, 4h)")
    parser.add_argument("--start", type=str, default="2023-01-01",
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None,
                        help="End date (YYYY-MM-DD), defaults to now")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory for CSV files")
    args = parser.parse_args()

    # Setup logging
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")
    logger.add("logs/fetch_data.log", rotation="10 MB", level="DEBUG")
    Path("logs").mkdir(exist_ok=True)

    # Load .env before imports that might need env vars
    _load_env()

    from btc_trend_bot.exchange.bitget_public import BitgetPublicClient
    from btc_trend_bot.exchange.models import ExchangeConfig

    # End date
    if args.end is None:
        import pandas as pd
        args.end = str(pd.Timestamp.now(tz="UTC").date())

    # Output dir
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = str(Path(__file__).parent / "data" / "raw")

    # Create client with env vars
    config = ExchangeConfig(
        api_key=os.environ.get("BITGET_API_KEY", ""),
        api_secret=os.environ.get("BITGET_API_SECRET", ""),
        passphrase=os.environ.get("BITGET_PASSPHRASE", ""),
    )
    client = BitgetPublicClient(config)

    timeframes = ["5m", "15m", "1h", "4h"] if args.all_timeframes else [args.timeframe]

    for tf in timeframes:
        logger.info(f"Fetching {args.symbol} {tf} from {args.start} to {args.end}")
        try:
            filepath = client.download_and_save(
                symbol=args.symbol,
                timeframe=tf,
                start_date=args.start,
                end_date=args.end,
                output_dir=output_dir,
            )
            logger.info(f"Saved: {filepath}")
        except Exception as e:
            logger.error(f"Failed to fetch {tf}: {e}")
            import traceback
            traceback.print_exc()

    logger.info("Data fetch complete")


if __name__ == "__main__":
    main()
