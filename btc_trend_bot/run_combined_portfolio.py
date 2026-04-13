"""
Combined Long + Short Portfolio Backtest
=========================================
Runs both long and short strategies on 5 coins, combines equity curves,
and reports comprehensive stats at $100 and $500 capital levels.

Includes: trades/yr, trades/mo, cumulative PnL, max DD, compound vs simple.
Bitget USDT-M futures fees applied (0.06% taker).

Usage:
    python -m btc_trend_bot.run_combined_portfolio
"""

import copy
import sys
from pathlib import Path

import numpy as np
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
    BEST_STRATEGY_PER_SYMBOL,
    SYMBOL_STRATEGY_OVERRIDES,
    SYMBOL_EXIT_OVERRIDES,
    load_config,
)
from btc_trend_bot.run_multisymbol_backtest_short import (
    BEST_SHORT_STRATEGY_PER_SYMBOL,
    SYMBOL_SHORT_STRATEGY_OVERRIDES,
    SYMBOL_SHORT_EXIT_OVERRIDES,
)


def _get_all_strategy_classes() -> dict:
    """All long + short strategy classes."""
    from btc_trend_bot.strategies.trend_long.breakout_confirmed import BreakoutConfirmedStrategy
    from btc_trend_bot.strategies.trend_long.multi_tf_trend_hold import MultiTFTrendHoldStrategy
    from btc_trend_bot.strategies.trend_short.breakdown_confirmed import BreakdownConfirmedStrategy
    from btc_trend_bot.strategies.trend_short.multi_tf_trend_hold_short import MultiTFTrendHoldShortStrategy

    return {
        "breakout_confirmed": BreakoutConfirmedStrategy,
        "multi_tf_trend_hold": MultiTFTrendHoldStrategy,
        "breakdown_confirmed": BreakdownConfirmedStrategy,
        "multi_tf_trend_hold_short": MultiTFTrendHoldShortStrategy,
    }


def run_single(symbol, strat_name, strat_cls, df, config, exit_method,
               strat_overrides, exit_overrides):
    strat_config = dict(config.get("strategies", {}).get(strat_name, {}))
    sym_so = strat_overrides.get(symbol, {}).get(strat_name, {})
    strat_config.update(sym_so)

    strategy = strat_cls(strat_config)
    signals = strategy.generate_signals(df)
    if not signals:
        return None

    exit_config = copy.deepcopy(config.get("exit", {}))
    exit_config["method"] = exit_method
    sym_eo = exit_overrides.get(symbol, {}).get(exit_method, {})
    if sym_eo:
        exit_sub = exit_config.get(exit_method, {})
        exit_sub.update(sym_eo)
        exit_config[exit_method] = exit_sub

    em = ExitManager(exit_config)
    bt_config = dict(config.get("backtest", {}))
    bt_config["min_order_size"] = COIN_CONFIGS.get(symbol, {}).get("min_order_size", 0.001)

    engine = BacktestEngine(bt_config)
    result = engine.run(df, signals, em)
    return result


def scale_equity(eq: pd.Series, per_coin_alloc: float) -> pd.Series:
    """Scale equity curve from backtest capital to per-coin allocation."""
    bt_initial = eq.iloc[0] if len(eq) > 0 else 100.0
    if bt_initial == 0:
        return eq
    return eq * (per_coin_alloc / bt_initial)


def calc_compound_return(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] == 0:
        return 0.0
    return (equity.iloc[-1] / equity.iloc[0] - 1) * 100


def calc_max_dd(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = (equity - peak) / peak * 100
    return abs(dd.min()) if len(dd) > 0 else 0.0


def calc_annualized(total_return_pct: float, days: int) -> float:
    if days <= 0 or total_return_pct <= -100:
        return 0.0
    return ((1 + total_return_pct / 100) ** (365.0 / days) - 1) * 100


def main():
    load_env()
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")

    config = load_config()
    strategy_classes = _get_all_strategy_classes()
    fe = FeatureEngineer()

    leverage = config.get("backtest", {}).get("leverage", 2)

    logger.info("=" * 70)
    logger.info("COMBINED LONG + SHORT PORTFOLIO BACKTEST")
    logger.info(f"Leverage: {leverage}x | Fee: 0.06% taker | Symbols: {len(ALL_SYMBOLS)}")
    logger.info("=" * 70)

    # Load all data
    data = {}
    for symbol in ALL_SYMBOLS:
        csv = Path(__file__).parent / "data" / "raw" / f"{symbol}_1h.csv"
        if not csv.exists():
            continue
        loader = DataLoader()
        df = loader.load_csv(str(csv))
        df = fe.add_all_features(df)
        data[symbol] = df

    # ---------------------------------------------------------------
    # Run all strategies (long + short) per symbol
    # ---------------------------------------------------------------
    results = {}  # key: (symbol, "long"|"short")

    for symbol in ALL_SYMBOLS:
        df = data.get(symbol)
        if df is None:
            continue

        # Long
        ls, le = BEST_STRATEGY_PER_SYMBOL.get(symbol, ("breakout_confirmed", "partial_trail"))
        cls = strategy_classes.get(ls)
        if cls:
            r = run_single(symbol, ls, cls, df, config, le,
                           SYMBOL_STRATEGY_OVERRIDES, SYMBOL_EXIT_OVERRIDES)
            if r and r.metrics.get("total_trades", 0) > 0:
                results[(symbol, "long")] = r

        # Short
        ss, se = BEST_SHORT_STRATEGY_PER_SYMBOL.get(symbol, ("breakdown_confirmed", "partial_trail"))
        cls = strategy_classes.get(ss)
        if cls:
            r = run_single(symbol, ss, cls, df, config, se,
                           SYMBOL_SHORT_STRATEGY_OVERRIDES, SYMBOL_SHORT_EXIT_OVERRIDES)
            if r and r.metrics.get("total_trades", 0) > 0:
                results[(symbol, "short")] = r

    # ---------------------------------------------------------------
    # Per-symbol summary
    # ---------------------------------------------------------------
    logger.info("")
    logger.info(f"{'Symbol':10s} {'Dir':6s} {'Strategy':30s} {'Trades':>6s} {'WR%':>6s} "
                f"{'PF':>6s} {'Calmar':>7s} {'DD%':>6s} {'P&L':>8s}")
    logger.info("-" * 90)

    all_trades_long = 0
    all_trades_short = 0
    for (symbol, direction), r in sorted(results.items()):
        m = r.metrics
        t = m.get("total_trades", 0)
        if direction == "long":
            all_trades_long += t
        else:
            all_trades_short += t
        logger.info(
            f"{symbol:10s} {direction:6s} "
            f"{BEST_STRATEGY_PER_SYMBOL.get(symbol, ('?','?'))[0] if direction == 'long' else BEST_SHORT_STRATEGY_PER_SYMBOL.get(symbol, ('?','?'))[0]:30s} "
            f"{t:6d} {m.get('win_rate', 0):5.1f}% "
            f"{m.get('profit_factor', 0):5.2f} {m.get('calmar_ratio', 0):6.2f} "
            f"{m.get('max_drawdown_pct', 0):5.1f}% ${m.get('total_profit', 0):+7.2f}"
        )

    # ---------------------------------------------------------------
    # Portfolio simulation for $100 and $500
    # ---------------------------------------------------------------
    for total_capital in [100.0, 500.0]:
        n_coins = len(ALL_SYMBOLS)
        # Split: half for long, half for short per coin
        per_coin_per_side = total_capital / (n_coins * 2)

        combined_equities = []
        total_trade_count = 0
        all_trade_records = []

        for symbol in ALL_SYMBOLS:
            for direction in ["long", "short"]:
                key = (symbol, direction)
                r = results.get(key)
                if r is None or r.equity_curve is None:
                    continue
                eq = scale_equity(r.equity_curve, per_coin_per_side)
                combined_equities.append(eq)
                total_trade_count += r.metrics.get("total_trades", 0)
                if r.trades is not None and len(r.trades) > 0:
                    all_trade_records.append(r.trades)

        if not combined_equities:
            continue

        # Align all equity series to common index and sum
        all_eq = pd.concat(combined_equities, axis=1).ffill().bfill()
        portfolio_eq = all_eq.sum(axis=1)

        # Stats
        initial = total_capital
        final = portfolio_eq.iloc[-1]
        total_pnl = final - initial
        total_return_pct = (total_pnl / initial) * 100
        max_dd = calc_max_dd(portfolio_eq)

        # Duration
        if isinstance(portfolio_eq.index, pd.DatetimeIndex):
            days = (portfolio_eq.index[-1] - portfolio_eq.index[0]).days
        else:
            days = len(portfolio_eq) / 24  # approx hours to days
        months = days / 30.44
        years = days / 365.25

        ann_return = calc_annualized(total_return_pct, int(days))

        # Simple return projection
        simple_annual_pnl = total_pnl / years if years > 0 else 0
        simple_annual_pct = total_return_pct / years if years > 0 else 0

        # Compound (already in the equity curve since engine reinvests)
        compound_annual_pct = ann_return

        trades_per_year = total_trade_count / years if years > 0 else 0
        trades_per_month = total_trade_count / months if months > 0 else 0

        # Calmar
        calmar = ann_return / max_dd if max_dd > 0 else 0

        logger.info("")
        logger.info("=" * 70)
        logger.info(f"PORTFOLIO: ${total_capital:.0f} | {n_coins} coins | Long+Short | {leverage}x lever")
        logger.info("=" * 70)
        logger.info(f"  Period             : {days:.0f} days ({years:.2f} years)")
        logger.info(f"  Total trades       : {total_trade_count} "
                    f"(Long: {all_trades_long}, Short: {all_trades_short})")
        logger.info(f"  Trades / year      : {trades_per_year:.1f}")
        logger.info(f"  Trades / month     : {trades_per_month:.1f}")
        logger.info(f"  Final equity       : ${final:.2f}")
        logger.info(f"  Cumulative P&L     : ${total_pnl:+.2f} ({total_return_pct:+.1f}%)")
        logger.info(f"  Max Drawdown       : {max_dd:.1f}%")
        logger.info(f"  Calmar Ratio       : {calmar:.2f}")
        logger.info("")
        logger.info(f"  --- SIMPLE (linear) ---")
        logger.info(f"  Annual P&L         : ${simple_annual_pnl:+.2f}/yr")
        logger.info(f"  Annual Return      : {simple_annual_pct:+.1f}%/yr")
        logger.info("")
        logger.info(f"  --- COMPOUND (reinvested) ---")
        logger.info(f"  Annualized Return  : {compound_annual_pct:+.1f}%/yr")
        logger.info(f"  2yr projection     : ${initial * (1 + compound_annual_pct/100)**2:.2f}")
        logger.info(f"  3yr projection     : ${initial * (1 + compound_annual_pct/100)**3:.2f}")
        logger.info("=" * 70)


if __name__ == "__main__":
    main()
