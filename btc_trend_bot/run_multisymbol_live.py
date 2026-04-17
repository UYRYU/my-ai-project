"""
Multi-Symbol LIVE Trading Runner — Long + Short (REAL MONEY)
============================================================
Runs long AND short strategies on BTC, ETH, XRP, DOGE, SOL simultaneously
from the same Bitget USDT-M Futures account.

Capital allocation:
    $100 total → $10 per coin per side (5 coins × 2 sides)
    Simple interest: position sizing always uses the initial $10 allocation,
    profits are tracked but NOT compounded into bigger positions.

Defaults: $100 total / 2x leverage / -10% daily kill switch.

USAGE:
    python -m btc_trend_bot.run_multisymbol_live
    python -m btc_trend_bot.run_multisymbol_live --symbols BTCUSDT,ETHUSDT
    python -m btc_trend_bot.run_multisymbol_live --total-capital 100 --interval 300
    python -m btc_trend_bot.run_multisymbol_live --yes   # skip confirmation

This script REQUIRES typing 'yes' at startup to acknowledge real-money mode.
"""

import argparse
import copy
import os
import sys
import time
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger

from btc_trend_bot.env_loader import load_env
from btc_trend_bot.exchange.bitget_futures import BitgetFuturesClient
from btc_trend_bot.exchange.models import ExchangeConfig
from btc_trend_bot.live.bitget_feed import BitgetFeed
from btc_trend_bot.live.live_executor import LiveExecutor

from btc_trend_bot.run_multisymbol_backtest import (
    COIN_CONFIGS,
    ALL_SYMBOLS,
    BEST_STRATEGY_PER_SYMBOL,
    SYMBOL_STRATEGY_OVERRIDES,
    SYMBOL_EXIT_OVERRIDES,
)
from btc_trend_bot.run_multisymbol_backtest_short import (
    BEST_SHORT_STRATEGY_PER_SYMBOL,
    SYMBOL_SHORT_STRATEGY_OVERRIDES,
    SYMBOL_SHORT_EXIT_OVERRIDES,
)
from btc_trend_bot.run_multisymbol_paper import load_config


# Bitget futures actual minimums (USDT-M perpetual).
LIVE_MIN_ORDER_SIZE = {
    "BTCUSDT":  0.0001,
    "ETHUSDT":  0.01,
    "XRPUSDT":  1.0,
    "DOGEUSDT": 1.0,
    "SOLUSDT":  0.01,
}
LIVE_SIZE_STEP = {
    "BTCUSDT":  0.0001,
    "ETHUSDT":  0.01,
    "XRPUSDT":  1.0,
    "DOGEUSDT": 1.0,
    "SOLUSDT":  0.01,
}


# Timeframe string → pandas offset for forming-bar detection
_TIMEFRAME_DURATIONS = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}


def drop_forming_bar(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Drop the last bar if it is still forming (end time in the future).

    Bitget's candles endpoint returns the current in-progress bar as the
    most recent entry, which causes the live signal engine's "latest-bar"
    filter to miss confirmed signals (signal is at bar N-1 but latest
    is at bar N which is forming).
    """
    if df is None or df.empty:
        return df
    bar_dur = _TIMEFRAME_DURATIONS.get(timeframe)
    if bar_dur is None:
        return df
    now = pd.Timestamp.now(tz="UTC")
    last_bar_start = df.index[-1]
    # If last bar's end is still in the future, it's forming → drop it
    if last_bar_start + bar_dur > now:
        return df.iloc[:-1]
    return df


def confirm_live_mode(total_capital: float, leverage: int,
                      symbols: list[str], daily_loss_limit: float) -> bool:
    per_coin = total_capital / len(symbols)
    print()
    print("=" * 70)
    print("  ⚠️  LIVE TRADING MODE — REAL MONEY (LONG + SHORT)  ⚠️")
    print("=" * 70)
    print(f"  Account capital    : ${total_capital:.2f} USDT")
    print(f"  Per-coin (L+S)     : ${per_coin:.2f}")
    print(f"  Leverage           : {leverage}x")
    print(f"  Symbols            : {', '.join(symbols)}")
    print(f"  Directions         : LONG + SHORT")
    print(f"  Sizing mode        : Simple interest (fixed $100)")
    print(f"  Daily kill-switch  : -${daily_loss_limit:.2f} "
          f"({daily_loss_limit / total_capital * 100:.0f}%)")
    print("=" * 70)
    print()
    print("Type 'yes' to start live trading, anything else to abort:")
    try:
        answer = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer == "yes"


def build_futures_client() -> BitgetFuturesClient:
    api_key = os.environ.get("BITGET_API_KEY", "")
    api_secret = os.environ.get("BITGET_API_SECRET", "")
    passphrase = os.environ.get("BITGET_PASSPHRASE", "")
    if not (api_key and api_secret and passphrase):
        raise RuntimeError(
            "BITGET_API_KEY / BITGET_API_SECRET / BITGET_PASSPHRASE must be "
            "set in .env for live trading."
        )

    cfg = ExchangeConfig(
        exchange_name="bitget",
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        testnet=False,                 # LIVE
        base_url="https://api.bitget.com",
        product_type="USDT-FUTURES",
        margin_mode="crossed",
    )
    return BitgetFuturesClient(cfg, live_confirmed=True)


def build_symbol_config_directional(
    base_config: dict,
    symbol: str,
    capital_per_coin_side: float,
    direction: str,
) -> tuple[dict, str, str]:
    """Build per-symbol config for a specific direction (long or short)."""
    cfg = copy.deepcopy(base_config.get("paper_trading", {}))

    if direction == "short":
        best_strat, best_exit = BEST_SHORT_STRATEGY_PER_SYMBOL.get(
            symbol, ("breakdown_confirmed", "partial_trail")
        )
        strat_overrides = SYMBOL_SHORT_STRATEGY_OVERRIDES
        exit_overrides = SYMBOL_SHORT_EXIT_OVERRIDES
    else:
        best_strat, best_exit = BEST_STRATEGY_PER_SYMBOL.get(
            symbol, ("breakout_confirmed", "partial_trail")
        )
        strat_overrides = SYMBOL_STRATEGY_OVERRIDES
        exit_overrides = SYMBOL_EXIT_OVERRIDES

    cfg["symbol"] = symbol
    cfg["direction"] = direction
    cfg["initial_capital"] = capital_per_coin_side
    cfg["simple_interest"] = True  # fixed $100 sizing
    cfg["enabled_strategies"] = [best_strat]
    cfg["state_file"] = f"data/live_state_{symbol}_{direction}.json"

    # Strategy param overrides
    strategies = copy.deepcopy(base_config.get("strategies", {}))
    sym_strat_overrides = strat_overrides.get(symbol, {}).get(best_strat, {})
    if sym_strat_overrides:
        strategies.setdefault(best_strat, {}).update(sym_strat_overrides)
    cfg["strategies"] = strategies

    # Exit overrides
    exit_cfg = copy.deepcopy(base_config.get("exit", {}))
    exit_cfg["method"] = best_exit
    sym_exit_overrides = exit_overrides.get(symbol, {}).get(best_exit, {})
    if sym_exit_overrides:
        exit_sub = exit_cfg.get(best_exit, {})
        exit_sub.update(sym_exit_overrides)
        exit_cfg[best_exit] = exit_sub
    cfg["exit"] = exit_cfg

    # Pass through trend detection
    cfg["trend_detection"] = base_config.get("trend_detection", {})

    return cfg, best_strat, best_exit


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(
        description="Multi-Symbol LIVE Trading (Long + Short)"
    )
    parser.add_argument("--symbols", type=str, default=None)
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--total-capital", type=float, default=100.0)
    parser.add_argument("--daily-loss-pct", type=float, default=10.0)
    parser.add_argument("--leverage", type=int, default=2)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--yes", action="store_true",
                        help="Skip interactive confirmation (DANGEROUS)")
    args = parser.parse_args()

    # Logging
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(str(log_dir / "multisymbol_live.log"),
               rotation="10 MB", level="DEBUG")

    base_config = load_config(args.config)
    symbols = args.symbols.split(",") if args.symbols else ALL_SYMBOLS
    # Long and short rarely overlap (uptrend vs downtrend), so each side
    # gets the full per-coin allocation rather than splitting in half.
    capital_per_coin_side = args.total_capital / len(symbols)
    leverage = args.leverage
    daily_loss_limit = args.total_capital * args.daily_loss_pct / 100.0

    if not args.yes:
        if not confirm_live_mode(args.total_capital, leverage,
                                 symbols, daily_loss_limit):
            print("Aborted.")
            return 1

    # Build futures client and verify connectivity / balance
    try:
        futures = build_futures_client()
        balance = futures.get_balance("USDT")
        logger.info("Connected to Bitget. USDT balance: ${:.2f}", balance)
        if balance < args.total_capital * 0.95:
            logger.warning(
                "Account balance ${:.2f} is lower than declared capital "
                "${:.2f} — proceeding anyway", balance, args.total_capital,
            )
    except Exception as exc:
        logger.error("Failed to connect to Bitget: {}", exc)
        return 2

    # Set leverage and margin mode for each symbol (both sides)
    for symbol in symbols:
        try:
            futures.set_margin_mode(symbol, "crossed")
        except Exception as exc:
            logger.warning("[{}] set_margin_mode failed: {}", symbol, exc)
        for side in ["long", "short"]:
            try:
                futures.set_leverage(symbol, leverage, side=side)
                logger.info("[{}] leverage set to {}x ({})", symbol, leverage, side)
            except Exception as exc:
                logger.error("[{}] set_leverage({}) failed: {}", symbol, side, exc)

    # Build executors and feeds — keyed as "BTCUSDT:long", "BTCUSDT:short"
    executors: dict[str, LiveExecutor] = {}
    feeds: dict[str, BitgetFeed] = {}

    for symbol in symbols:
        for direction in ["long", "short"]:
            key = f"{symbol}:{direction}"

            sym_cfg, best_strat, best_exit = build_symbol_config_directional(
                base_config, symbol, capital_per_coin_side, direction,
            )
            sym_cfg["leverage"] = leverage

            logger.info(
                "[{}:{}] strategy={} exit={} capital=${:.2f} (simple interest)",
                symbol, direction, best_strat, best_exit, capital_per_coin_side,
            )

            executor = LiveExecutor(
                sym_cfg,
                futures_client=futures,
                min_order_size=LIVE_MIN_ORDER_SIZE.get(symbol, 0.001),
                size_step=LIVE_SIZE_STEP.get(symbol, 0.001),
            )
            executors[key] = executor

        # One feed per symbol (shared by long & short executors)
        if symbol not in feeds:
            ex_cfg = copy.deepcopy(base_config.get("exchange", {}))
            ex_cfg["symbol"] = symbol
            feed = BitgetFeed(ex_cfg)
            feed.symbol = symbol
            feeds[symbol] = feed

    # Initial higher-TF data
    for key, executor in executors.items():
        symbol = key.split(":")[0]
        if executor.signal_engine.needs_higher_tf:
            try:
                htf = feeds[symbol].get_latest_bars(timeframe="4h", count=500)
                htf = drop_forming_bar(htf, "4h")
                if not htf.empty:
                    executor.signal_engine.update_higher_tf(htf)
                    logger.info("[{}] Loaded {} bars of 4h data", key, len(htf))
            except Exception as exc:
                logger.error("[{}] 4h fetch failed: {}", key, exc)

    initial_total = sum(e.initial_capital for e in executors.values())
    htf_refresh_counter = 0
    htf_refresh_interval = 4
    # Track the last bar time processed per executor to fire on signals
    # that appeared since the previous poll.  Initialize to 1 bar before
    # the current latest so we can act on a signal that just landed on
    # the most-recent closed bar right after startup.
    last_processed: dict[str, pd.Timestamp] = {}
    for key, executor in executors.items():
        symbol = key.split(":")[0]
        bar_dur = _TIMEFRAME_DURATIONS.get(
            executor.timeframe, pd.Timedelta(hours=1)
        )
        try:
            df0 = feeds[symbol].get_latest_bars(
                timeframe=executor.timeframe, count=5
            )
            df0 = drop_forming_bar(df0, executor.timeframe)
            if not df0.empty:
                last_processed[key] = df0.index[-1] - 12 * bar_dur
        except Exception:
            pass

    logger.info("=" * 70)
    logger.info("LIVE LOOP STARTED — Long + Short — Ctrl+C to stop")
    logger.info(f"  {len(executors)} executors "
                f"({len(symbols)} symbols × 2 sides) "
                f"| ${capital_per_coin_side:.2f}/executor")
    logger.info("=" * 70)

    try:
        while True:
            cycle_start = time.time()

            for key, executor in executors.items():
                symbol = key.split(":")[0]
                direction = key.split(":")[1]
                feed = feeds[symbol]
                try:
                    df = feed.get_latest_bars(
                        timeframe=executor.timeframe, count=500
                    )
                    if df is None or df.empty:
                        logger.warning("[{}] no data", key)
                        continue

                    # Drop the last bar if it's still forming so the
                    # signal-engine's "latest-bar" filter matches confirmed
                    # signals.
                    df = drop_forming_bar(df, executor.timeframe)
                    if df.empty:
                        continue

                    if (executor.signal_engine.needs_higher_tf
                            and htf_refresh_counter >= htf_refresh_interval):
                        try:
                            htf = feed.get_latest_bars(
                                timeframe="4h", count=500
                            )
                            htf = drop_forming_bar(htf, "4h")
                            if not htf.empty:
                                executor.signal_engine.update_higher_tf(htf)
                        except Exception as exc:
                            logger.warning(
                                "[{}] 4h refresh failed: {}", key, exc
                            )

                    current_price = float(df.iloc[-1]["close"])

                    # 1) Reconcile any closed exchange position
                    closed = executor.reconcile_position(current_price)
                    if closed:
                        logger.info(
                            "[{}] CLOSED on exchange: PnL=${:+.2f}",
                            key, closed["pnl"],
                        )

                    # 2) Look for new signals since the last poll
                    has_open = executor._open_local_pid is not None
                    latest_bar_time = df.index[-1]
                    if not has_open:
                        since = last_processed.get(key)
                        new_signals = executor.signal_engine.process_bar_since(
                            df, since=since,
                        )
                        # Only take signals matching this executor's direction,
                        # and only from the last 3 bars so we don't fire on
                        # stale signals after long downtime.
                        cutoff = latest_bar_time - 12 * _TIMEFRAME_DURATIONS.get(
                            executor.timeframe, pd.Timedelta(hours=1)
                        )
                        matching_dir = [
                            s for s in new_signals
                            if getattr(s, "direction", "long") == direction
                        ]
                        in_window = [
                            s for s in matching_dir if s.timestamp >= cutoff
                        ]
                        if new_signals:
                            logger.debug(
                                "[{}] signals={} | dir_match={} | in_window={} "
                                "(since={}, cutoff={})",
                                key, len(new_signals), len(matching_dir),
                                len(in_window), since, cutoff,
                            )
                        # Sort by timestamp descending (newest first) and take one
                        in_window.sort(key=lambda s: s.timestamp, reverse=True)
                        for signal in in_window[:1]:
                            price_drift = abs(current_price - signal.entry_price) / signal.entry_price * 100
                            if price_drift > 5.0:
                                logger.warning(
                                    "[{}] signal @{} SKIPPED: price drifted "
                                    "{:.1f}% (entry={:.4f}, now={:.4f})",
                                    key, signal.timestamp, price_drift,
                                    signal.entry_price, current_price,
                                )
                                continue
                            allowed, reason = (
                                executor.risk_manager.check_trade_allowed(
                                    executor.capital,
                                    executor.peak_equity,
                                    executor.daily_pnl,
                                    1 if has_open else 0,
                                )
                            )
                            if not allowed:
                                logger.warning(
                                    "[{}] signal @{} BLOCKED: {}",
                                    key, signal.timestamp, reason,
                                )
                                continue
                            # Pre-check size so we know why it would fail
                            test_size = executor.calc_live_size(
                                executor.capital,
                                signal.entry_price,
                                signal.stop_loss,
                            )
                            if test_size <= 0:
                                logger.warning(
                                    "[{}] signal @{} BLOCKED: size=0 "
                                    "(capital=${:.2f}, entry={:.4f}, "
                                    "sl={:.4f}, min={})",
                                    key, signal.timestamp,
                                    executor.capital, signal.entry_price,
                                    signal.stop_loss, executor.min_order_size,
                                )
                                continue
                            logger.info(
                                "[{}] ACTING on signal @{} size={} "
                                "(last_processed={})",
                                key, signal.timestamp, test_size, since,
                            )
                            ok = executor.open_live_position(signal)
                            if ok:
                                logger.success(
                                    "[{}] ENTRY CONFIRMED @{}",
                                    key, signal.timestamp,
                                )
                            break
                    # Update last-processed marker regardless
                    last_processed[key] = latest_bar_time

                    executor.state_store.set("capital", executor.capital)
                    executor.state_store.set(
                        "positions", executor.position_manager.to_dict()
                    )
                    executor.state_store.save()

                except Exception as exc:
                    logger.error("[{}] cycle error: {}", key, exc)

            # Portfolio summary + daily loss kill switch
            total_capital = sum(e.capital for e in executors.values())
            total_pnl = total_capital - initial_total
            n_open = sum(
                1 for e in executors.values() if e._open_local_pid is not None
            )
            n_long_open = sum(
                1 for k, e in executors.items()
                if e._open_local_pid is not None and k.endswith(":long")
            )
            n_short_open = sum(
                1 for k, e in executors.items()
                if e._open_local_pid is not None and k.endswith(":short")
            )
            logger.info(
                "--- Portfolio: ${:.2f} ({:+.2f}) | "
                "Open: {} (L:{} S:{}) ---",
                total_capital, total_pnl, n_open, n_long_open, n_short_open,
            )

            if total_pnl <= -daily_loss_limit:
                logger.error(
                    "DAILY LOSS LIMIT HIT (${:+.2f} <= -${:.2f}). "
                    "Closing all positions and stopping.",
                    total_pnl, daily_loss_limit,
                )
                for key, ex in executors.items():
                    ex.emergency_close()
                break

            htf_refresh_counter = (htf_refresh_counter + 1) % (
                htf_refresh_interval + 1
            )
            elapsed = time.time() - cycle_start
            time.sleep(max(0, args.interval - elapsed))

    except KeyboardInterrupt:
        logger.info("Stopped by user. Open positions remain on the exchange "
                    "with their preset SL/TP. Use the Bitget UI to manage.")

    # Final summary
    logger.info("=" * 70)
    logger.info("FINAL SUMMARY")
    logger.info("=" * 70)
    total = 0.0
    for key, executor in sorted(executors.items()):
        pnl = executor.capital - capital_per_coin_side
        total += executor.capital
        logger.info(
            "  {:20s}: ${:7.2f} (PnL ${:+.2f})",
            key, executor.capital, pnl,
        )
    total_pnl = total - initial_total
    logger.info(
        "  {:20s}: ${:7.2f} (PnL ${:+.2f}, {:+.2f}%)",
        "TOTAL", total, total_pnl, total_pnl / initial_total * 100,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
