"""
Run Optimization for BTC Trend Long Bot
========================================
Optimize strategy parameters using Optuna with walk-forward validation.

Usage:
    python -m btc_trend_bot.run_optimize
    python -m btc_trend_bot.run_optimize --strategy pullback --trials 300
    python -m btc_trend_bot.run_optimize --walk-forward --splits 5
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger

from btc_trend_bot.data_loader import DataLoader, generate_sample_data
from btc_trend_bot.feature_engineering import FeatureEngineer
from btc_trend_bot.extract_bull_runs import BullRunExtractor
from btc_trend_bot.optimizer.optimizer import StrategyOptimizer
from btc_trend_bot.report_generator import ReportGenerator
from btc_trend_bot.strategies.trend_long.pullback_strategy import PullbackStrategy
from btc_trend_bot.strategies.trend_long.breakout_strategy import BreakoutStrategy
from btc_trend_bot.strategies.trend_long.reacceleration_strategy import ReaccelerationStrategy
from btc_trend_bot.strategies.trend_long.multi_tf_strategy import MultiTFStrategy


STRATEGY_MAP = {
    "pullback": PullbackStrategy,
    "breakout": BreakoutStrategy,
    "reacceleration": ReaccelerationStrategy,
    "multi_tf": MultiTFStrategy,
}


def load_config(config_path: str = "config/settings.yaml") -> dict:
    """Load configuration from YAML file."""
    config_file = Path(__file__).parent / config_path
    if not config_file.exists():
        logger.warning(f"Config not found at {config_file}, using defaults")
        return {}
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="BTC Trend Long Bot - Optimizer")
    parser.add_argument("--data", type=str, default=None, help="Path to OHLCV CSV file")
    parser.add_argument("--strategy", type=str, default="all",
                        choices=["all"] + list(STRATEGY_MAP.keys()),
                        help="Strategy to optimize")
    parser.add_argument("--trials", type=int, default=200,
                        help="Number of Optuna trials")
    parser.add_argument("--objective", type=str, default="calmar_ratio",
                        choices=["calmar_ratio", "profit_factor", "total_profit", "expectancy"],
                        help="Optimization objective metric")
    parser.add_argument("--walk-forward", action="store_true",
                        help="Use walk-forward optimization")
    parser.add_argument("--splits", type=int, default=5,
                        help="Number of walk-forward splits")
    parser.add_argument("--config", type=str, default="config/settings.yaml",
                        help="Config file path")
    parser.add_argument("--generate-data", action="store_true",
                        help="Generate sample data first")
    args = parser.parse_args()

    # Setup logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add("logs/optimize.log", rotation="10 MB", level="DEBUG")

    # Load config
    config = load_config(args.config)
    opt_config = config.get("optimization", {})
    opt_config["n_trials"] = args.trials
    opt_config["objective"] = args.objective

    # Generate sample data if needed
    data_path = args.data
    if args.generate_data or data_path is None:
        default_path = str(Path(__file__).parent / "data" / "raw" / "BTCUSDT_1h.csv")
        if not Path(default_path).exists():
            logger.info("Generating sample data...")
            generate_sample_data(default_path)
        data_path = default_path

    # Load data
    loader = DataLoader(
        data_dir=str(Path(data_path).parent),
        timezone=config.get("data", {}).get("timezone", "UTC"),
    )
    df = loader.load_csv(data_path)

    # Add features
    fe = FeatureEngineer(config.get("trend_detection", {}))
    df = fe.add_all_features(df)
    logger.info(f"Data prepared: {len(df)} bars, {df.shape[1]} features")

    # Setup optimizer
    optimizer = StrategyOptimizer(opt_config)
    exit_config = config.get("exit", {})
    exit_config["method"] = "atr_trailing"
    bt_config = config.get("backtest", {})

    # Select strategies
    if args.strategy == "all":
        strategies_to_opt = {k: v for k, v in STRATEGY_MAP.items() if k != "multi_tf"}
    else:
        strategies_to_opt = {args.strategy: STRATEGY_MAP[args.strategy]}

    all_results = []

    for name, strategy_class in strategies_to_opt.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"Optimizing: {name}")
        logger.info(f"{'='*60}")

        try:
            if args.walk_forward:
                wf_results = optimizer.walk_forward(
                    strategy_class, df, exit_config, bt_config,
                    n_splits=args.splits,
                    train_pct=opt_config.get("walk_forward", {}).get("train_pct", 70),
                )
                # Use average of walk-forward results
                if wf_results:
                    avg_metrics = {}
                    for key in wf_results[0].get("test_metrics", {}).keys():
                        values = [r["test_metrics"].get(key, 0) for r in wf_results if r.get("test_metrics")]
                        if values:
                            avg_metrics[key] = sum(values) / len(values)

                    best_params = wf_results[0].get("best_params", {})
                    all_results.append({
                        "strategy": name,
                        "method": "walk_forward",
                        "best_params": best_params,
                        "avg_test_metrics": avg_metrics,
                        "n_splits": len(wf_results),
                        "per_split": wf_results,
                    })
                    logger.info(f"Walk-forward avg metrics: {avg_metrics}")
            else:
                result = optimizer.optimize(
                    strategy_class, df, exit_config, bt_config,
                )
                if result:
                    all_results.append({
                        "strategy": name,
                        "method": "standard",
                        **result,
                    })
                    logger.info(f"Best params: {result.get('best_params', {})}")
                    logger.info(f"Validation metrics: {result.get('validation_metrics', {})}")
        except Exception as e:
            logger.error(f"Optimization failed for {name}: {e}")
            import traceback
            traceback.print_exc()

    if not all_results:
        logger.error("No optimization results")
        return

    # Save results
    reporter = ReportGenerator(
        config.get("reports", {}).get("output_dir", "reports")
    )

    # Save parameter rankings
    ranking_data = []
    for r in all_results:
        metrics = r.get("validation_metrics", r.get("avg_test_metrics", {}))
        ranking_data.append({
            "strategy": r["strategy"],
            "method": r["method"],
            "calmar_ratio": metrics.get("calmar_ratio", 0),
            "profit_factor": metrics.get("profit_factor", 0),
            "win_rate": metrics.get("win_rate", 0),
            "total_profit": metrics.get("total_profit", 0),
            "max_dd_pct": metrics.get("max_drawdown_pct", 0),
            "best_params": str(r.get("best_params", {})),
        })

    ranking_df = pd.DataFrame(ranking_data)
    ranking_df = ranking_df.sort_values("calmar_ratio", ascending=False)
    ranking_path = Path(reporter.output_dir) / "optimization_ranking.csv"
    ranking_df.to_csv(ranking_path, index=False)
    logger.info(f"Ranking saved to {ranking_path}")

    # Save detailed params
    params_data = []
    for r in all_results:
        params = r.get("best_params", {})
        params["strategy"] = r["strategy"]
        params_data.append(params)

    params_df = pd.DataFrame(params_data)
    params_path = Path(reporter.output_dir) / "best_parameters.csv"
    params_df.to_csv(params_path, index=False)
    logger.info(f"Parameters saved to {params_path}")

    # Print summary
    logger.info("\n=== OPTIMIZATION SUMMARY ===")
    logger.info(f"{'Strategy':20s} | {'Calmar':>8s} | {'PF':>6s} | {'WR':>6s} | {'Method':>12s}")
    logger.info("-" * 60)
    for _, row in ranking_df.iterrows():
        logger.info(
            f"{row['strategy']:20s} | "
            f"{row['calmar_ratio']:8.2f} | "
            f"{row['profit_factor']:6.2f} | "
            f"{row['win_rate']*100 if row['win_rate'] <= 1 else row['win_rate']:5.1f}% | "
            f"{row['method']:>12s}"
        )

    # Identify top strategies
    top_n = min(3, len(ranking_df))
    logger.info(f"\nTop {top_n} strategies selected for further analysis")
    for i, (_, row) in enumerate(ranking_df.head(top_n).iterrows()):
        logger.info(f"  {i+1}. {row['strategy']} (Calmar={row['calmar_ratio']:.2f})")


if __name__ == "__main__":
    main()
