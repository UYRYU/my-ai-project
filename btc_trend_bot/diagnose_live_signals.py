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
Uses PUBLIC Bitget data only — no API keys required.

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
from btc_trend_bot.live.bitget_feed import BitgetFeed
from btc_trend_bot.live.signal_engine import SignalEngine
from btc_trend_bot.live.risk_manager import RiskManager

from btc_trend_bot.run_multisymbol_backtest import ALL_SYMBOLS
from btc_trend_bot.run_multisymbol_live import (
    LIVE_MIN_ORDER_SIZE,
    LIVE_SIZE_STEP,
    _TIMEFRAME_DURATIONS,
    build_symbol_config_directional,
    drop_forming_bar,
)
from btc_trend_bot.run_multisymbol_paper import load_config


def _calc_size_noexec(
    config: dict,
    capital: float,
    entry: float,
    stop_loss: float,
    leverage: int,
    min_order_size: float,
    size_step: float,
) -> float:
    """Replicate LiveExecutor.calc_live_size without needing a futures client."""
    import math
    rm = RiskManager(config)
    risk_size = rm.calc_position_size(capital, entry, stop_loss)
    max_notional = capital * leverage
    max_size = max_notional / entry if entry > 0 else 0.0
    size = min(risk_size, max_size)
    if size_step > 0:
        size = math.floor(size / size_step) * size_step
    if size < min_order_size:
        return 0.0
    return size


def diagnose() -> None:
    load_env()
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")

    base_config = load_config()
    symbols = ALL_SYMBOLS
    capital_per_coin_side = 20.0
    leverage = 2

    logger.info("=" * 70)
    logger.info("DIAGNOSTIC — would the bot fire if a signal came in?")
    logger.info("(using public market data only, no API keys needed)")
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

            # Build the config the same way as the live runner
            sym_cfg, best_strat, best_exit = build_symbol_config_directional(
                base_config, symbol, capital_per_coin_side, direction,
            )
            sym_cfg["leverage"] = leverage

            # Build a signal engine directly (no futures client needed)
            signal_engine = SignalEngine(sym_cfg)
            timeframe = sym_cfg.get("timeframe", "1h")

            # Fetch data
            df = feed.get_latest_bars(timeframe=timeframe, count=500)
            if df is None or df.empty:
                logger.warning("  no data")
                continue

            # Log forming bar status
            bar_dur = _TIMEFRAME_DURATIONS.get(timeframe,
                                                pd.Timedelta(hours=1))
            raw_last = df.index[-1]
            raw_end = raw_last + bar_dur
            forming = raw_end > now
            logger.info("  raw_last_bar={} | end={} | now={} | forming={}",
                        raw_last, raw_end, now, forming)

            df = drop_forming_bar(df, timeframe)
            if df.empty:
                logger.warning("  df empty after drop")
                continue
            latest = df.index[-1]
            logger.info("  after drop: latest_bar={}", latest)

            # Load 4h if needed
            if signal_engine.needs_higher_tf:
                htf = feed.get_latest_bars(timeframe="4h", count=500)
                htf = drop_forming_bar(htf, "4h")
                if not htf.empty:
                    signal_engine.update_higher_tf(htf)

            # Run signal generation (no since filter)
            all_signals = signal_engine.process_bar_since(df, since=None)
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
                    size = _calc_size_noexec(
                        sym_cfg, capital_per_coin_side,
                        newest.entry_price, newest.stop_loss,
                        leverage,
                        LIVE_MIN_ORDER_SIZE.get(symbol, 0.001),
                        LIVE_SIZE_STEP.get(symbol, 0.001),
                    )
                    rm = RiskManager(sym_cfg)
                    allowed, reason = rm.check_trade_allowed(
                        capital_per_coin_side, capital_per_coin_side,
                        0.0, 0,
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
        logger.info("No pending live entries. Market conditions don't have")
        logger.info("any fresh signals in the last 3 bars on any symbol.")
        logger.info("This is expected if the market is sideways.")


if __name__ == "__main__":
    diagnose()
