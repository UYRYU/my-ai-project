"""Risk management for live and paper trading.

Enforces position sizing rules, drawdown limits, daily loss caps,
and circuit-breaker logic to protect capital.
"""

from __future__ import annotations

from loguru import logger


class RiskManager:
    """Evaluate whether trades are permitted and compute safe position sizes.

    Parameters
    ----------
    config : dict
        Keys consumed: ``initial_capital``, ``risk_per_trade_pct``,
        ``max_drawdown_pct``, ``max_daily_loss_pct``, ``max_open_positions``,
        ``min_order_size_btc``.
    """

    def __init__(self, config: dict) -> None:
        self.initial_capital: float = config.get("initial_capital", 10000.0)
        self.risk_per_trade_pct: float = config.get("risk_per_trade_pct", 2.0)
        self.max_drawdown_pct: float = config.get("max_drawdown_pct", 15.0)
        self.max_daily_loss_pct: float = config.get("max_daily_loss_pct", 5.0)
        self.max_open_positions: int = config.get("max_open_positions", 1)
        self.min_order_size: float = config.get("min_order_size_btc", 0.0001)

        logger.info(
            "RiskManager initialised: risk/trade={:.1f}%, max_dd={:.1f}%, "
            "daily_loss={:.1f}%, max_positions={}",
            self.risk_per_trade_pct,
            self.max_drawdown_pct,
            self.max_daily_loss_pct,
            self.max_open_positions,
        )

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def calc_position_size(
        self,
        capital: float,
        entry_price: float,
        stop_loss: float,
    ) -> float:
        """Calculate position size in BTC based on fixed-fractional risk.

        Risk amount = capital * risk_per_trade_pct / 100
        Distance   = abs(entry_price - stop_loss)
        Size (BTC) = risk_amount / distance

        The result is clamped to ``min_order_size`` at the low end and to
        ``capital / entry_price`` at the high end (cannot buy more BTC than
        capital allows).

        Returns
        -------
        float
            Position size in BTC, or 0.0 if the trade is not viable.
        """
        distance = abs(entry_price - stop_loss)
        if distance <= 0:
            logger.warning(
                "Invalid SL distance (entry={}, sl={}), returning 0 size",
                entry_price,
                stop_loss,
            )
            return 0.0

        if entry_price <= 0 or capital <= 0:
            return 0.0

        risk_amount = capital * self.risk_per_trade_pct / 100.0
        size = risk_amount / distance

        # Cap to affordable amount
        max_affordable = capital / entry_price
        size = min(size, max_affordable)

        # Enforce minimum order size
        if size < self.min_order_size:
            logger.warning(
                "Calculated size {:.8f} BTC below minimum {:.8f}, returning min",
                size,
                self.min_order_size,
            )
            # If even the minimum is too expensive, return 0
            if self.min_order_size * entry_price > capital:
                return 0.0
            return self.min_order_size

        logger.debug(
            "Position size: {:.6f} BTC (risk ${:.2f}, distance ${:.2f})",
            size,
            risk_amount,
            distance,
        )
        return size

    # ------------------------------------------------------------------
    # Trade permission checks
    # ------------------------------------------------------------------

    def check_trade_allowed(
        self,
        current_equity: float,
        peak_equity: float,
        daily_pnl: float,
        open_positions: int,
    ) -> tuple[bool, str]:
        """Check whether opening a new trade is permitted.

        Returns
        -------
        tuple[bool, str]
            ``(True, "")`` if allowed, ``(False, reason)`` if blocked.
        """
        # --- Max drawdown check ---
        if peak_equity > 0:
            drawdown_pct = (peak_equity - current_equity) / peak_equity * 100.0
            if drawdown_pct >= self.max_drawdown_pct:
                reason = (
                    f"Max drawdown breached: {drawdown_pct:.1f}% >= "
                    f"{self.max_drawdown_pct:.1f}%"
                )
                logger.warning(reason)
                return False, reason

        # --- Max daily loss check ---
        if self.initial_capital > 0:
            daily_loss_pct = abs(min(daily_pnl, 0.0)) / self.initial_capital * 100.0
            if daily_loss_pct >= self.max_daily_loss_pct:
                reason = (
                    f"Max daily loss breached: {daily_loss_pct:.1f}% >= "
                    f"{self.max_daily_loss_pct:.1f}%"
                )
                logger.warning(reason)
                return False, reason

        # --- Max open positions check ---
        if open_positions >= self.max_open_positions:
            reason = (
                f"Max open positions reached: {open_positions} >= "
                f"{self.max_open_positions}"
            )
            logger.debug(reason)
            return False, reason

        return True, ""

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------

    def check_circuit_breaker(
        self, equity_history: list[dict]
    ) -> tuple[bool, str]:
        """Check if the circuit breaker should trigger (halt all trading).

        The circuit breaker fires when equity drops below
        ``initial_capital * (1 - max_drawdown_pct / 100)``.

        Parameters
        ----------
        equity_history : list[dict]
            List of ``{"timestamp": ..., "equity": float}`` snapshots.

        Returns
        -------
        tuple[bool, str]
            ``(True, reason)`` if circuit breaker is triggered,
            ``(False, "")`` otherwise.
        """
        if not equity_history:
            return False, ""

        floor = self.initial_capital * (1.0 - self.max_drawdown_pct / 100.0)
        latest_equity = equity_history[-1].get("equity", self.initial_capital)

        if latest_equity < floor:
            reason = (
                f"Circuit breaker triggered: equity ${latest_equity:.2f} "
                f"< floor ${floor:.2f} "
                f"(initial ${self.initial_capital:.2f}, "
                f"max_dd {self.max_drawdown_pct:.1f}%)"
            )
            logger.error(reason)
            return True, reason

        return False, ""
