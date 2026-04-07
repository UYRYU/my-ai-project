"""
Multi-Symbol Paper Trading Runner
==================================
Run paper trading on BTC, ETH, XRP, DOGE, SOL simultaneously from the
same $100 account ($20 per coin). Uses the best strategy per coin with
per-symbol parameter overrides (same logic as run_multisymbol_backtest).

Usage:
    python -m btc_trend_bot.run_multisymbol_paper
    python -m btc_trend_bot.run_multisymbol_paper --interval 300
    python -m btc_trend_bot.run_multisymbol_paper --symbols BTCUSDT,ETHUSDT
"""

import argparse
import copy
import sys
import time
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger

from btc_trend_bot.env_loader import load_env
from btc_trend_bot.live.paper_executor import PaperExecutor
from btc_trend_bot.live.bitget_feed import BitgetFeed

# Reuse per-symbol overrides from the backtest runner
from btc_trend_bot.run_multisymbol_backtest import (
    COIN_CONFIGS,
    ALL_SYMBOLS,
    BEST_STRATEGY_PER_SYMBOL,
    SYMBOL_STRATEGY_OVERRIDES,
    SYMBOL_EXIT_OVERRIDES,
)


def load_config(config_path: str | None = None) -> dict:
    config_file = Path(__file__).parent / "config" / "settings.yaml"
    if config_path:
        config_file = Path(config_path)
    if not config_file.exists():
        return {}
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_symbol_config(
    base_config: dict,
    symbol: str,
    capital_per_coin: float,
) -> dict:
    """Build a per-symbol paper_trading config with overrides applied."""
    cfg = copy.deepcopy(base_config.get("paper_trading", {}))

    # Determine best strategy + exit for this symbol
    best_strat, best_exit = BEST_STRATEGY_PER_SYMBOL.get(
        symbol, ("breakout_confirmed", "partial_trail")
    )

    cfg["symbol"] = symbol
    cfg["initial_capital"] = capital_per_coin
    cfg["enabled_strategies"] = [best_strat]
    cfg["state_file"] = f"data/paper_state_{symbol}.json"

    # Apply per-symbol strategy parameter overrides
    strategies = copy.deepcopy(base_config.get("strategies", {}))
    sym_strat_overrides = SYMBOL_STRATEGY_OVERRIDES.get(symbol, {}).get(best_strat, {})
    if sym_strat_overrides:
        strategies.setdefault(best_strat, {}).update(sym_strat_overrides)
    cfg["strategies"] = strategies

    # Apply per-symbol exit overrides
    exit_cfg = copy.deepcopy(base_config.get("exit", {}))
    exit_cfg["method"] = best_exit
    sym_exit_overrides = SYMBOL_EXIT_OVERRIDES.get(symbol, {}).get(best_exit, {})
    if sym_exit_overrides:
        exit_sub = exit_cfg.get(best_exit, {})
        exit_sub.update(sym_exit_overrides)
        exit_cfg[best_exit] = exit_sub
    cfg["exit"] = exit_cfg

    # Pass through trend detection
    cfg["trend_detection"] = base_config.get("trend_detection", {})

    return cfg, best_strat, best_exit


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Multi-Symbol Paper Trading")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbols (default: all 5)")
    parser.add_argument("--interval", type=int, default=300,
                        help="Polling interval in seconds (default: 300 = 5min)")
    parser.add_argument("--total-capital", type=float, default=100.0,
                        help="Total account capital (default: 100)")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    # Logging
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(str(log_dir / "multisymbol_paper.log"), rotation="10 MB", level="DEBUG")

    base_config = load_config(args.config)

    symbols = args.symbols.split(",") if args.symbols else ALL_SYMBOLS
    capital_per_coin = args.total_capital / len(symbols)

    leverage = base_config.get("backtest", {}).get("leverage", 1)

    logger.info("=" * 70)
    logger.info("MULTI-SYMBOL PAPER TRADING")
    logger.info("=" * 70)
    logger.info(f"Total capital: ${args.total_capital:.2f}")
    logger.info(f"Per-coin allocation: ${capital_per_coin:.2f}")
    logger.info(f"Leverage: {leverage}x")
    logger.info(f"Polling interval: {args.interval}s")
    logger.info(f"Symbols: {', '.join(symbols)}")
    logger.info("=" * 70)

    # Build executor + feed per symbol
    executors: dict[str, PaperExecutor] = {}
    feeds: dict[str, BitgetFeed] = {}

    for symbol in symbols:
        sym_cfg, best_strat, best_exit = build_symbol_config(
            base_config, symbol, capital_per_coin
        )

        logger.info(f"\nInitialising {symbol}:")
        logger.info(f"  Strategy: {best_strat}")
        logger.info(f"  Exit: {best_exit}")
        logger.info(f"  Capital: ${capital_per_coin:.2f}")
        logger.info(f"  State file: {sym_cfg['state_file']}")

        executor = PaperExecutor(sym_cfg)
        executors[symbol] = executor

        # Feed with the correct symbol
        exchange_cfg = copy.deepcopy(base_config.get("exchange", {}))
        exchange_cfg["symbol"] = symbol
        feed = BitgetFeed(exchange_cfg)
        feed.symbol = symbol  # ensure symbol is set correctly
        feeds[symbol] = feed

    logger.info("\n" + "=" * 70)
    logger.info("Starting polling loop (Ctrl+C to stop)")
    logger.info("=" * 70)

    # Fetch initial higher TF data where needed
    for symbol, executor in executors.items():
        if executor.signal_engine.needs_higher_tf:
            try:
                htf = feeds[symbol].get_latest_bars(timeframe="4h", count=500)
                if not htf.empty:
                    executor.signal_engine.update_higher_tf(htf)
                    logger.info(f"[{symbol}] Loaded {len(htf)} bars of 4h data")
            except Exception as exc:
                logger.error(f"[{symbol}] Failed to fetch 4h data: {exc}")

    htf_refresh_counter = 0
    htf_refresh_interval = 4  # refresh 4h every 4 cycles

    try:
        while True:
            cycle_start = time.time()

            for symbol, executor in executors.items():
                feed = feeds[symbol]
                try:
                    df = feed.get_latest_bars(timeframe=executor.timeframe, count=500)
                    if df is None or df.empty:
                        logger.warning(f"[{symbol}] No data received")
                        continue

                    # Refresh 4h data if needed
                    if executor.signal_engine.needs_higher_tf and htf_refresh_counter >= htf_refresh_interval:
                        try:
                            htf = feed.get_latest_bars(timeframe="4h", count=500)
                            if not htf.empty:
                                executor.signal_engine.update_higher_tf(htf)
                        except Exception as exc:
                            logger.warning(f"[{symbol}] 4h refresh failed: {exc}")

                    current_price = float(df.iloc[-1]["close"])

                    # Check exits on open position
                    closed = executor.position_manager.update_price(current_price)
                    for trade in closed:
                        executor.capital += trade["pnl"]
                        executor.state_store.add_trade(trade)
                        logger.info(
                            f"[{symbol}] CLOSED: PnL=${trade['pnl']:.2f} "
                            f"({trade.get('exit_reason', '?')})"
                        )

                    # Check new signals
                    if not executor.position_manager.has_open_position(symbol):
                        signals = executor.signal_engine.process_bar(df)
                        for signal in signals:
                            allowed, reason = executor.risk_manager.check_signal(
                                signal, executor.capital, executor.peak_equity, executor.daily_pnl
                            )
                            if allowed:
                                position = executor.position_manager.open_position(
                                    symbol, signal, executor.capital
                                )
                                if position:
                                    logger.info(
                                        f"[{symbol}] OPEN: {signal.strategy_name} "
                                        f"@ ${signal.entry_price:.4f} SL=${signal.stop_loss:.4f}"
                                    )
                            else:
                                logger.debug(f"[{symbol}] Signal rejected: {reason}")

                    # Save state
                    executor.state_store.update(
                        capital=executor.capital,
                        positions=executor.position_manager.to_dict(),
                    )

                except Exception as exc:
                    logger.error(f"[{symbol}] Cycle error: {exc}")

            # Summary of all symbols
            total_capital = sum(e.capital for e in executors.values())
            n_open = sum(
                1 for e in executors.values()
                if e.position_manager.has_open_position(e.symbol)
            )
            logger.info(
                f"--- Portfolio: ${total_capital:.2f} "
                f"({n_open} open positions) ---"
            )

            htf_refresh_counter = (htf_refresh_counter + 1) % (htf_refresh_interval + 1)

            # Sleep for remainder of interval
            elapsed = time.time() - cycle_start
            sleep_time = max(0, args.interval - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("\n" + "=" * 70)
        logger.info("STOPPED by user. Final summary:")
        logger.info("=" * 70)
        total = 0.0
        for symbol, executor in executors.items():
            pnl = executor.capital - capital_per_coin
            total += executor.capital
            logger.info(
                f"  {symbol:10s}: ${executor.capital:7.2f} "
                f"(PnL ${pnl:+.2f})"
            )
        total_pnl = total - args.total_capital
        ret_pct = (total_pnl / args.total_capital) * 100
        logger.info(f"  {'TOTAL':10s}: ${total:7.2f} "
                    f"(PnL ${total_pnl:+.2f}, {ret_pct:+.2f}%)")


if __name__ == "__main__":
    main()
