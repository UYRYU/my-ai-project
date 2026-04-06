"""
Multi-Symbol Backtest Runner
============================
Run identical strategies across BTC, ETH, XRP, DOGE, SOL.
Compares performance with $100 capital, futures fees, per-coin min order sizes.

Usage:
    python -m btc_trend_bot.run_multisymbol_backtest
    python -m btc_trend_bot.run_multisymbol_backtest --symbols BTCUSDT,ETHUSDT
    python -m btc_trend_bot.run_multisymbol_backtest --strategy multi_tf_trend_hold --exit partial_trail
    python -m btc_trend_bot.run_multisymbol_backtest --generate-data
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger

from btc_trend_bot.env_loader import load_env
from btc_trend_bot.data_loader import DataLoader
from btc_trend_bot.feature_engineering import FeatureEngineer
from btc_trend_bot.backtest.engine import BacktestEngine
from btc_trend_bot.backtest.exit_manager import ExitManager


# ---------------------------------------------------------------
# Per-coin settings for Bitget USDT-M Futures
# ---------------------------------------------------------------
COIN_CONFIGS = {
    "BTCUSDT": {"min_order_size": 0.001, "price_decimals": 1},
    "ETHUSDT": {"min_order_size": 0.01, "price_decimals": 2},
    "XRPUSDT": {"min_order_size": 1.0, "price_decimals": 4},
    "DOGEUSDT": {"min_order_size": 10.0, "price_decimals": 5},
    "SOLUSDT": {"min_order_size": 0.01, "price_decimals": 2},
}

ALL_SYMBOLS = list(COIN_CONFIGS.keys())

# Strategies to test (best performers from BTC analysis)
DEFAULT_STRATEGIES = [
    "multi_tf_trend_hold",
    "breakout_confirmed",
    "pullback_strict",
    "reacceleration_quality",
]

DEFAULT_EXIT_METHODS = ["partial_trail", "atr_trailing"]


def _get_strategy_classes(names: list[str] | None = None) -> dict:
    """Import strategy classes."""
    from btc_trend_bot.strategies.trend_long.pullback_strategy import PullbackStrategy
    from btc_trend_bot.strategies.trend_long.breakout_strategy import BreakoutStrategy
    from btc_trend_bot.strategies.trend_long.reacceleration_strategy import ReaccelerationStrategy
    from btc_trend_bot.strategies.trend_long.multi_tf_strategy import MultiTFStrategy

    all_strategies = {
        "pullback": PullbackStrategy,
        "breakout": BreakoutStrategy,
        "reacceleration": ReaccelerationStrategy,
        "multi_tf": MultiTFStrategy,
    }

    try:
        from btc_trend_bot.strategies.trend_long.pullback_strict import PullbackStrictStrategy
        all_strategies["pullback_strict"] = PullbackStrictStrategy
    except ImportError:
        pass
    try:
        from btc_trend_bot.strategies.trend_long.breakout_confirmed import BreakoutConfirmedStrategy
        all_strategies["breakout_confirmed"] = BreakoutConfirmedStrategy
    except ImportError:
        pass
    try:
        from btc_trend_bot.strategies.trend_long.reacceleration_quality import ReaccelerationQualityStrategy
        all_strategies["reacceleration_quality"] = ReaccelerationQualityStrategy
    except ImportError:
        pass
    try:
        from btc_trend_bot.strategies.trend_long.multi_tf_trend_hold import MultiTFTrendHoldStrategy
        all_strategies["multi_tf_trend_hold"] = MultiTFTrendHoldStrategy
    except ImportError:
        pass

    if names:
        return {k: v for k, v in all_strategies.items() if k in names}
    return all_strategies


def load_config(config_path: str | None = None) -> dict:
    config_file = Path(__file__).parent / "config" / "settings.yaml"
    if config_path:
        config_file = Path(config_path)
    if not config_file.exists():
        return {}
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_single(
    symbol: str,
    strategy_name: str,
    strategy_class,
    df: pd.DataFrame,
    config: dict,
    exit_method: str,
    higher_tf_df: pd.DataFrame | None = None,
) -> dict | None:
    """Run one strategy+exit on one symbol."""
    strat_config = config.get("strategies", {}).get(strategy_name, {})

    # Create strategy
    if strategy_name in ("multi_tf", "multi_tf_trend_hold"):
        strategy = strategy_class(strat_config)
        if higher_tf_df is not None and hasattr(strategy, "set_higher_tf_data"):
            strategy.set_higher_tf_data(higher_tf_df)
        elif strategy_name == "multi_tf":
            return None
    else:
        strategy = strategy_class(strat_config)

    # Generate signals
    signals = strategy.generate_signals(df)
    if not signals:
        return {
            "symbol": symbol,
            "strategy": strategy_name,
            "exit_method": exit_method,
            "signals_count": 0,
            "total_trades": 0,
            "metrics": {},
        }

    # Backtest with per-coin min order size
    exit_config = config.get("exit", {})
    exit_config["method"] = exit_method
    exit_manager = ExitManager(exit_config)

    bt_config = dict(config.get("backtest", {}))
    coin_cfg = COIN_CONFIGS.get(symbol, {})
    bt_config["min_order_size"] = coin_cfg.get("min_order_size", 0.001)

    engine = BacktestEngine(bt_config)
    result = engine.run(df, signals, exit_manager)

    m = result.metrics
    return {
        "symbol": symbol,
        "strategy": strategy_name,
        "exit_method": exit_method,
        "signals_count": len(signals),
        "total_trades": m.get("total_trades", 0),
        "total_profit": m.get("total_profit", 0),
        "profit_factor": m.get("profit_factor", 0),
        "win_rate": m.get("win_rate", 0),
        "calmar_ratio": m.get("calmar_ratio", 0),
        "max_drawdown_pct": m.get("max_drawdown_pct", 0),
        "expectancy": m.get("expectancy", 0),
        "avg_win_loss_ratio": m.get("avg_win_loss_ratio", 0),
        "metrics": m,
    }


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Multi-Symbol Backtest Runner")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbols (default: all 5)")
    parser.add_argument("--strategy", type=str, default=None,
                        help="Strategy name (default: top 4)")
    parser.add_argument("--exit", type=str, default=None,
                        help="Exit method (default: partial_trail,atr_trailing)")
    parser.add_argument("--generate-data", action="store_true",
                        help="Generate sample data if missing")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    # Logging
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(str(log_dir / "multisymbol_backtest.log"), rotation="10 MB", level="DEBUG")

    config = load_config(args.config)

    # Determine symbols
    symbols = args.symbols.split(",") if args.symbols else ALL_SYMBOLS

    # Determine strategies & exits
    strat_names = [args.strategy] if args.strategy else DEFAULT_STRATEGIES
    exit_methods = [args.exit] if args.exit else DEFAULT_EXIT_METHODS
    strategy_map = _get_strategy_classes(strat_names)

    # Data directory
    data_dir = Path(__file__).parent / "data" / "raw"

    # Check data availability, generate if needed
    missing = [s for s in symbols if not (data_dir / f"{s}_1h.csv").exists()]
    if missing:
        if args.generate_data or True:  # Auto-generate for convenience
            logger.info(f"Generating sample data for: {', '.join(missing)}")
            from btc_trend_bot.generate_multisymbol_data import generate_all
            generate_all(missing)
        else:
            logger.error(f"Missing data for: {', '.join(missing)}")
            logger.info("Fetch with: python -m btc_trend_bot.fetch_data --symbol <SYM>")
            logger.info("Or use --generate-data to create sample data")
            sys.exit(1)

    # Run backtests
    all_results = []
    total = len(symbols) * len(strategy_map) * len(exit_methods)
    logger.info(f"Running {total} combinations: {len(symbols)} symbols x "
                f"{len(strategy_map)} strategies x {len(exit_methods)} exits")
    logger.info(f"Capital: ${config.get('backtest', {}).get('initial_capital', 100)}")
    logger.info("=" * 80)

    loader = DataLoader(str(data_dir))

    for symbol in symbols:
        data_file = data_dir / f"{symbol}_1h.csv"
        logger.info(f"\n--- {symbol} ---")

        try:
            df = loader.load_csv(str(data_file))
        except Exception as e:
            logger.error(f"Failed to load {symbol}: {e}")
            continue

        # Feature engineering
        fe = FeatureEngineer(config.get("trend_detection", {}))
        df = fe.add_all_features(df)

        # Higher TF
        higher_tf_df = None
        try:
            higher_tf_df = loader.resample(df, "4h")
            fe_htf = FeatureEngineer(config.get("trend_detection", {}))
            higher_tf_df = fe_htf.add_all_features(higher_tf_df)
        except Exception as e:
            logger.warning(f"Higher TF prep failed for {symbol}: {e}")

        logger.info(f"Loaded {len(df)} bars: {df.index[0]} to {df.index[-1]}")

        for strat_name, strat_class in strategy_map.items():
            for exit_method in exit_methods:
                try:
                    result = run_single(
                        symbol, strat_name, strat_class, df, config,
                        exit_method, higher_tf_df,
                    )
                    if result:
                        all_results.append(result)
                        t = result.get("total_trades", 0)
                        pf = result.get("profit_factor", 0)
                        cal = result.get("calmar_ratio", 0)
                        logger.info(f"  {strat_name:25s} + {exit_method:15s} | "
                                    f"trades={t:3d} PF={pf:.2f} Calmar={cal:.2f}")
                except Exception as e:
                    logger.error(f"  {strat_name} + {exit_method}: {e}")

    # Build results DataFrame
    if not all_results:
        logger.error("No results produced!")
        sys.exit(1)

    results_df = pd.DataFrame(all_results)

    # Drop the nested metrics dict for the CSV
    csv_df = results_df.drop(columns=["metrics"], errors="ignore")

    # Report directory
    report_dir = Path(__file__).parent / "reports" / "multisymbol"
    report_dir.mkdir(parents=True, exist_ok=True)

    # Save full results
    csv_df.to_csv(report_dir / "全通貨バックテスト結果.csv", index=False, encoding="utf-8-sig")

    # --- Summary tables ---

    # 1. Best combo per symbol
    logger.info("\n" + "=" * 90)
    logger.info("MULTI-SYMBOL BACKTEST RESULTS ($100 capital, futures fees)")
    logger.info("=" * 90)

    logger.info(f"\n{'Symbol':10s} | {'Strategy':25s} | {'Exit':15s} | "
                f"{'Trades':>6s} | {'PF':>6s} | {'WR':>6s} | {'Calmar':>8s} | {'DD%':>7s} | {'Profit':>8s}")
    logger.info("-" * 90)

    for symbol in symbols:
        sym_df = csv_df[csv_df["symbol"] == symbol].copy()
        if sym_df.empty:
            continue
        best = sym_df.sort_values("calmar_ratio", ascending=False).iloc[0]
        wr = best["win_rate"] * 100 if best["win_rate"] <= 1 else best["win_rate"]
        dd = best["max_drawdown_pct"] * 100 if abs(best["max_drawdown_pct"]) < 1 else best["max_drawdown_pct"]
        logger.info(
            f"{best['symbol']:10s} | {best['strategy']:25s} | {best['exit_method']:15s} | "
            f"{best['total_trades']:6.0f} | {best['profit_factor']:6.2f} | "
            f"{wr:5.1f}% | {best['calmar_ratio']:8.2f} | {dd:6.1f}% | "
            f"${best['total_profit']:7.2f}"
        )

    # 2. Strategy comparison across all symbols
    logger.info("\n--- Strategy Average Performance Across All Symbols ---")
    for strat in strategy_map:
        strat_df = csv_df[csv_df["strategy"] == strat]
        if strat_df.empty:
            continue
        avg_pf = strat_df["profit_factor"].mean()
        avg_wr = strat_df["win_rate"].mean()
        avg_cal = strat_df["calmar_ratio"].mean()
        total_t = strat_df["total_trades"].sum()
        logger.info(f"  {strat:25s} | avg_PF={avg_pf:.2f} avg_WR={avg_wr*100:.1f}% "
                     f"avg_Calmar={avg_cal:.2f} total_trades={total_t:.0f}")

    # 3. Symbol ranking (best Calmar across all strats)
    logger.info("\n--- Symbol Ranking (Best Calmar per symbol) ---")
    sym_ranking = []
    for symbol in symbols:
        sym_df = csv_df[csv_df["symbol"] == symbol]
        if sym_df.empty:
            continue
        best_cal = sym_df["calmar_ratio"].max()
        best_row = sym_df.loc[sym_df["calmar_ratio"].idxmax()]
        sym_ranking.append({
            "symbol": symbol,
            "best_calmar": best_cal,
            "best_strategy": best_row["strategy"],
            "best_exit": best_row["exit_method"],
            "profit": best_row["total_profit"],
        })

    sym_ranking_df = pd.DataFrame(sym_ranking).sort_values("best_calmar", ascending=False)
    for _, row in sym_ranking_df.iterrows():
        logger.info(f"  {row['symbol']:10s} Calmar={row['best_calmar']:.2f} "
                     f"({row['best_strategy']}+{row['best_exit']}) "
                     f"profit=${row['profit']:.2f}")

    sym_ranking_df.to_csv(report_dir / "通貨ランキング.csv", index=False, encoding="utf-8-sig")

    # 4. Per-symbol full ranking
    for symbol in symbols:
        sym_df = csv_df[csv_df["symbol"] == symbol].sort_values("calmar_ratio", ascending=False)
        sym_df.to_csv(report_dir / f"{symbol}_ranking.csv", index=False, encoding="utf-8-sig")

    # 5. Strategy x Symbol matrix (Calmar)
    pivot = csv_df.pivot_table(
        values="calmar_ratio",
        index=["strategy", "exit_method"],
        columns="symbol",
        aggfunc="first",
    )
    pivot.to_csv(report_dir / "戦略x通貨マトリクス.csv", encoding="utf-8-sig")

    logger.info(f"\nReports saved to: {report_dir}")
    logger.info("Done!")


if __name__ == "__main__":
    main()
