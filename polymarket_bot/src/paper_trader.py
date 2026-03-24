"""Paper trading engine: simulated entry/exit with PnL tracking."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from .config import Config
from .models import (
    Market,
    PaperPosition,
    PositionStatus,
    SignalResult,
    TradeAction,
)

logger = logging.getLogger("polymarket_bot")


class PaperTrader:
    """Simulates trades based on signals without real order execution.

    Designed so that replacing this with a real trader requires
    implementing the same interface (enter / check_exits / close).
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.open_positions: dict[str, PaperPosition] = {}
        self.closed_positions: list[PaperPosition] = []

    @property
    def position_count(self) -> int:
        return len(self.open_positions)

    def can_open(self) -> bool:
        return self.position_count < self.config.paper_max_positions

    def enter(self, signal: SignalResult) -> Optional[PaperPosition]:
        """Open a new paper position based on a signal."""
        if not self.can_open():
            logger.warning("Max positions reached (%d), skipping", self.config.paper_max_positions)
            return None

        if signal.recommended_action is None:
            return None

        # Determine entry price from the signal's market book
        entry_price = self._get_entry_price(signal)
        if entry_price is None or entry_price <= 0:
            logger.warning("Cannot determine entry price for %s", signal.market.question[:40])
            return None

        pos_id = str(uuid.uuid4())[:8]
        position = PaperPosition(
            position_id=pos_id,
            market=signal.market,
            action=signal.recommended_action,
            entry_price=entry_price,
            size=self.config.paper_trade_size,
            entry_time=datetime.utcnow(),
            signal=signal,
        )
        self.open_positions[pos_id] = position

        logger.info(
            "PAPER ENTRY: id=%s | %s | %s @ %.4f | size=%.2f | edge=%.4f",
            pos_id,
            signal.recommended_action.value,
            signal.market.question[:40],
            entry_price,
            self.config.paper_trade_size,
            signal.expected_edge,
        )
        return position

    def check_exits(self, market: Market) -> list[PaperPosition]:
        """Check all open positions for TP/SL/timeout exits.

        Returns list of newly closed positions.
        """
        closed: list[PaperPosition] = []
        now = datetime.utcnow()

        for pos_id, pos in list(self.open_positions.items()):
            if pos.market.condition_id != market.condition_id:
                continue

            current_price = self._get_current_price(pos, market)
            if current_price is None:
                continue

            # Calculate unrealized PnL
            pnl = self._calc_pnl(pos, current_price)
            hold_secs = (now - pos.entry_time).total_seconds()

            # Check take profit
            if pnl >= self.config.paper_take_profit * pos.size:
                self._close_position(pos, current_price, PositionStatus.CLOSED_TP, pnl)
                closed.append(pos)

            # Check stop loss
            elif pnl <= -(self.config.paper_stop_loss * pos.size):
                self._close_position(pos, current_price, PositionStatus.CLOSED_SL, pnl)
                closed.append(pos)

            # Check timeout
            elif hold_secs >= self.config.paper_timeout_sec:
                self._close_position(pos, current_price, PositionStatus.CLOSED_TIMEOUT, pnl)
                closed.append(pos)

        return closed

    def close_all(self, market: Market) -> list[PaperPosition]:
        """Force close all open positions for a market."""
        closed: list[PaperPosition] = []
        for pos_id, pos in list(self.open_positions.items()):
            if pos.market.condition_id != market.condition_id:
                continue
            current_price = self._get_current_price(pos, market)
            if current_price is None:
                current_price = pos.entry_price  # Fallback
            pnl = self._calc_pnl(pos, current_price)
            self._close_position(pos, current_price, PositionStatus.CLOSED_MANUAL, pnl)
            closed.append(pos)
        return closed

    def _close_position(
        self,
        pos: PaperPosition,
        exit_price: float,
        status: PositionStatus,
        pnl: float,
    ) -> None:
        pos.exit_price = exit_price
        pos.exit_time = datetime.utcnow()
        pos.status = status
        pos.pnl = pnl
        self.open_positions.pop(pos.position_id, None)
        self.closed_positions.append(pos)

        logger.info(
            "PAPER EXIT: id=%s | %s | exit=%.4f | pnl=%.4f | hold=%.0fs | %s",
            pos.position_id,
            pos.market.question[:40],
            exit_price,
            pnl,
            pos.hold_time_sec,
            status.value,
        )

    def _get_entry_price(self, signal: SignalResult) -> Optional[float]:
        """Get simulated entry price (best ask for buys)."""
        action = signal.recommended_action
        market = signal.market
        if action in (TradeAction.BUY_YES, TradeAction.SELL_NO):
            yes = market.yes_token
            return yes.order_book.best_ask if yes else None
        elif action in (TradeAction.BUY_NO, TradeAction.SELL_YES):
            no = market.no_token
            return no.order_book.best_ask if no else None
        return None

    def _get_current_price(self, pos: PaperPosition, market: Market) -> Optional[float]:
        """Get current exit price (best bid for sells)."""
        if pos.action in (TradeAction.BUY_YES, TradeAction.SELL_NO):
            yes = market.yes_token
            return yes.order_book.best_bid if yes else None
        elif pos.action in (TradeAction.BUY_NO, TradeAction.SELL_YES):
            no = market.no_token
            return no.order_book.best_bid if no else None
        return None

    def _calc_pnl(self, pos: PaperPosition, current_price: float) -> float:
        """Calculate PnL for a position.

        For BUY: PnL = (current_bid - entry_ask) * size
        """
        return (current_price - pos.entry_price) * pos.size
