"""
Multi-Symbol SHORT Backtest Runner
===================================
Run short strategies (breakdown_confirmed, multi_tf_trend_hold_short) across
BTC, ETH, XRP, DOGE, SOL. Same infrastructure as the long backtest runner
with direction-aware engine + exit manager.

Usage:
    python -m btc_trend_bot.run_multisymbol_backtest_short
    python -m btc_trend_bot.run_multisymbol_backtest_short --symbols BTCUSDT,ETHUSDT
"""

import argparse
import copy
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

from btc_trend_bot.run_multisymbol_backtest import (
    COIN_CONFIGS,
    ALL_SYMBOLS,
    load_config,
)

# ---------------------------------------------------------------
# Short-side strategies
# ---------------------------------------------------------------
SHORT_STRATEGIES = ["breakdown_confirmed", "multi_tf_trend_hold_short"]
SHORT_EXIT_METHODS = ["partial_trail", "atr_trailing"]


def _get_short_strategy_classes() -> dict:
    from btc_trend_bot.strategies.trend_short.breakdown_confirmed import (
        BreakdownConfirmedStrategy,
    )
    from btc_trend_bot.strategies.trend_short.multi_tf_trend_hold_short import (
        MultiTFTrendHoldShortStrategy,
    )
    return {
        "breakdown_confirmed": BreakdownConfirmedStrategy,
        "multi_tf_trend_hold_short": MultiTFTrendHoldShortStrategy,
    }


# Per-symbol overrides — optimized via parameter sweep
SYMBOL_SHORT_STRATEGY_OVERRIDES: dict[str, dict[str, dict]] = {
    # BTC: mtf_short with default strat params (s0) is best
    "ETHUSDT": {
        "breakdown_confirmed": {
            "adx_min": 18,
            "bar_strength_min": 0.6,
        },
    },
    "XRPUSDT": {
        "breakdown_confirmed": {
            "adx_min": 18,
            "bar_strength_min": 0.6,
        },
    },
    "DOGEUSDT": {
        "breakdown_confirmed": {
            "adx_min": 18,
            "volume_mult": 1.1,
            "atr_sl_mult": 2.0,
            "bar_strength_min": 0.6,
        },
    },
    "SOLUSDT": {
        "breakdown_confirmed": {
            "adx_min": 18,
            "volume_mult": 1.1,
            "atr_sl_mult": 2.0,
            "bar_strength_min": 0.6,
        },
    },
}

SYMBOL_SHORT_EXIT_OVERRIDES: dict[str, dict] = {
    "BTCUSDT": {
        "partial_trail": {
            "first_tp_rr": 2.0,
            "first_tp_pct": 50.0,
            "trail_atr_mult": 1.3,
        },
    },
    "ETHUSDT": {
        "partial_trail": {
            "first_tp_rr": 2.0,
            "first_tp_pct": 50.0,
            "trail_atr_mult": 1.3,
        },
    },
    "XRPUSDT": {
        "partial_trail": {
            "first_tp_rr": 2.5,
            "first_tp_pct": 40.0,
            "trail_atr_mult": 1.5,
        },
    },
    "DOGEUSDT": {
        "partial_trail": {
            "first_tp_rr": 2.0,
            "first_tp_pct": 50.0,
            "trail_atr_mult": 1.3,
        },
    },
    "SOLUSDT": {
        "partial_trail": {
            "first_tp_rr": 2.0,
            "first_tp_pct": 50.0,
            "trail_atr_mult": 1.3,
        },
    },
}

BEST_SHORT_STRATEGY_PER_SYMBOL: dict[str, tuple[str, str]] = {
    "BTCUSDT":  ("multi_tf_trend_hold_short", "partial_trail"),
    "ETHUSDT":  ("breakdown_confirmed",       "partial_trail"),
    "XRPUSDT":  ("breakdown_confirmed",       "partial_trail"),
    "DOGEUSDT": ("breakdown_confirmed",       "partial_trail"),
    "SOLUSDT":  ("breakdown_confirmed",       "partial_trail"),
}


def run_single_short(
    symbol: str,
    strategy_name: str,
    strategy_class,
    df: pd.DataFrame,
    config: dict,
    exit_method: str,
) -> dict | None:
    """Run one short strategy + exit on one symbol."""
    strat_config = dict(config.get("strategies", {}).get(strategy_name, {}))
    sym_overrides = SYMBOL_SHORT_STRATEGY_OVERRIDES.get(symbol, {}).get(strategy_name, {})
    strat_config.update(sym_overrides)

    strategy = strategy_class(strat_config)
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

    exit_config = copy.deepcopy(config.get("exit", {}))
    exit_config["method"] = exit_method
    sym_exit_overrides = SYMBOL_SHORT_EXIT_OVERRIDES.get(symbol, {}).get(exit_method, {})
    if sym_exit_overrides:
        exit_sub = exit_config.get(exit_method, {})
        exit_sub.update(sym_exit_overrides)
        exit_config[exit_method] = exit_sub

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
        "equity_curve": result.equity_curve,
        "trades_df": result.trades,
    }


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Multi-Symbol SHORT Backtest")
    parser.add_argument("--symbols", type=str, default=None)
    parser.add_argument("--strategy", type=str, default=None)
    parser.add_argument("--exit", type=str, default=None)
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")

    config = load_config(args.config)
    symbols = args.symbols.split(",") if args.symbols else ALL_SYMBOLS
    strategies_to_test = [args.strategy] if args.strategy else SHORT_STRATEGIES
    exit_methods = [args.exit] if args.exit else SHORT_EXIT_METHODS

    strategy_classes = _get_short_strategy_classes()

    logger.info("=" * 70)
    logger.info("MULTI-SYMBOL SHORT BACKTEST")
    logger.info("=" * 70)
    logger.info(f"Symbols: {', '.join(symbols)}")
    logger.info(f"Strategies: {', '.join(strategies_to_test)}")
    logger.info(f"Exit methods: {', '.join(exit_methods)}")
    leverage = config.get("backtest", {}).get("leverage", 1)
    logger.info(f"Leverage: {leverage}x")
    logger.info("=" * 70)

    fe = FeatureEngineer()
    all_results: list[dict] = []

    for symbol in symbols:
        logger.info(f"\n{'='*50}")
        logger.info(f"  {symbol}")
        logger.info(f"{'='*50}")

        # Load data
        data_dir = Path(__file__).parent / "data" / "raw"
        csv_path = data_dir / f"{symbol}_1h.csv"
        if not csv_path.exists():
            logger.warning(f"No data for {symbol} at {csv_path}, skipping")
            continue

        loader = DataLoader()
        df = loader.load_csv(str(csv_path))
        if df is None or df.empty:
            logger.warning(f"Empty data for {symbol}")
            continue

        df = fe.add_all_features(df)
        logger.info(f"  Loaded {len(df)} bars, features added")

        for strat_name in strategies_to_test:
            cls = strategy_classes.get(strat_name)
            if cls is None:
                logger.warning(f"  Unknown strategy: {strat_name}")
                continue

            for exit_method in exit_methods:
                result = run_single_short(
                    symbol, strat_name, cls, df, config, exit_method
                )
                if result is None:
                    continue
                all_results.append(result)

                trades = result["total_trades"]
                pf = result.get("profit_factor", 0)
                wr = result.get("win_rate", 0)
                calmar = result.get("calmar_ratio", 0)
                profit = result.get("total_profit", 0)
                dd = result.get("max_drawdown_pct", 0)

                logger.info(
                    f"  {strat_name:30s} | {exit_method:15s} | "
                    f"trades={trades:3d} WR={wr:5.1f}% PF={pf:5.2f} "
                    f"Calmar={calmar:6.2f} DD={dd:5.1f}% "
                    f"P&L=${profit:+.2f}"
                )

    # Summary table
    logger.info(f"\n{'='*70}")
    logger.info("SHORT BACKTEST SUMMARY")
    logger.info(f"{'='*70}")
    logger.info(
        f"{'Symbol':10s} {'Strategy':30s} {'Exit':15s} "
        f"{'Trades':>6s} {'WR%':>6s} {'PF':>6s} {'Calmar':>7s} {'DD%':>6s} {'P&L':>8s}"
    )
    logger.info("-" * 100)

    for r in all_results:
        if r["total_trades"] > 0:
            logger.info(
                f"{r['symbol']:10s} {r['strategy']:30s} {r['exit_method']:15s} "
                f"{r['total_trades']:6d} {r.get('win_rate', 0):5.1f}% "
                f"{r.get('profit_factor', 0):5.2f} {r.get('calmar_ratio', 0):6.2f} "
                f"{r.get('max_drawdown_pct', 0):5.1f}% ${r.get('total_profit', 0):+7.2f}"
            )

    return all_results


if __name__ == "__main__":
    main()
