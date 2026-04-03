"""
BTC Trend Long Bot - Main Entry Point
======================================
Complete pipeline: data → features → bull run extraction → backtest → optimize → report

Usage:
    python -m btc_trend_bot.main
    python -m btc_trend_bot.main --mode backtest
    python -m btc_trend_bot.main --mode optimize
    python -m btc_trend_bot.main --mode full
"""

import argparse
import os
import sys
from pathlib import Path

import yaml
from loguru import logger

from btc_trend_bot.env_loader import load_env


def load_config(config_path: str | None = None) -> dict:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = str(Path(__file__).parent / "config" / "settings.yaml")
    config_file = Path(config_path)
    if not config_file.exists():
        logger.warning(f"Config not found at {config_file}, using defaults")
        return {}
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging():
    """Configure logging."""
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")
    logger.add(str(log_dir / "main.log"), rotation="10 MB", level="DEBUG")


def run_data_prep(config: dict) -> tuple:
    """Prepare data: load, add features, extract bull runs."""
    from btc_trend_bot.data_loader import DataLoader, generate_sample_data
    from btc_trend_bot.feature_engineering import FeatureEngineer
    from btc_trend_bot.extract_bull_runs import BullRunExtractor

    # Ensure data exists
    data_dir = Path(__file__).parent / "data" / "raw"
    default_data = data_dir / "BTCUSDT_1h.csv"
    if not default_data.exists():
        logger.info("No data found. Generating sample data...")
        generate_sample_data(str(default_data))

    # Load
    loader = DataLoader(str(data_dir))
    df = loader.load_csv(str(default_data))
    logger.info(f"Loaded {len(df)} bars")

    # Add features
    fe = FeatureEngineer(config.get("trend_detection", {}))
    df = fe.add_all_features(df)
    logger.info(f"Features added: {df.shape[1]} columns")

    # Extract bull runs
    extractor = BullRunExtractor(config.get("bull_run_extraction", {}))
    bull_runs = extractor.extract(df)
    if not bull_runs.empty:
        output = Path(__file__).parent / "data" / "processed" / "bull_runs.csv"
        extractor.save(bull_runs, str(output))
        logger.info(f"Extracted {len(bull_runs)} bull run periods")
    else:
        logger.warning("No bull runs found in data")

    # Prepare higher TF
    higher_tf_df = None
    try:
        higher_tf_df = loader.resample(df, "4h")
        fe_htf = FeatureEngineer(config.get("trend_detection", {}))
        higher_tf_df = fe_htf.add_all_features(higher_tf_df)
    except Exception as e:
        logger.warning(f"Higher TF preparation failed: {e}")

    return df, bull_runs, higher_tf_df


def run_backtest_mode(config: dict, df, bull_runs, higher_tf_df):
    """Run backtests for all strategies."""
    from btc_trend_bot.run_backtest import run_all_strategies
    from btc_trend_bot.report_generator import ReportGenerator

    results = run_all_strategies(
        df, config,
        exit_methods=["atr_trailing", "partial_trail", "ema_break"],
        bull_only=False,
        bull_runs=bull_runs,
        higher_tf_df=higher_tf_df,
    )

    reporter = ReportGenerator(
        config.get("reports", {}).get("output_dir",
                                      str(Path(__file__).parent / "reports"))
    )

    for r in results:
        if r.get("trades") is not None and not r["trades"].empty:
            reporter.generate_full_report(r, f"{r['strategy']}_{r['exit_method']}")

    reporter.save_ranking(results)

    # Bull-only comparison
    bull_results = run_all_strategies(
        df, config,
        exit_methods=["atr_trailing"],
        bull_only=True,
        bull_runs=bull_runs,
        higher_tf_df=higher_tf_df,
    )
    for r in bull_results:
        if r.get("trades") is not None and not r["trades"].empty:
            reporter.save_metrics_csv(r["metrics"], f"{r['strategy']}_bull_only")

    return results, bull_results


def run_optimize_mode(config: dict, df):
    """Run optimization for all strategies."""
    from btc_trend_bot.optimizer.optimizer import StrategyOptimizer
    from btc_trend_bot.strategies.trend_long.pullback_strategy import PullbackStrategy
    from btc_trend_bot.strategies.trend_long.breakout_strategy import BreakoutStrategy
    from btc_trend_bot.strategies.trend_long.reacceleration_strategy import ReaccelerationStrategy

    opt_config = config.get("optimization", {})
    optimizer = StrategyOptimizer(opt_config)
    exit_config = config.get("exit", {})
    exit_config["method"] = "atr_trailing"
    bt_config = config.get("backtest", {})

    strategies = {
        "pullback": PullbackStrategy,
        "breakout": BreakoutStrategy,
        "reacceleration": ReaccelerationStrategy,
    }

    results = optimizer.compare_strategies(
        list(strategies.values()), df, exit_config, bt_config,
    )

    logger.info("\n=== OPTIMIZATION RANKING ===")
    logger.info(results.to_string())

    # Save
    output_dir = Path(__file__).parent / config.get("reports", {}).get("output_dir", "reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(output_dir / "optimization_ranking.csv", index=False)

    return results


def main():
    parser = argparse.ArgumentParser(description="BTC Trend Long Bot")
    parser.add_argument("--mode", type=str, default="full",
                        choices=["data", "backtest", "optimize", "full"],
                        help="Execution mode")
    parser.add_argument("--config", type=str, default=None,
                        help="Config file path")
    args = parser.parse_args()

    load_env()
    setup_logging()
    logger.info("=" * 60)
    logger.info("BTC Trend Long Bot - Starting")
    logger.info("=" * 60)

    config = load_config(args.config)

    # Step 1: Data preparation
    logger.info("\n[STEP 1] Data Preparation")
    df, bull_runs, higher_tf_df = run_data_prep(config)

    if args.mode == "data":
        logger.info("Data preparation complete. Exiting.")
        return

    # Step 2: Backtest
    if args.mode in ("backtest", "full"):
        logger.info("\n[STEP 2] Backtesting")
        results, bull_results = run_backtest_mode(config, df, bull_runs, higher_tf_df)

        # Print summary
        logger.info("\n=== ALL PERIOD RESULTS ===")
        for r in results:
            m = r.get("metrics", {})
            if m:
                logger.info(
                    f"  {r['strategy']:20s} | {r.get('exit_method',''):15s} | "
                    f"PF={m.get('profit_factor',0):.2f} | "
                    f"Calmar={m.get('calmar_ratio',0):.2f} | "
                    f"WR={m.get('win_rate',0)*100:.1f}%"
                )

    # Step 3: Optimization
    if args.mode in ("optimize", "full"):
        logger.info("\n[STEP 3] Optimization")
        opt_results = run_optimize_mode(config, df)

    # Step 4: Generate final summary
    if args.mode == "full":
        logger.info("\n[STEP 4] Generating Final Reports")
        from btc_trend_bot.report_generator import ReportGenerator
        reporter = ReportGenerator(
            config.get("reports", {}).get("output_dir",
                                          str(Path(__file__).parent / "reports"))
        )
        if results:
            # Find best result
            best = max(
                [r for r in results if r.get("metrics")],
                key=lambda x: x["metrics"].get("calmar_ratio", 0),
                default=None,
            )
            if best:
                reporter.generate_summary_md(best, results)
                logger.info("Summary report generated: reports/ベスト戦略要約.md")

    logger.info("\n" + "=" * 60)
    logger.info("BTC Trend Long Bot - Complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
