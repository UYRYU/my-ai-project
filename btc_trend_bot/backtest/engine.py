"""Backtest engine for the BTC Trend Long Bot.

Runs a vectorised-loop backtest over OHLCV data using pre-generated
:class:`Signal` objects and an :class:`ExitManager` instance to manage
exits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from btc_trend_bot.strategies.base_strategy import Signal
from btc_trend_bot.backtest.exit_manager import ExitManager, Position
from btc_trend_bot.metrics import calc_all_metrics, calc_regime_metrics


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    """Container for all outputs produced by a single backtest run."""

    trades: pd.DataFrame
    equity_curve: pd.Series
    metrics: dict
    regime_metrics: dict = field(default_factory=dict)
    signals_count: int = 0
    config: dict = field(default_factory=dict)

    def summary(self) -> str:
        """Return a human-readable one-line summary."""
        m = self.metrics
        return (
            f"Trades: {m.get('total_trades', 0)} | "
            f"Profit: {m.get('total_profit', 0):.2f} | "
            f"Win rate: {m.get('win_rate', 0):.2%} | "
            f"PF: {m.get('profit_factor', 0):.2f} | "
            f"Max DD: {m.get('max_drawdown_pct', 0):.2%} | "
            f"Calmar: {m.get('calmar_ratio', 0):.2f}"
        )


# ---------------------------------------------------------------------------
# BacktestEngine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """Event-driven backtest engine.

    Parameters
    ----------
    config : dict
        The ``backtest`` section from *settings.yaml*.
    """

    def __init__(self, config: dict) -> None:
        self.initial_capital: float = config.get("initial_capital", 10_000.0)
        self.commission_pct: float = config.get("commission_pct", 0.04)
        self.slippage_pct: float = config.get("slippage_pct", 0.02)
        self.position_size_pct: float = config.get("position_size_pct", 95.0)
        self.leverage: int = config.get("leverage", 1)
        self.max_open_trades: int = config.get("max_open_trades", 1)
        self.min_order_size: float = config.get("min_order_size", 0.0)
        self._config = config

        logger.info(
            "BacktestEngine init: capital={}, commission={:.4f}%, slippage={:.4f}%, "
            "size={:.1f}%, leverage={}",
            self.initial_capital,
            self.commission_pct,
            self.slippage_pct,
            self.position_size_pct,
            self.leverage,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        df: pd.DataFrame,
        signals: list[Signal],
        exit_manager: ExitManager,
        regime_labels: Optional[pd.Series] = None,
    ) -> BacktestResult:
        """Run the backtest.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV DataFrame indexed by datetime with columns ``open``,
            ``high``, ``low``, ``close``, ``volume`` (and any indicators).
        signals : list[Signal]
            Pre-generated entry signals sorted by timestamp.
        exit_manager : ExitManager
            Instance responsible for deciding when to close a position.
        regime_labels : pd.Series, optional
            Market regime labels (bull/bear/sideways) indexed by datetime.
            If provided, regime-specific metrics are computed.

        Returns
        -------
        BacktestResult
        """
        if df.empty:
            logger.warning("Empty DataFrame passed to backtest engine")
            return self._empty_result()

        # Sort signals by timestamp for efficient look-up
        signals_sorted = sorted(signals, key=lambda s: s.timestamp)
        signal_map: dict[pd.Timestamp, Signal] = {s.timestamp: s for s in signals_sorted}

        logger.info(
            "Starting backtest: {} bars, {} signals, range {} to {}",
            len(df),
            len(signals_sorted),
            df.index[0],
            df.index[-1],
        )

        # State
        capital: float = self.initial_capital
        position: Optional[Position] = None
        trade_log: list[dict] = []
        equity_timestamps: list[pd.Timestamp] = []
        equity_values: list[float] = []

        for idx in range(len(df)):
            bar = df.iloc[idx]
            bar_time = df.index[idx]
            df_history = df.iloc[: idx + 1]

            # --- Check exit for open position ---
            if position is not None:
                exit_result = exit_manager.check_exit(position, bar, df_history)
                if exit_result is not None:
                    trade = self._close_position(
                        position,
                        exit_result,
                        bar_time,
                        capital,
                    )

                    # Handle partial exits
                    partial_pct = exit_result.get("partial_pct")
                    if partial_pct is not None and partial_pct < 100.0:
                        # Partial close: realise PnL for the closed portion
                        fraction = partial_pct / 100.0
                        trade["pnl"] *= fraction
                        trade["exit_reason"] = exit_result["exit_reason"]
                        capital += trade["pnl"]
                        trade_log.append(trade)

                        # Position stays open with reduced effective size
                        # (tracked via remaining_size_pct inside Position)
                    else:
                        capital += trade["pnl"]
                        trade_log.append(trade)
                        position = None

            # --- Check entry if no position ---
            if position is None and bar_time in signal_map:
                signal = signal_map[bar_time]
                position, entry_cost = self._open_position(signal, bar, capital)
                if position is not None:
                    capital -= entry_cost
                    logger.debug(
                        "Opened position: strategy={}, entry={:.2f}, sl={:.2f}, size={:.6f}",
                        position.strategy_name,
                        position.entry_price,
                        position.stop_loss,
                        position.size,
                    )

            # --- Record equity ---
            mark_to_market = capital
            if position is not None:
                close_price = float(bar["close"])
                if position.direction == "short":
                    unrealised = (position.entry_price - close_price) * position.size
                else:
                    unrealised = (close_price - position.entry_price) * position.size
                # Apply remaining-size adjustment for partial exits
                remaining_frac = position.remaining_size_pct / 100.0
                unrealised *= remaining_frac
                mark_to_market += unrealised

            equity_timestamps.append(bar_time)
            equity_values.append(mark_to_market)

        # --- Force-close any remaining position at last bar ---
        if position is not None:
            last_bar = df.iloc[-1]
            last_time = df.index[-1]
            forced_exit = {
                "exit_price": float(last_bar["close"]),
                "exit_reason": "backtest_end",
            }
            trade = self._close_position(position, forced_exit, last_time, capital)
            capital += trade["pnl"]
            trade_log.append(trade)
            position = None
            logger.info("Force-closed position at backtest end")

        # --- Build results ---
        trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame(
            columns=[
                "entry_time", "exit_time", "entry_price", "exit_price",
                "pnl", "pnl_pct", "direction", "strategy", "stop_loss",
                "take_profit", "exit_reason",
            ]
        )

        equity_series = pd.Series(equity_values, index=equity_timestamps, name="equity")

        metrics = calc_all_metrics(trades_df, equity_series)

        regime_met: dict = {}
        if regime_labels is not None and not trades_df.empty:
            regime_met = calc_regime_metrics(trades_df, equity_series, regime_labels)

        result = BacktestResult(
            trades=trades_df,
            equity_curve=equity_series,
            metrics=metrics,
            regime_metrics=regime_met,
            signals_count=len(signals),
            config=self._config,
        )

        logger.info("Backtest complete: {}", result.summary())
        return result

    # ------------------------------------------------------------------
    # Position management helpers
    # ------------------------------------------------------------------

    def _open_position(
        self,
        signal: Signal,
        bar: pd.Series,
        capital: float,
    ) -> tuple[Optional[Position], float]:
        """Open a new position from *signal*.

        Returns ``(Position, entry_cost)`` or ``(None, 0.0)`` if the
        signal is invalid.
        """
        entry_price = signal.entry_price

        # Apply slippage (long entry => price goes up, short => price goes down)
        if signal.direction == "short":
            entry_price *= 1 - self.slippage_pct / 100.0
        else:
            entry_price *= 1 + self.slippage_pct / 100.0

        # Determine size
        allocation = capital * (self.position_size_pct / 100.0) * self.leverage
        if allocation <= 0 or entry_price <= 0:
            logger.warning("Cannot open position: allocation={:.2f}, price={:.2f}", allocation, entry_price)
            return None, 0.0

        size = allocation / entry_price

        # Check minimum order size (e.g. Bitget min 0.0001 BTC)
        if self.min_order_size > 0 and size < self.min_order_size:
            logger.debug(
                "Order size {:.8f} below minimum {:.4f}, skipping",
                size, self.min_order_size,
            )
            return None, 0.0

        # Entry commission
        commission = allocation * (self.commission_pct / 100.0)

        position = Position(
            entry_time=signal.timestamp,
            entry_price=entry_price,
            stop_loss=signal.stop_loss,
            direction=signal.direction,
            size=size,
            strategy_name=signal.strategy_name,
            metadata=dict(signal.metadata) if signal.metadata else {},
        )

        # Store take-profit hint in metadata (for exit manager)
        if signal.take_profit is not None:
            position.metadata["take_profit"] = signal.take_profit

        entry_cost = commission  # capital is reserved via mark-to-market
        return position, entry_cost

    def _close_position(
        self,
        position: Position,
        exit_result: dict,
        exit_time: pd.Timestamp,
        capital: float,
    ) -> dict:
        """Close *position* and return a trade-log record dict."""
        exit_price = exit_result["exit_price"]

        # Apply slippage (long exit => price goes down, short exit => up)
        if position.direction == "short":
            exit_price *= 1 + self.slippage_pct / 100.0
        else:
            exit_price *= 1 - self.slippage_pct / 100.0

        # PnL calculation (short: profit when price drops)
        if position.direction == "short":
            price_diff = position.entry_price - exit_price
        else:
            price_diff = exit_price - position.entry_price
        raw_pnl = price_diff * position.size

        # Exit commission
        notional = exit_price * position.size
        commission = notional * (self.commission_pct / 100.0)
        pnl = raw_pnl - commission

        # Also subtract entry commission that was already deducted (not double-counted)
        # Entry commission was taken from capital at open, so pnl here is net of exit comm only.

        pnl_pct = (price_diff / position.entry_price) * 100.0 if position.entry_price else 0.0

        trade_record = {
            "entry_time": position.entry_time,
            "exit_time": exit_time,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "direction": position.direction,
            "strategy": position.strategy_name,
            "stop_loss": position.stop_loss,
            "take_profit": position.metadata.get("take_profit"),
            "exit_reason": exit_result["exit_reason"],
            "size": position.size,
            "bars_held": position.bars_held,
        }

        logger.debug(
            "Closed position: strategy={}, pnl={:.2f} ({:.2f}%), reason={}",
            position.strategy_name,
            pnl,
            pnl_pct,
            exit_result["exit_reason"],
        )

        return trade_record

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _empty_result(self) -> BacktestResult:
        """Return an empty :class:`BacktestResult`."""
        empty_trades = pd.DataFrame(
            columns=[
                "entry_time", "exit_time", "entry_price", "exit_price",
                "pnl", "pnl_pct", "direction", "strategy", "stop_loss",
                "take_profit", "exit_reason",
            ]
        )
        empty_equity = pd.Series(dtype=float, name="equity")
        return BacktestResult(
            trades=empty_trades,
            equity_curve=empty_equity,
            metrics=calc_all_metrics(empty_trades, empty_equity),
            regime_metrics={},
            signals_count=0,
            config=self._config,
        )
