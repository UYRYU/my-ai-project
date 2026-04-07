"""
Multi-Symbol LIVE Trading Runner (REAL MONEY)
=============================================
Runs live trading on BTC, ETH, XRP, DOGE, SOL simultaneously from the
same Bitget USDT-M Futures account.

Defaults: $100 total / $20 per coin / 2x leverage / -10% daily kill switch.

USAGE:
    python -m btc_trend_bot.run_multisymbol_live
    python -m btc_trend_bot.run_multisymbol_live --symbols BTCUSDT,ETHUSDT
    python -m btc_trend_bot.run_multisymbol_live --total-capital 100 --interval 300

This script REQUIRES typing 'yes' at startup to acknowledge real-money mode.
"""

import argparse
import copy
import os
import sys
import time
from pathlib import Path

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
from btc_trend_bot.run_multisymbol_paper import build_symbol_config, load_config


# Bitget futures actual minimums (USDT-M perpetual). These override the
# COIN_CONFIGS values which were tuned for backtests.
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


def confirm_live_mode(total_capital: float, leverage: int,
                      symbols: list[str], daily_loss_limit: float) -> bool:
    print()
    print("=" * 70)
    print("  ⚠️  LIVE TRADING MODE — REAL MONEY  ⚠️")
    print("=" * 70)
    print(f"  Account capital  : ${total_capital:.2f} USDT")
    print(f"  Per-coin alloc   : ${total_capital / len(symbols):.2f}")
    print(f"  Leverage         : {leverage}x")
    print(f"  Symbols          : {', '.join(symbols)}")
    print(f"  Daily kill-switch: -${daily_loss_limit:.2f} "
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


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Multi-Symbol LIVE Trading")
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
    capital_per_coin = args.total_capital / len(symbols)
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

    # Set leverage and margin mode for each symbol
    for symbol in symbols:
        try:
            futures.set_margin_mode(symbol, "crossed")
        except Exception as exc:
            logger.warning("[{}] set_margin_mode failed: {}", symbol, exc)
        try:
            futures.set_leverage(symbol, leverage, side="long")
            logger.info("[{}] leverage set to {}x", symbol, leverage)
        except Exception as exc:
            logger.error("[{}] set_leverage failed: {}", symbol, exc)

    # Build executors and feeds
    executors: dict[str, LiveExecutor] = {}
    feeds: dict[str, BitgetFeed] = {}

    for symbol in symbols:
        sym_cfg, best_strat, best_exit = build_symbol_config(
            base_config, symbol, capital_per_coin
        )
        sym_cfg["leverage"] = leverage
        sym_cfg["state_file"] = f"data/live_state_{symbol}.json"

        logger.info(
            "[{}] strategy={} exit={} capital=${:.2f}",
            symbol, best_strat, best_exit, capital_per_coin,
        )

        executor = LiveExecutor(
            sym_cfg,
            futures_client=futures,
            min_order_size=LIVE_MIN_ORDER_SIZE.get(symbol, 0.001),
            size_step=LIVE_SIZE_STEP.get(symbol, 0.001),
        )
        executors[symbol] = executor

        ex_cfg = copy.deepcopy(base_config.get("exchange", {}))
        ex_cfg["symbol"] = symbol
        feed = BitgetFeed(ex_cfg)
        feed.symbol = symbol
        feeds[symbol] = feed

    # Initial higher-TF data
    for symbol, executor in executors.items():
        if executor.signal_engine.needs_higher_tf:
            try:
                htf = feeds[symbol].get_latest_bars(timeframe="4h", count=500)
                if not htf.empty:
                    executor.signal_engine.update_higher_tf(htf)
                    logger.info("[{}] Loaded {} bars of 4h data",
                                symbol, len(htf))
            except Exception as exc:
                logger.error("[{}] 4h fetch failed: {}", symbol, exc)

    initial_total = args.total_capital
    htf_refresh_counter = 0
    htf_refresh_interval = 4

    logger.info("=" * 70)
    logger.info("LIVE LOOP STARTED — Ctrl+C to stop")
    logger.info("=" * 70)

    try:
        while True:
            cycle_start = time.time()

            for symbol, executor in executors.items():
                feed = feeds[symbol]
                try:
                    df = feed.get_latest_bars(
                        timeframe=executor.timeframe, count=500
                    )
                    if df is None or df.empty:
                        logger.warning("[{}] no data", symbol)
                        continue

                    if (executor.signal_engine.needs_higher_tf
                            and htf_refresh_counter >= htf_refresh_interval):
                        try:
                            htf = feed.get_latest_bars(
                                timeframe="4h", count=500
                            )
                            if not htf.empty:
                                executor.signal_engine.update_higher_tf(htf)
                        except Exception as exc:
                            logger.warning(
                                "[{}] 4h refresh failed: {}", symbol, exc
                            )

                    current_price = float(df.iloc[-1]["close"])

                    # 1) Reconcile any closed exchange position
                    closed = executor.reconcile_position(current_price)
                    if closed:
                        logger.info(
                            "[{}] CLOSED on exchange: PnL=${:+.2f}",
                            symbol, closed["pnl"],
                        )

                    # 2) Look for fresh signal at the latest bar
                    has_open = executor._open_local_pid is not None
                    if not has_open:
                        signals = executor.signal_engine.process_bar(df)
                        latest_bar_time = df.index[-1]
                        fresh = [
                            s for s in signals if s.timestamp == latest_bar_time
                        ]
                        for signal in fresh:
                            allowed, reason = (
                                executor.risk_manager.check_trade_allowed(
                                    executor.capital,
                                    executor.peak_equity,
                                    executor.daily_pnl,
                                    1 if has_open else 0,
                                )
                            )
                            if not allowed:
                                logger.debug(
                                    "[{}] signal blocked: {}", symbol, reason
                                )
                                continue
                            executor.open_live_position(signal)
                            break  # one position per symbol

                    executor.state_store.set("capital", executor.capital)
                    executor.state_store.set(
                        "positions", executor.position_manager.to_dict()
                    )
                    executor.state_store.save()

                except Exception as exc:
                    logger.error("[{}] cycle error: {}", symbol, exc)

            # Portfolio summary + daily loss kill switch
            total_capital = sum(e.capital for e in executors.values())
            total_pnl = total_capital - initial_total
            n_open = sum(
                1 for e in executors.values() if e._open_local_pid is not None
            )
            logger.info(
                "--- Portfolio: ${:.2f} ({:+.2f}, {} open) ---",
                total_capital, total_pnl, n_open,
            )

            if total_pnl <= -daily_loss_limit:
                logger.error(
                    "🚨 DAILY LOSS LIMIT HIT (${:+.2f} <= -${:.2f}). "
                    "Closing all positions and stopping.",
                    total_pnl, daily_loss_limit,
                )
                for sym, ex in executors.items():
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
    for symbol, executor in executors.items():
        pnl = executor.capital - capital_per_coin
        total += executor.capital
        logger.info(
            "  {:10s}: ${:7.2f} (PnL ${:+.2f})",
            symbol, executor.capital, pnl,
        )
    total_pnl = total - initial_total
    logger.info(
        "  {:10s}: ${:7.2f} (PnL ${:+.2f}, {:+.2f}%)",
        "TOTAL", total, total_pnl, total_pnl / initial_total * 100,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
