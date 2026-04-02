"""Paper trading executor for the BTC Trend Long Bot.

Ties together the signal engine, position manager, risk manager, and
state store to run a realistic paper-trading simulation -- either on
historical data (``run_on_historical``) or in a live polling loop
(``run_live_loop``).  No real orders are placed.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
from loguru import logger

from btc_trend_bot.live.signal_engine import SignalEngine
from btc_trend_bot.live.position_manager import PositionManager
from btc_trend_bot.live.risk_manager import RiskManager
from btc_trend_bot.live.state_store import StateStore


class PaperExecutor:
    """Paper trading executor.

    Runs in a loop (or over historical bars), fetching data, generating
    signals, managing positions, and tracking P&L without placing real
    orders.
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self.symbol: str = config.get("symbol", "BTCUSDT")
        self.timeframe: str = config.get("timeframe", "1h")
        self.initial_capital: float = config.get("initial_capital", 10000.0)
        self.capital: float = self.initial_capital
        self.peak_equity: float = self.initial_capital
        self.daily_pnl: float = 0.0

        self.signal_engine = SignalEngine(config)
        self.position_manager = PositionManager()
        self.risk_manager = RiskManager(config)
        self.state_store = StateStore(
            config.get("state_file", "data/paper_state.json")
        )

        self.fee_pct: float = config.get("taker_fee_pct", 0.06)
        self._running: bool = False

    # ------------------------------------------------------------------
    # Historical simulation
    # ------------------------------------------------------------------

    def run_on_historical(self, df: pd.DataFrame) -> dict:
        """Run paper trading over historical OHLCV data.

        Iterates bar-by-bar (after a warm-up window), generates signals,
        manages positions, and records equity.  Behaves like a backtest
        but exercises the full paper-trading infrastructure.

        Parameters
        ----------
        df : pd.DataFrame
            Full OHLCV DataFrame with DatetimeIndex.

        Returns
        -------
        dict
            Summary containing ``trades``, ``final_equity``,
            ``total_pnl``, ``total_trades``, and ``equity_history``.
        """
        trades: list[dict] = []
        equity_history: list[dict] = []
        warmup = self.signal_engine.min_bars

        logger.info(
            "Starting historical paper trading: {} bars, warmup={}",
            len(df),
            warmup,
        )

        for i in range(warmup, len(df)):
            # Sliding window: up to 500 bars of look-back plus the current bar
            window = df.iloc[max(0, i - 500) : i + 1].copy()
            current_bar = df.iloc[i]
            current_price = float(current_bar["close"])

            # --- Check exits for open positions ---
            closed = self.position_manager.update_price(current_price)
            for trade in closed:
                self.capital += trade["pnl"]
                self.daily_pnl += trade["pnl"]
                trades.append(trade)

            # --- Check for new signals if no position is open ---
            if not self.position_manager.has_open_position(self.symbol):
                signals = self.signal_engine.process_bar(window)

                for signal in signals:
                    allowed, reason = self.risk_manager.check_trade_allowed(
                        self.capital,
                        self.peak_equity,
                        self.daily_pnl,
                        len(self.position_manager.get_open_positions()),
                    )
                    if not allowed:
                        logger.debug("Trade blocked: {}", reason)
                        continue

                    size = self.risk_manager.calc_position_size(
                        self.capital,
                        signal.entry_price,
                        signal.stop_loss,
                    )
                    if size <= 0:
                        logger.debug("Skipping signal: computed size is 0")
                        continue

                    self.position_manager.open_position(
                        symbol=self.symbol,
                        side="long",
                        entry_price=signal.entry_price,
                        size=size,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        strategy_name=signal.strategy_name,
                        metadata=signal.metadata,
                    )

            # --- Track equity ---
            unrealized = self.position_manager.get_unrealized_pnl(
                current_price
            )
            equity = self.capital + unrealized
            self.peak_equity = max(self.peak_equity, equity)

            if i % 100 == 0:
                equity_history.append(
                    {"timestamp": str(df.index[i]), "equity": equity}
                )

        # --- Close remaining positions at the final price ---
        if len(df) > 0:
            last_price = float(df.iloc[-1]["close"])
            for pos in list(self.position_manager.positions.values()):
                trade = self.position_manager.close_position(
                    pos.position_id, last_price, "end_of_data", self.fee_pct
                )
                self.capital += trade["pnl"]
                trades.append(trade)

        summary = {
            "trades": trades,
            "final_equity": self.capital,
            "total_pnl": self.capital - self.initial_capital,
            "total_trades": len(trades),
            "equity_history": equity_history,
        }
        logger.info(
            "Historical paper trading complete: {} trades, final equity={:.2f}, PnL={:.2f}",
            len(trades),
            self.capital,
            self.capital - self.initial_capital,
        )
        return summary

    # ------------------------------------------------------------------
    # Live loop
    # ------------------------------------------------------------------

    def run_live_loop(
        self,
        exchange_client: Any,
        interval_seconds: int = 60,
    ) -> None:
        """Run a live paper-trading polling loop.

        Fetches the latest candles from *exchange_client*, generates
        signals, manages positions, and persists state.  No real orders
        are placed.

        Parameters
        ----------
        exchange_client
            Any object that exposes
            ``fetch_ohlcv(symbol, timeframe, limit=N) -> pd.DataFrame``.
        interval_seconds : int
            Seconds to sleep between iterations.
        """
        logger.info(
            "Starting paper trading loop: {} {} (poll every {}s)",
            self.symbol,
            self.timeframe,
            interval_seconds,
        )
        self._running = True

        # Restore any persisted position state
        persisted_positions = self.state_store.get("positions")
        if persisted_positions:
            self.position_manager.from_dict(persisted_positions)
            logger.info("Restored positions from state store")

        persisted_capital = self.state_store.get("capital")
        if persisted_capital is not None:
            self.capital = float(persisted_capital)
            logger.info("Restored capital: {:.2f}", self.capital)

        while self._running:
            try:
                # Fetch latest data
                df = exchange_client.fetch_ohlcv(
                    self.symbol, self.timeframe, limit=500
                )
                if df is None or df.empty:
                    logger.warning("No data received from exchange")
                    time.sleep(interval_seconds)
                    continue

                current_price = float(df.iloc[-1]["close"])

                # --- Check exits ---
                closed = self.position_manager.update_price(current_price)
                for trade in closed:
                    self.capital += trade["pnl"]
                    self.daily_pnl += trade["pnl"]
                    self.state_store.add_trade(trade)
                    logger.info(
                        "Position closed: PnL={:.2f} ({})",
                        trade["pnl"],
                        trade["exit_reason"],
                    )

                # --- Check new signals ---
                if not self.position_manager.has_open_position(self.symbol):
                    signals = self.signal_engine.process_bar(df)
                    for signal in signals:
                        allowed, reason = (
                            self.risk_manager.check_trade_allowed(
                                self.capital,
                                self.peak_equity,
                                self.daily_pnl,
                                len(
                                    self.position_manager.get_open_positions()
                                ),
                            )
                        )
                        if not allowed:
                            logger.debug("Trade blocked: {}", reason)
                            continue

                        size = self.risk_manager.calc_position_size(
                            self.capital,
                            signal.entry_price,
                            signal.stop_loss,
                        )
                        if size <= 0:
                            continue

                        self.position_manager.open_position(
                            symbol=self.symbol,
                            side="long",
                            entry_price=signal.entry_price,
                            size=size,
                            stop_loss=signal.stop_loss,
                            take_profit=signal.take_profit,
                            strategy_name=signal.strategy_name,
                        )
                        logger.info(
                            "Paper position opened: {} @ {:.2f}",
                            signal.strategy_name,
                            signal.entry_price,
                        )

                # --- Equity tracking ---
                unrealized = self.position_manager.get_unrealized_pnl(
                    current_price
                )
                equity = self.capital + unrealized
                self.peak_equity = max(self.peak_equity, equity)

                self.state_store.add_equity_snapshot(
                    str(pd.Timestamp.now(tz="UTC")), equity
                )

                # Persist positions and capital
                self.state_store.set(
                    "positions", self.position_manager.to_dict()
                )
                self.state_store.set("capital", self.capital)
                self.state_store.save()

                # --- Circuit breaker ---
                triggered, cb_reason = self.risk_manager.check_circuit_breaker(
                    self.state_store.get_equity_history()
                )
                if triggered:
                    logger.error(
                        "Circuit breaker triggered, stopping: {}", cb_reason
                    )
                    self._running = False
                    break

                logger.info(
                    "Equity: {:.2f} | Open: {} | Price: {:.2f}",
                    equity,
                    len(self.position_manager.get_open_positions()),
                    current_price,
                )

            except KeyboardInterrupt:
                logger.info("Paper trading stopped by user")
                self._running = False
                break
            except Exception as exc:
                logger.error("Error in paper trading loop: {}", exc)

            time.sleep(interval_seconds)

        # Final state persistence on exit
        self.state_store.set("positions", self.position_manager.to_dict())
        self.state_store.set("capital", self.capital)
        self.state_store.save()
        logger.info("Paper trading loop ended. Final equity: {:.2f}", self.capital)

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the live loop to stop after the current iteration."""
        self._running = False
        logger.info("Stop requested")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> dict:
        """Return a snapshot of the current paper-trading state."""
        pnl = self.capital - self.initial_capital
        pnl_pct = (pnl / self.initial_capital * 100.0) if self.initial_capital > 0 else 0.0
        return {
            "capital": self.capital,
            "initial_capital": self.initial_capital,
            "peak_equity": self.peak_equity,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "open_positions": len(self.position_manager.get_open_positions()),
            "total_trades": len(self.state_store.get_trades()),
        }
