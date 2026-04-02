"""Manage virtual positions for paper trading.

Tracks open paper positions, checks stop-loss / take-profit levels on
each price update, and computes realised and unrealised P&L.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from loguru import logger


@dataclass
class PaperPosition:
    """A single virtual (paper) position."""

    position_id: str
    symbol: str
    side: str  # "long"
    entry_price: float
    entry_time: pd.Timestamp
    size: float  # in BTC
    stop_loss: float
    take_profit: Optional[float]
    strategy_name: str
    highest_price: float = 0.0
    trailing_stop: Optional[float] = None
    partial_closed: bool = False
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.highest_price == 0.0:
            self.highest_price = self.entry_price


class PositionManager:
    """Create, track, and close paper positions."""

    def __init__(self) -> None:
        self.positions: dict[str, PaperPosition] = {}
        self._next_id: int = 1

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        stop_loss: float,
        take_profit: Optional[float] = None,
        strategy_name: str = "",
        metadata: dict | None = None,
    ) -> PaperPosition:
        """Create and track a new paper position.

        Returns the newly created ``PaperPosition``.
        """
        pid = f"paper_{self._next_id}"
        self._next_id += 1

        pos = PaperPosition(
            position_id=pid,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            entry_time=pd.Timestamp.now(tz="UTC"),
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy_name,
            highest_price=entry_price,
            metadata=metadata or {},
        )
        self.positions[pid] = pos
        logger.info(
            "Opened paper position {} | {} {} {:.6f} BTC @ {:.2f} | SL={:.2f} TP={}",
            pid,
            symbol,
            side,
            size,
            entry_price,
            stop_loss,
            f"{take_profit:.2f}" if take_profit else "None",
        )
        return pos

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str,
        fee_pct: float = 0.06,
    ) -> dict:
        """Close a position and return a trade-result dictionary.

        The result contains: pnl, pnl_pct, entry_price, exit_price,
        entry_time, exit_time, holding_time, fee, exit_reason,
        strategy_name, symbol, side, size, position_id.
        """
        if position_id not in self.positions:
            raise KeyError(f"Position {position_id} not found")

        pos = self.positions.pop(position_id)
        exit_time = pd.Timestamp.now(tz="UTC")

        # Gross P&L (long only)
        if pos.side == "long":
            gross_pnl = (exit_price - pos.entry_price) * pos.size
        else:
            gross_pnl = (pos.entry_price - exit_price) * pos.size

        # Fees: applied on both entry and exit notional
        entry_notional = pos.entry_price * pos.size
        exit_notional = exit_price * pos.size
        total_fee = (entry_notional + exit_notional) * fee_pct / 100.0

        net_pnl = gross_pnl - total_fee
        pnl_pct = (net_pnl / entry_notional * 100.0) if entry_notional > 0 else 0.0
        holding_time = exit_time - pos.entry_time

        trade_result = {
            "position_id": pos.position_id,
            "symbol": pos.symbol,
            "side": pos.side,
            "size": pos.size,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "entry_time": str(pos.entry_time),
            "exit_time": str(exit_time),
            "holding_time": str(holding_time),
            "pnl": net_pnl,
            "pnl_pct": pnl_pct,
            "fee": total_fee,
            "exit_reason": exit_reason,
            "strategy_name": pos.strategy_name,
            "metadata": pos.metadata,
        }

        logger.info(
            "Closed {} | PnL={:.2f} ({:.2f}%) | reason={} | held {}",
            pos.position_id,
            net_pnl,
            pnl_pct,
            exit_reason,
            holding_time,
        )
        return trade_result

    # ------------------------------------------------------------------
    # Price updates (SL / TP checking)
    # ------------------------------------------------------------------

    def update_price(self, current_price: float) -> list[dict]:
        """Update all positions with the current price.

        Checks stop-loss and take-profit levels. Returns a list of
        trade-result dicts for any positions that were closed.
        """
        closed_trades: list[dict] = []
        # Iterate over a snapshot of keys since we may remove entries
        for pid in list(self.positions.keys()):
            pos = self.positions[pid]

            # Update highest price for trailing-stop calculation
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            # --- Stop-loss check ---
            if current_price <= pos.stop_loss:
                exit_price = pos.stop_loss  # assume filled at SL level
                trade = self.close_position(pid, exit_price, "stop_loss")
                closed_trades.append(trade)
                continue

            # --- Take-profit check ---
            if pos.take_profit is not None and current_price >= pos.take_profit:
                exit_price = pos.take_profit
                trade = self.close_position(pid, exit_price, "take_profit")
                closed_trades.append(trade)
                continue

            # --- Trailing stop update (if configured) ---
            if pos.trailing_stop is not None:
                # Trail only tightens, never loosens
                new_trail = pos.highest_price - (pos.entry_price - pos.trailing_stop)
                if new_trail > pos.trailing_stop:
                    pos.trailing_stop = new_trail
                if current_price <= pos.trailing_stop:
                    trade = self.close_position(pid, pos.trailing_stop, "trailing_stop")
                    closed_trades.append(trade)
                    continue

        return closed_trades

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_open_positions(self) -> list[PaperPosition]:
        """Return all currently open positions."""
        return list(self.positions.values())

    def get_unrealized_pnl(self, current_price: float) -> float:
        """Sum of unrealised P&L across all open positions."""
        total = 0.0
        for pos in self.positions.values():
            if pos.side == "long":
                total += (current_price - pos.entry_price) * pos.size
            else:
                total += (pos.entry_price - current_price) * pos.size
        return total

    def has_open_position(self, symbol: str = "BTCUSDT") -> bool:
        """Check whether there is at least one open position for *symbol*."""
        return any(pos.symbol == symbol for pos in self.positions.values())

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize all positions and internal state for persistence."""
        positions_data: list[dict] = []
        for pos in self.positions.values():
            positions_data.append({
                "position_id": pos.position_id,
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "entry_time": str(pos.entry_time),
                "size": pos.size,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "strategy_name": pos.strategy_name,
                "highest_price": pos.highest_price,
                "trailing_stop": pos.trailing_stop,
                "partial_closed": pos.partial_closed,
                "metadata": pos.metadata,
            })
        return {
            "positions": positions_data,
            "next_id": self._next_id,
        }

    def from_dict(self, data: dict) -> None:
        """Restore positions and internal state from a persisted dict."""
        self._next_id = data.get("next_id", 1)
        self.positions.clear()

        for p in data.get("positions", []):
            pos = PaperPosition(
                position_id=p["position_id"],
                symbol=p["symbol"],
                side=p["side"],
                entry_price=p["entry_price"],
                entry_time=pd.Timestamp(p["entry_time"]),
                size=p["size"],
                stop_loss=p["stop_loss"],
                take_profit=p.get("take_profit"),
                strategy_name=p.get("strategy_name", ""),
                highest_price=p.get("highest_price", p["entry_price"]),
                trailing_stop=p.get("trailing_stop"),
                partial_closed=p.get("partial_closed", False),
                metadata=p.get("metadata", {}),
            )
            self.positions[pos.position_id] = pos

        logger.info(
            "Restored {} positions from persisted state",
            len(self.positions),
        )
