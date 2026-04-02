"""
Run Backtest for BTC Trend Long Bot
====================================
Execute backtests for one or all strategies with configurable exit methods.

Usage:
    python -m btc_trend_bot.run_backtest
    python -m btc_trend_bot.run_backtest --strategy pullback --exit atr_trailing
    python -m btc_trend_bot.run_backtest --data data/raw/BTCUSDT_1h.csv --bull-only
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
from btc_trend_bot.backtest.engine import BacktestEngine
from btc_trend_bot.backtest.exit_manager import ExitManager
from btc_trend_bot.metrics import calc_all_metrics, calc_regime_metrics, get_top_trades
from btc_trend_bot.report_generator import ReportGenerator
from btc_trend_bot.strategies.trend_long.pullback_strategy import PullbackStrategy
from btc_trend_bot.strategies.trend_long.breakout_strategy import BreakoutStrategy
from btc_trend_bot.strategies.trend_long.reacceleration_strategy import ReaccelerationStrategy
from btc_trend_bot.strategies.trend_long.multi_tf_strategy import MultiTFStrategy


def _build_strategy_map() -> dict:
    """Build strategy map including strict variants if available."""
    strategy_map = {
        "pullback": PullbackStrategy,
        "breakout": BreakoutStrategy,
        "reacceleration": ReaccelerationStrategy,
        "multi_tf": MultiTFStrategy,
    }
    try:
        from btc_trend_bot.strategies.trend_long.pullback_strict import PullbackStrictStrategy
        strategy_map["pullback_strict"] = PullbackStrictStrategy
    except ImportError:
        pass
    try:
        from btc_trend_bot.strategies.trend_long.breakout_confirmed import BreakoutConfirmedStrategy
        strategy_map["breakout_confirmed"] = BreakoutConfirmedStrategy
    except ImportError:
        pass
    try:
        from btc_trend_bot.strategies.trend_long.reacceleration_quality import ReaccelerationQualityStrategy
        strategy_map["reacceleration_quality"] = ReaccelerationQualityStrategy
    except ImportError:
        pass
    try:
        from btc_trend_bot.strategies.trend_long.multi_tf_trend_hold import MultiTFTrendHoldStrategy
        strategy_map["multi_tf_trend_hold"] = MultiTFTrendHoldStrategy
    except ImportError:
        pass
    return strategy_map


STRATEGY_MAP = _build_strategy_map()


def load_config(config_path: str = "config/settings.yaml") -> dict:
    """Load configuration from YAML file."""
    config_file = Path(__file__).parent / config_path
    if not config_file.exists():
        logger.warning(f"Config not found at {config_file}, using defaults")
        return {}
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_single_strategy(
    strategy_name: str,
    df: pd.DataFrame,
    config: dict,
    exit_method: str = "atr_trailing",
    bull_only: bool = False,
    bull_runs: pd.DataFrame | None = None,
    higher_tf_df: pd.DataFrame | None = None,
) -> dict:
    """Run backtest for a single strategy."""
    logger.info(f"=== Running backtest: {strategy_name} (exit: {exit_method}) ===")

    # Filter to bull periods if requested
    if bull_only and bull_runs is not None:
        extractor = BullRunExtractor(config.get("bull_run_extraction", {}))
        df = extractor.filter_data_to_bull_runs(df, bull_runs)
        logger.info(f"Filtered to bull periods: {len(df)} bars")

    # Get strategy config
    strategy_configs = config.get("strategies", {})
    strat_config = strategy_configs.get(strategy_name, {})

    # Create strategy
    strategy_class = STRATEGY_MAP[strategy_name]

    if strategy_name == "multi_tf":
        strategy = strategy_class(strat_config)
        if higher_tf_df is not None:
            strategy.set_higher_tf_data(higher_tf_df)
        else:
            logger.warning("Multi-TF strategy requires higher timeframe data. Skipping.")
            return {}
    else:
        strategy = strategy_class(strat_config)

    # Generate signals
    signals = strategy.generate_signals(df)
    logger.info(f"Generated {len(signals)} signals")

    if not signals:
        logger.warning(f"No signals generated for {strategy_name}")
        return {
            "strategy": strategy_name,
            "exit_method": exit_method,
            "signals_count": 0,
            "trades": pd.DataFrame(),
            "equity": pd.Series(dtype=float),
            "metrics": {},
        }

    # Setup exit manager
    exit_config = config.get("exit", {})
    exit_config["method"] = exit_method
    exit_manager = ExitManager(exit_config)

    # Run backtest
    bt_config = config.get("backtest", {})
    engine = BacktestEngine(bt_config)
    result = engine.run(df, signals, exit_manager)

    # Calculate regime metrics if regime column exists
    regime_metrics = {}
    if "trend_regime" in df.columns and not result.trades.empty:
        try:
            regime_metrics = calc_regime_metrics(
                result.trades, result.equity_curve,
                df["trend_regime"]
            )
        except Exception as e:
            logger.warning(f"Could not compute regime metrics: {e}")

    return {
        "strategy": strategy_name,
        "exit_method": exit_method,
        "signals_count": len(signals),
        "trades": result.trades,
        "equity": result.equity_curve,
        "metrics": result.metrics,
        "regime_metrics": regime_metrics,
    }


def run_all_strategies(
    df: pd.DataFrame,
    config: dict,
    exit_methods: list[str] | None = None,
    bull_only: bool = False,
    bull_runs: pd.DataFrame | None = None,
    higher_tf_df: pd.DataFrame | None = None,
) -> list[dict]:
    """Run backtest for all strategies with multiple exit methods."""
    if exit_methods is None:
        exit_methods = config.get("exit", {}).get("methods", ["atr_trailing"])

    all_results = []

    for strategy_name in STRATEGY_MAP:
        for exit_method in exit_methods:
            try:
                result = run_single_strategy(
                    strategy_name, df, config, exit_method,
                    bull_only, bull_runs, higher_tf_df,
                )
                if result:
                    all_results.append(result)
            except Exception as e:
                logger.error(f"Error running {strategy_name}/{exit_method}: {e}")

    return all_results


def main():
    parser = argparse.ArgumentParser(description="BTC Trend Long Bot - Backtest Runner")
    parser.add_argument("--data", type=str, default=None, help="Path to OHLCV CSV file")
    parser.add_argument("--strategy", type=str, default="all",
                        choices=["all"] + list(STRATEGY_MAP.keys()),
                        help="Strategy to backtest")
    parser.add_argument("--exit", type=str, default="atr_trailing",
                        help="Exit method")
    parser.add_argument("--bull-only", action="store_true",
                        help="Only backtest on bull run periods")
    parser.add_argument("--config", type=str, default="config/settings.yaml",
                        help="Config file path")
    parser.add_argument("--generate-data", action="store_true",
                        help="Generate sample data first")
    args = parser.parse_args()

    # Setup logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add("logs/backtest.log", rotation="10 MB", level="DEBUG")

    # Load config
    config = load_config(args.config)
    logger.info("Config loaded")

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
    logger.info(f"Features added. Shape: {df.shape}")

    # Extract bull runs
    bull_extractor = BullRunExtractor(config.get("bull_run_extraction", {}))
    bull_runs = bull_extractor.extract(df)
    logger.info(f"Found {len(bull_runs)} bull run periods")

    # Prepare higher TF data for multi-TF strategy
    higher_tf_df = None
    try:
        higher_tf_df = loader.resample(df, "4h")
        fe_htf = FeatureEngineer(config.get("trend_detection", {}))
        higher_tf_df = fe_htf.add_all_features(higher_tf_df)
    except Exception as e:
        logger.warning(f"Could not prepare higher TF data: {e}")

    # Run backtests
    if args.strategy == "all":
        results = run_all_strategies(
            df, config, bull_only=args.bull_only,
            bull_runs=bull_runs, higher_tf_df=higher_tf_df,
        )
    else:
        result = run_single_strategy(
            args.strategy, df, config, args.exit,
            args.bull_only, bull_runs, higher_tf_df,
        )
        results = [result] if result else []

    if not results:
        logger.error("No results generated")
        return

    # Generate reports
    reporter = ReportGenerator(
        config.get("reports", {}).get("output_dir", "reports")
    )

    for r in results:
        if r.get("trades") is not None and not r["trades"].empty:
            reporter.generate_full_report(r, f"{r['strategy']}_{r['exit_method']}")

    # Save ranking
    reporter.save_ranking(results)

    # Summary
    logger.info("\n=== BACKTEST SUMMARY ===")
    for r in results:
        m = r.get("metrics", {})
        logger.info(
            f"{r['strategy']:20s} | exit={r.get('exit_method', 'N/A'):15s} | "
            f"trades={r.get('signals_count', 0):4d} | "
            f"PF={m.get('profit_factor', 0):.2f} | "
            f"WR={m.get('win_rate', 0)*100:.1f}% | "
            f"Calmar={m.get('calmar_ratio', 0):.2f} | "
            f"MaxDD={m.get('max_dd_pct', 0)*100:.1f}%"
        )

    # Also run bull-only comparison
    if not args.bull_only and bull_runs is not None and not bull_runs.empty:
        logger.info("\n=== BULL PERIOD ONLY ===")
        bull_results = run_all_strategies(
            df, config, exit_methods=["atr_trailing"],
            bull_only=True, bull_runs=bull_runs, higher_tf_df=higher_tf_df,
        )
        for r in bull_results:
            m = r.get("metrics", {})
            if m:
                logger.info(
                    f"{r['strategy']:20s} | "
                    f"PF={m.get('profit_factor', 0):.2f} | "
                    f"WR={m.get('win_rate', 0)*100:.1f}% | "
                    f"Calmar={m.get('calmar_ratio', 0):.2f}"
                )
        # Save bull-only metrics
        for r in bull_results:
            if r.get("trades") is not None and not r["trades"].empty:
                reporter.save_metrics_csv(
                    r["metrics"],
                    f"{r['strategy']}_bull_only"
                )


if __name__ == "__main__":
    main()
