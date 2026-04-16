"""
Live Signal Pipeline Diagnostic
================================
Fetches current market data for all 5 symbols, runs the full signal
pipeline (same as run_multisymbol_live.py), and reports:

- Latest bar time after drop_forming_bar
- All signals detected in the last 500 bars
- Signals within the last 3 bars (the fire window)
- Whether each would pass the risk/size/direction filters

Run this if the bot shows 0 trades and you want to know why.

Usage:
    python -m btc_trend_bot.diagnose_live_signals
"""

import copy
import os
import sys
from pathlib import Path

import pandas as pd
from loguru import logger

from btc_trend_bot.env_loader import load_env
from btc_trend_bot.exchange.bitget_futures import BitgetFuturesClient
from btc_trend_bot.exchange.models import ExchangeConfig
from btc_trend_bot.live.bitget_feed import BitgetFeed
from btc_trend_bot.live.live_executor import LiveExecutor

from btc_trend_bot.run_multisymbol_backtest import ALL_SYMBOLS
from btc_trend_bot.run_multisymbol_live import (
    LIVE_MIN_ORDER_SIZE,
    LIVE_SIZE_STEP,
    _TIMEFRAME_DURATIONS,
    build_futures_client,
    build_symbol_config_directional,
    drop_forming_bar,
)
from btc_trend_bot.run_multisymbol_paper import load_config


def diagnose() -> None:
    load_env()
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")

    base_config = load_config()
    symbols = ALL_SYMBOLS
    capital_per_coin_side = 20.0
    leverage = 2

    # Connect to Bitget (for position sizing, not placing orders)
    futures = build_futures_client()
    balance = futures.get_balance("USDT")
    logger.info("USDT balance: ${:.2f}", balance)

    logger.info("=" * 70)
    logger.info("DIAGNOSTIC — would the bot fire if a signal came in?")
    logger.info("=" * 70)

    now = pd.Timestamp.now(tz="UTC")
    logger.info("Current time (UTC): {}", now)

    total_would_fire = 0
    total_signals_ever = 0

    for symbol in symbols:
        # Build feed for this symbol
        ex_cfg = copy.deepcopy(base_config.get("exchange", {}))
        ex_cfg["symbol"] = symbol
        feed = BitgetFeed(ex_cfg)
        feed.symbol = symbol

        for direction in ["long", "short"]:
            key = f"{symbol}:{direction}"
            logger.info("-" * 70)
            logger.info("[{}]", key)

            # Build the config & executor the same way as the live runner
            sym_cfg, best_strat, best_exit = build_symbol_config_directional(
                base_config, symbol, capital_per_coin_side, direction,
            )
            sym_cfg["leverage"] = leverage

            executor = LiveExecutor(
                sym_cfg,
                futures_client=futures,
                min_order_size=LIVE_MIN_ORDER_SIZE.get(symbol, 0.001),
                size_step=LIVE_SIZE_STEP.get(symbol, 0.001),
            )

            # Fetch data
            df = feed.get_latest_bars(timeframe=executor.timeframe, count=500)
            if df is None or df.empty:
                logger.warning("  no data")
                continue

            # Log forming bar status
            bar_dur = _TIMEFRAME_DURATIONS.get(executor.timeframe,
                                                pd.Timedelta(hours=1))
            raw_last = df.index[-1]
            raw_end = raw_last + bar_dur
            forming = raw_end > now
            logger.info("  raw_last_bar={} | end={} | now={} | forming={}",
                        raw_last, raw_end, now, forming)

            df = drop_forming_bar(df, executor.timeframe)
            if df.empty:
                logger.warning("  df empty after drop")
                continue
            latest = df.index[-1]
            logger.info("  after drop: latest_bar={}", latest)

            # Load 4h if needed
            if executor.signal_engine.needs_higher_tf:
                htf = feed.get_latest_bars(timeframe="4h", count=500)
                htf = drop_forming_bar(htf, "4h")
                if not htf.empty:
                    executor.signal_engine.update_higher_tf(htf)

            # Run signal generation (no since filter)
            all_signals = executor.signal_engine.process_bar_since(
                df, since=None,
            )
            # Filter by direction
            matching = [
                s for s in all_signals
                if getattr(s, "direction", "long") == direction
            ]
            total_signals_ever += len(matching)
            logger.info("  total signals in history: {} | matching direction: {}",
                        len(all_signals), len(matching))

            if matching:
                # Show most recent 3
                recent = sorted(matching, key=lambda s: s.timestamp,
                                reverse=True)[:3]
                for s in recent:
                    age = (latest - s.timestamp).total_seconds() / 3600
                    logger.info("    {} @ {} entry={:.4f} sl={:.4f} "
                                "(age={:.1f}h)",
                                s.strategy_name, s.timestamp,
                                s.entry_price, s.stop_loss, age)

                # Would the newest fire?
                cutoff = latest - 3 * bar_dur
                newest = recent[0]
                if newest.timestamp >= cutoff:
                    # Check size
                    size = executor.calc_live_size(
                        executor.capital,
                        newest.entry_price,
                        newest.stop_loss,
                    )
                    allowed, reason = executor.risk_manager.check_trade_allowed(
                        executor.capital, executor.peak_equity,
                        executor.daily_pnl, 0,
                    )
                    if size > 0 and allowed:
                        logger.success(
                            "  => WOULD FIRE: {} @ {} size={}",
                            newest.strategy_name, newest.timestamp, size,
                        )
                        total_would_fire += 1
                    else:
                        logger.warning(
                            "  => signal at {} is fresh but blocked: "
                            "size={}, allowed={} ({})",
                            newest.timestamp, size, allowed, reason,
                        )
                else:
                    age_h = (latest - newest.timestamp).total_seconds() / 3600
                    logger.info(
                        "  => no fire: newest signal age {:.1f}h > cutoff "
                        "({} bars)", age_h, 3,
                    )

    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info("Total historical signals across 10 executors : {}",
                total_signals_ever)
    logger.info("Executors that WOULD fire right now          : {}/10",
                total_would_fire)
    if total_would_fire == 0:
        logger.info("")
        logger.info("No live bot execution pending. Market conditions don't")
        logger.info("have any fresh signals in the last 3 bars on any symbol.")
        logger.info("This is expected if the market is sideways.")


if __name__ == "__main__":
    diagnose()
