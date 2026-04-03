"""
Paper Trading Runner for BTC Trend Long Bot
=============================================
Run paper trading with Bitget data feed or historical simulation.

Usage:
    # Historical simulation (like backtest but using paper trading infra)
    python -m btc_trend_bot.run_paper --mode historical --data data/raw/BTCUSDT_1h.csv

    # Live paper trading loop (fetches from Bitget every N seconds)
    python -m btc_trend_bot.run_paper --mode live --interval 300

    # Fetch data first then simulate
    python -m btc_trend_bot.run_paper --mode historical --fetch --start 2024-01-01
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger

from btc_trend_bot.env_loader import load_env


def load_config(config_path: str | None = None) -> dict:
    config_file = Path(__file__).parent / "config" / "settings.yaml"
    if config_path:
        config_file = Path(config_path)
    if not config_file.exists():
        return {}
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_historical(config: dict, data_path: str):
    """Run paper trading on historical data."""
    from btc_trend_bot.data_loader import DataLoader
    from btc_trend_bot.feature_engineering import FeatureEngineer
    from btc_trend_bot.live.paper_executor import PaperExecutor

    # Load data
    loader = DataLoader(str(Path(data_path).parent))
    df = loader.load_csv(data_path)

    # Add features
    fe = FeatureEngineer(config.get("trend_detection", {}))
    df = fe.add_all_features(df)
    logger.info(f"Data prepared: {len(df)} bars")

    # Paper config
    paper_config = config.get("paper_trading", {})
    paper_config.update({
        "strategies": config.get("strategies", {}),
        "trend_detection": config.get("trend_detection", {}),
        "exit": config.get("exit", {"method": "atr_trailing"}),
    })

    executor = PaperExecutor(paper_config)
    logger.info("Running historical paper trading simulation...")
    result = executor.run_on_historical(df)

    # Print results
    logger.info("\n" + "=" * 60)
    logger.info("PAPER TRADING SIMULATION RESULTS")
    logger.info("=" * 60)
    logger.info(f"Final equity:  {result['final_equity']:.2f} USDT")
    logger.info(f"Total PnL:     {result['total_pnl']:.2f} USDT")
    logger.info(f"Total trades:  {result['total_trades']}")

    if result["trades"]:
        trades_df = pd.DataFrame(result["trades"])
        wins = trades_df[trades_df["pnl"] > 0]
        losses = trades_df[trades_df["pnl"] <= 0]
        logger.info(f"Win rate:      {len(wins)/len(trades_df)*100:.1f}%")
        logger.info(f"Avg win:       {wins['pnl'].mean():.2f}" if len(wins) > 0 else "Avg win:       N/A")
        logger.info(f"Avg loss:      {losses['pnl'].mean():.2f}" if len(losses) > 0 else "Avg loss:      N/A")

        # Save trades
        report_dir = Path(__file__).parent / "reports" / "paper"
        report_dir.mkdir(parents=True, exist_ok=True)
        trades_df.to_csv(report_dir / "paper_trades.csv", index=False)
        logger.info(f"Trades saved to: {report_dir / 'paper_trades.csv'}")

    return result


def run_live(config: dict, interval: int):
    """Run live paper trading loop with Bitget feed."""
    from btc_trend_bot.live.paper_executor import PaperExecutor
    from btc_trend_bot.live.bitget_feed import BitgetFeed

    paper_config = config.get("paper_trading", {})
    paper_config.update({
        "strategies": config.get("strategies", {}),
        "trend_detection": config.get("trend_detection", {}),
        "exit": config.get("exit", {"method": "atr_trailing"}),
    })

    executor = PaperExecutor(paper_config)
    feed = BitgetFeed(config.get("exchange", {}))

    logger.info(f"Starting live paper trading (interval={interval}s)")
    logger.info("Press Ctrl+C to stop")

    executor.run_live_loop(feed, interval_seconds=interval)

    # Print final summary
    summary = executor.get_summary()
    logger.info("\n" + "=" * 60)
    logger.info("PAPER TRADING FINAL SUMMARY")
    logger.info("=" * 60)
    for k, v in summary.items():
        logger.info(f"  {k}: {v}")


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Paper Trading Runner")
    parser.add_argument("--mode", type=str, default="historical",
                        choices=["historical", "live"],
                        help="Paper trading mode")
    parser.add_argument("--data", type=str, default=None,
                        help="CSV file for historical mode")
    parser.add_argument("--fetch", action="store_true",
                        help="Fetch data from Bitget first")
    parser.add_argument("--start", type=str, default="2024-01-01",
                        help="Start date for fetch")
    parser.add_argument("--interval", type=int, default=300,
                        help="Interval in seconds for live mode")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    # Logging
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(str(log_dir / "paper.log"), rotation="10 MB", level="DEBUG")

    config = load_config(args.config)

    if args.mode == "historical":
        data_path = args.data

        if args.fetch:
            from btc_trend_bot.exchange.bitget_public import BitgetPublicClient
            from btc_trend_bot.exchange.models import ExchangeConfig
            client = BitgetPublicClient(ExchangeConfig())
            end_date = str(pd.Timestamp.now(tz="UTC").date())
            output_dir = str(Path(__file__).parent / "data" / "raw")
            data_path = client.download_and_save("BTCUSDT", "1h", args.start, end_date, output_dir)

        if data_path is None:
            default = Path(__file__).parent / "data" / "raw" / "BTCUSDT_1h.csv"
            if default.exists():
                data_path = str(default)
            else:
                logger.error("No data. Use --data, --fetch, or place CSV in data/raw/")
                sys.exit(1)

        run_historical(config, data_path)

    elif args.mode == "live":
        run_live(config, args.interval)


if __name__ == "__main__":
    main()
