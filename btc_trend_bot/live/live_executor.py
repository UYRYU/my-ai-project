"""Live trading executor for the BTC Trend Long Bot.

Mirrors PaperExecutor's structure but places real orders against
Bitget USDT-M Futures via BitgetFuturesClient.

Design notes
------------
- SL / TP are attached to the entry order via Bitget's preset fields,
  so position closure is handled by the exchange (no client-side risk
  of missing an exit if the bot dies).
- Each polling cycle we call get_position() on the exchange to detect
  whether our open position is still alive. If it disappears (SL/TP
  filled), we mark it closed locally and refresh capital from the
  exchange balance.
- Position sizing reuses RiskManager.calc_position_size; the result is
  rounded down to the symbol's step size and validated against
  min_order_size before submission.
"""

from __future__ import annotations

import math
from typing import Optional

from loguru import logger

from btc_trend_bot.exchange.bitget_futures import BitgetFuturesClient
from btc_trend_bot.exchange.models import (
    OrderRequest,
    OrderSide,
    OrderType,
)
from btc_trend_bot.live.position_manager import PositionManager
from btc_trend_bot.live.risk_manager import RiskManager
from btc_trend_bot.live.signal_engine import SignalEngine
from btc_trend_bot.live.state_store import StateStore


class LiveExecutor:
    """Live (real-money) executor for a single symbol.

    Supports both long and short directions.  When ``simple_interest``
    is enabled, position sizing always uses ``initial_capital`` instead
    of the current (compound) capital.
    """

    def __init__(
        self,
        config: dict,
        futures_client: BitgetFuturesClient,
        min_order_size: float,
        size_step: float,
        price_decimals: int = 2,
    ) -> None:
        self.config = config
        self.symbol: str = config.get("symbol", "BTCUSDT")
        self.timeframe: str = config.get("timeframe", "1h")
        self.direction: str = config.get("direction", "long")  # "long" or "short"
        self.initial_capital: float = config.get("initial_capital", 20.0)
        self.capital: float = self.initial_capital
        self.peak_equity: float = self.initial_capital
        self.daily_pnl: float = 0.0
        self.leverage: int = int(config.get("leverage", 2))
        self.simple_interest: bool = config.get("simple_interest", False)

        self.futures = futures_client
        self.min_order_size = float(min_order_size)
        self.size_step = float(size_step)
        self.price_decimals = price_decimals

        # Reuse the existing signal / position / risk infrastructure.
        # PositionManager here mirrors exchange state for tracking only;
        # the actual exits happen on the exchange via preset SL/TP.
        self.signal_engine = SignalEngine(config)
        self.position_manager = PositionManager()
        self.risk_manager = RiskManager(config)
        self.state_store = StateStore(
            config.get("state_file", f"data/live_state_{self.symbol}.json")
        )

        # Track which local position id corresponds to the current open
        # exchange position so we can detect closure.
        self._open_local_pid: Optional[str] = None

    # ------------------------------------------------------------------
    # Sizing helpers
    # ------------------------------------------------------------------

    def _round_size(self, size: float) -> float:
        if self.size_step <= 0:
            return size
        return math.floor(size / self.size_step) * self.size_step

    def calc_live_size(
        self, capital: float, entry: float, stop_loss: float
    ) -> float:
        """Risk-based size in coin units, capped by leverage notional and
        rounded to the symbol step size.

        When ``simple_interest`` is True, sizing always uses
        ``initial_capital`` so profits don't compound.
        """
        sizing_capital = self.initial_capital if self.simple_interest else capital
        risk_size = self.risk_manager.calc_position_size(
            sizing_capital, entry, stop_loss
        )
        # Cap to leverage-adjusted notional (not just capital/entry)
        max_notional = sizing_capital * self.leverage
        max_size = max_notional / entry if entry > 0 else 0.0
        size = min(risk_size, max_size)
        size = self._round_size(size)
        if size < self.min_order_size:
            return 0.0
        return size

    # ------------------------------------------------------------------
    # Reconciliation with exchange
    # ------------------------------------------------------------------

    def reconcile_position(self, current_price: float) -> Optional[dict]:
        """Detect closure of an exchange-side position.

        Returns the closed-trade dict if the position disappeared this
        cycle, else None.
        """
        if self._open_local_pid is None:
            return None

        ex_pos = self.futures.get_position(self.symbol)
        if ex_pos is not None and ex_pos.get("size", 0) > 0:
            # Check it's the same direction we care about
            if ex_pos.get("side", "long") == self.direction:
                return None  # Still open — nothing to do.

        # Position vanished → SL or TP filled on the exchange.
        local = self.position_manager.positions.get(self._open_local_pid)
        if local is None:
            self._open_local_pid = None
            return None

        trade = self.position_manager.close_position(
            self._open_local_pid, current_price, "exchange_exit"
        )
        self._open_local_pid = None
        # Refresh capital from exchange to get accurate realized PnL
        try:
            new_balance = self.futures.get_balance("USDT")
            # We can't isolate per-symbol balance, so use the local
            # close PnL for tracking; balance is just informational.
            logger.info(
                "[{}] Exchange balance after close: ${:.2f}",
                self.symbol,
                new_balance,
            )
        except Exception as exc:
            logger.warning("[{}] Balance refresh failed: {}", self.symbol, exc)

        self.capital += trade["pnl"]
        self.daily_pnl += trade["pnl"]
        self.state_store.add_trade(trade)
        return trade

    # ------------------------------------------------------------------
    # Order submission
    # ------------------------------------------------------------------

    def open_live_position(self, signal) -> bool:
        """Place a live entry order with preset SL/TP and mirror it
        locally. Returns True on success.

        Direction (long/short) is determined by ``self.direction`` which
        is set at init from the config.
        """
        if self._open_local_pid is not None:
            logger.debug("[{}] Position already open, skipping signal",
                         self.symbol)
            return False

        # Only accept signals matching our direction
        sig_dir = getattr(signal, "direction", "long")
        if sig_dir != self.direction:
            return False

        size = self.calc_live_size(
            self.capital, signal.entry_price, signal.stop_loss
        )
        if size <= 0:
            logger.warning(
                "[{}:{}] Skipped: computed size below min_order_size "
                "(capital=${:.2f}, entry={:.4f}, sl={:.4f}, min={})",
                self.symbol, self.direction, self.capital,
                signal.entry_price, signal.stop_loss, self.min_order_size,
            )
            return False

        # Long opens with BUY, short opens with SELL
        order_side = OrderSide.SELL if self.direction == "short" else OrderSide.BUY

        sl = round(signal.stop_loss, self.price_decimals) if signal.stop_loss else None
        tp = round(signal.take_profit, self.price_decimals) if signal.take_profit else None

        order = OrderRequest(
            symbol=self.symbol,
            side=order_side,
            order_type=OrderType.MARKET,
            size=size,
            stop_loss=sl,
            take_profit=tp,
            leverage=self.leverage,
        )

        try:
            result = self.futures.place_order(order)
        except Exception as exc:
            logger.error("[{}:{}] place_order failed: {}", self.symbol,
                         self.direction, exc)
            return False

        logger.info(
            "[{}:{}] LIVE ORDER FILLED: {} size={} entry≈{:.4f} "
            "SL={:.4f} TP={:.4f} order_id={}",
            self.symbol, self.direction, signal.strategy_name, size,
            signal.entry_price, signal.stop_loss,
            signal.take_profit or 0.0, result.order_id,
        )

        # Mirror locally
        pos = self.position_manager.open_position(
            symbol=self.symbol,
            side=self.direction,
            entry_price=signal.entry_price,
            size=size,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            strategy_name=signal.strategy_name,
            metadata={"order_id": result.order_id, **(signal.metadata or {})},
        )
        self._open_local_pid = pos.position_id if hasattr(pos, "position_id") else None
        # PositionManager.open_position may not return the position; pull it.
        if self._open_local_pid is None:
            # Find the just-added position by symbol
            for pid, p in self.position_manager.positions.items():
                if p.symbol == self.symbol:
                    self._open_local_pid = pid
                    break
        return True

    # ------------------------------------------------------------------
    # Emergency
    # ------------------------------------------------------------------

    def emergency_close(self) -> None:
        """Force-close any open exchange position for this symbol."""
        try:
            ex_pos = self.futures.get_position(self.symbol)
            if ex_pos and ex_pos.get("size", 0) > 0:
                close_side = ex_pos.get("side", self.direction)
                logger.warning("[{}:{}] Emergency closing position",
                               self.symbol, close_side)
                self.futures.close_position(self.symbol, side=close_side)
        except Exception as exc:
            logger.error("[{}:{}] Emergency close failed: {}",
                         self.symbol, self.direction, exc)
