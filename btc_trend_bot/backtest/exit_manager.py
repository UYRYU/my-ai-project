"""Exit management for open positions in the BTC Trend Long Bot backtest.

Implements multiple exit strategies (fixed RR, ATR trailing, swing low,
EMA break, partial trail, volume fade) and stop-loss methods (ATR-based,
swing-low, time-based, breakeven).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


# ---------------------------------------------------------------------------
# Position data-class
# ---------------------------------------------------------------------------

@dataclass
class Position:
    """Represents an open position tracked by the backtest engine."""

    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    direction: str  # "long" or "short"
    size: float  # quantity (units of BTC)
    strategy_name: str = ""
    metadata: dict = field(default_factory=dict)

    # Tracking fields updated each bar
    highest_price_since_entry: float = 0.0
    lowest_price_since_entry: float = 0.0
    bars_held: int = 0

    # Partial-trail bookkeeping
    partial_closed: bool = False
    remaining_size_pct: float = 100.0

    def __post_init__(self) -> None:
        if self.highest_price_since_entry == 0.0:
            self.highest_price_since_entry = self.entry_price
        if self.lowest_price_since_entry == 0.0:
            self.lowest_price_since_entry = self.entry_price

    @property
    def is_short(self) -> bool:
        return self.direction == "short"


# ---------------------------------------------------------------------------
# ExitManager
# ---------------------------------------------------------------------------

class ExitManager:
    """Manages all exit logic for open positions.

    Parameters
    ----------
    config : dict
        The ``exit`` section from *settings.yaml*.  Expected keys include
        ``methods``, ``fixed_rr_ratios``, ``atr_trailing``, ``swing_low``,
        ``ema_break``, ``partial_trail``, ``volume_fade``, ``stoploss``.
    """

    def __init__(self, config: dict) -> None:
        self.config = config

        # Active exit method — the engine picks the first matching method in
        # order unless overridden by a specific strategy's signal metadata.
        self.method: str = config.get("method", "atr_trailing")

        # Exit-method parameters
        self.fixed_rr_ratios: list[float] = config.get("fixed_rr_ratios", [2.0, 3.0, 5.0])

        atr_cfg = config.get("atr_trailing", {})
        self.atr_trail_mult: float = atr_cfg.get("multiplier", 2.5)
        self.atr_trail_warmup: int = atr_cfg.get("warmup_bars", 5)

        self.swing_low_lookback: int = config.get("swing_low", {}).get("lookback", 5)

        self.ema_break_period: int = config.get("ema_break", {}).get("period", 20)

        pt_cfg = config.get("partial_trail", {})
        self.partial_first_tp_rr: float = pt_cfg.get("first_tp_rr", 1.5)
        self.partial_first_tp_pct: float = pt_cfg.get("first_tp_pct", 50.0)
        self.partial_trail_atr_mult: float = pt_cfg.get("trail_atr_mult", 2.0)

        vf_cfg = config.get("volume_fade", {})
        self.volume_fade_lookback: int = vf_cfg.get("lookback", 10)
        self.volume_fade_ratio: float = vf_cfg.get("fade_ratio", 0.5)

        # Stop-loss parameters
        sl_cfg = config.get("stoploss", {})
        self.sl_methods: list[str] = sl_cfg.get("methods", ["atr"])
        self.sl_atr_mult: float = sl_cfg.get("atr_mult", 1.5)
        self.sl_time_limit_bars: int = sl_cfg.get("time_limit_bars", 50)
        self.breakeven_after_rr: float = sl_cfg.get("breakeven_after_rr", 1.0)
        self.breakeven_enabled: bool = sl_cfg.get("breakeven_enabled", True)

        logger.debug(
            "ExitManager initialised: method={}, sl_methods={}",
            self.method,
            self.sl_methods,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_exit(
        self,
        position: Position,
        current_bar: pd.Series,
        df_history: pd.DataFrame,
    ) -> Optional[dict]:
        """Check whether *position* should be exited on *current_bar*.

        Parameters
        ----------
        position : Position
            The currently open position.
        current_bar : pd.Series
            OHLCV bar (must contain ``open``, ``high``, ``low``, ``close``,
            ``volume``) and any indicator columns.
        df_history : pd.DataFrame
            All bars up to and including *current_bar* (for look-back calcs).

        Returns
        -------
        dict | None
            ``{"exit_price": float, "exit_reason": str}`` when an exit is
            triggered, otherwise ``None``.
        """
        high = float(current_bar["high"])
        low = float(current_bar["low"])
        close = float(current_bar["close"])

        # Update tracking state
        position.bars_held += 1
        if high > position.highest_price_since_entry:
            position.highest_price_since_entry = high
        if low < position.lowest_price_since_entry:
            position.lowest_price_since_entry = low

        # --- Breakeven adjustment ---
        if self.breakeven_enabled:
            self._maybe_move_to_breakeven(position)

        # --- Stop-loss checks (always active) ---
        sl_exit = self._check_stoploss(position, current_bar, df_history)
        if sl_exit is not None:
            return sl_exit

        # --- Dispatch to active exit method ---
        method = position.metadata.get("exit_method", self.method)
        dispatch = {
            "fixed_rr": self._check_fixed_rr,
            "atr_trailing": self._check_atr_trailing,
            "swing_low": self._check_swing_low,
            "ema_break": self._check_ema_break,
            "partial_trail": self._check_partial_trail,
            "volume_fade": self._check_volume_fade,
        }

        handler = dispatch.get(method)
        if handler is None:
            logger.warning("Unknown exit method '{}', falling back to atr_trailing", method)
            handler = self._check_atr_trailing

        return handler(position, current_bar, df_history)

    # ------------------------------------------------------------------
    # Stop-loss checks
    # ------------------------------------------------------------------

    def _maybe_move_to_breakeven(self, position: Position) -> None:
        """Move stop-loss to entry price once the position reaches the
        configured breakeven RR threshold."""
        risk = abs(position.entry_price - position.stop_loss)
        if risk <= 0:
            return
        if position.is_short:
            current_rr = (position.entry_price - position.lowest_price_since_entry) / risk
            if current_rr >= self.breakeven_after_rr and position.stop_loss > position.entry_price:
                position.stop_loss = position.entry_price
        else:
            current_rr = (position.highest_price_since_entry - position.entry_price) / risk
            if current_rr >= self.breakeven_after_rr and position.stop_loss < position.entry_price:
                position.stop_loss = position.entry_price

    def _check_stoploss(
        self,
        position: Position,
        current_bar: pd.Series,
        df_history: pd.DataFrame,
    ) -> Optional[dict]:
        """Evaluate all active SL methods. Returns exit dict or None."""
        high = float(current_bar["high"])
        low = float(current_bar["low"])

        # --- Fixed / ATR stop-loss hit ---
        if position.is_short:
            sl_hit = high >= position.stop_loss
        else:
            sl_hit = low <= position.stop_loss

        if sl_hit:
            logger.info(
                "SL hit: strategy={}, entry={:.2f}, sl={:.2f}",
                position.strategy_name,
                position.entry_price,
                position.stop_loss,
            )
            return {"exit_price": position.stop_loss, "exit_reason": "stop_loss"}

        # --- Time-based exit ---
        if "time_based" in self.sl_methods:
            if position.bars_held >= self.sl_time_limit_bars:
                logger.info(
                    "Time-based exit after {} bars for {}",
                    position.bars_held,
                    position.strategy_name,
                )
                return {
                    "exit_price": float(current_bar["close"]),
                    "exit_reason": "time_limit",
                }

        # --- Swing SL recalculation (tighten only) ---
        if "swing_low" in self.sl_methods and len(df_history) >= self.swing_low_lookback:
            if position.is_short:
                recent_highs = df_history["high"].iloc[-self.swing_low_lookback:]
                swing_sl = float(recent_highs.max())
                if swing_sl < position.stop_loss:
                    position.stop_loss = swing_sl
            else:
                recent_lows = df_history["low"].iloc[-self.swing_low_lookback:]
                swing_sl = float(recent_lows.min())
                if swing_sl > position.stop_loss:
                    position.stop_loss = swing_sl

        return None

    # ------------------------------------------------------------------
    # Exit method implementations
    # ------------------------------------------------------------------

    def _check_fixed_rr(
        self,
        position: Position,
        current_bar: pd.Series,
        df_history: pd.DataFrame,
    ) -> Optional[dict]:
        """Exit at a fixed reward-to-risk multiple.

        Uses the *first* RR ratio from ``fixed_rr_ratios`` by default; the
        signal can override via ``metadata["rr_ratio"]``.
        """
        rr_ratio: float = position.metadata.get("rr_ratio", self.fixed_rr_ratios[0])
        risk = abs(position.entry_price - position.stop_loss)
        if risk <= 0:
            return None

        if position.is_short:
            target = position.entry_price - risk * rr_ratio
            hit = float(current_bar["low"]) <= target
        else:
            target = position.entry_price + risk * rr_ratio
            hit = float(current_bar["high"]) >= target

        if hit:
            logger.info(
                "Fixed RR {:.1f} TP hit at {:.2f} for {}",
                rr_ratio,
                target,
                position.strategy_name,
            )
            return {"exit_price": target, "exit_reason": f"fixed_rr_{rr_ratio:.1f}"}

        return None

    def _check_atr_trailing(
        self,
        position: Position,
        current_bar: pd.Series,
        df_history: pd.DataFrame,
    ) -> Optional[dict]:
        """ATR trailing stop — only tightens, never loosens."""
        if position.bars_held < self.atr_trail_warmup:
            return None

        atr = self._get_atr(df_history)
        if atr is None or atr <= 0:
            return None

        if position.is_short:
            trail_stop = position.lowest_price_since_entry + atr * self.atr_trail_mult
            if trail_stop < position.stop_loss:
                position.stop_loss = trail_stop
            high = float(current_bar["high"])
            if high >= position.stop_loss:
                return {"exit_price": position.stop_loss, "exit_reason": "atr_trailing"}
        else:
            trail_stop = position.highest_price_since_entry - atr * self.atr_trail_mult
            if trail_stop > position.stop_loss:
                position.stop_loss = trail_stop
            low = float(current_bar["low"])
            if low <= position.stop_loss:
                return {"exit_price": position.stop_loss, "exit_reason": "atr_trailing"}

        return None

    def _check_swing_low(
        self,
        position: Position,
        current_bar: pd.Series,
        df_history: pd.DataFrame,
    ) -> Optional[dict]:
        """Exit when price breaks the swing level (low for longs, high for shorts)."""
        if len(df_history) < self.swing_low_lookback + 1:
            return None

        if position.is_short:
            recent_highs = df_history["high"].iloc[-(self.swing_low_lookback + 1):-1]
            swing_level = float(recent_highs.max())
            high = float(current_bar["high"])
            if high > swing_level:
                exit_price = min(swing_level, float(current_bar["open"]))
                return {"exit_price": exit_price, "exit_reason": "swing_high_break"}
        else:
            recent_lows = df_history["low"].iloc[-(self.swing_low_lookback + 1):-1]
            swing_level = float(recent_lows.min())
            low = float(current_bar["low"])
            if low < swing_level:
                exit_price = max(swing_level, float(current_bar["open"]))
                return {"exit_price": exit_price, "exit_reason": "swing_low_break"}

        return None

    def _check_ema_break(
        self,
        position: Position,
        current_bar: pd.Series,
        df_history: pd.DataFrame,
    ) -> Optional[dict]:
        """Exit when close drops below EMA(period)."""
        if len(df_history) < self.ema_break_period:
            return None

        ema_col = f"ema_{self.ema_break_period}"
        if ema_col in current_bar.index:
            ema_val = float(current_bar[ema_col])
        else:
            ema_val = float(
                df_history["close"].iloc[-self.ema_break_period:].ewm(
                    span=self.ema_break_period, adjust=False
                ).mean().iloc[-1]
            )

        close = float(current_bar["close"])
        if position.is_short:
            if close > ema_val:
                return {"exit_price": close, "exit_reason": "ema_break"}
        else:
            if close < ema_val:
                return {"exit_price": close, "exit_reason": "ema_break"}

        return None

    def _check_partial_trail(
        self,
        position: Position,
        current_bar: pd.Series,
        df_history: pd.DataFrame,
    ) -> Optional[dict]:
        """Exit 50 % at a fixed RR target, then trail the rest with ATR."""
        risk = abs(position.entry_price - position.stop_loss)
        if risk <= 0:
            return None

        high = float(current_bar["high"])
        low = float(current_bar["low"])

        # --- Phase 1: first partial TP ---
        if not position.partial_closed:
            if position.is_short:
                target = position.entry_price - risk * self.partial_first_tp_rr
                hit = low <= target
            else:
                target = position.entry_price + risk * self.partial_first_tp_rr
                hit = high >= target

            if hit:
                position.partial_closed = True
                position.remaining_size_pct = 100.0 - self.partial_first_tp_pct
                position.stop_loss = position.entry_price
                return {
                    "exit_price": target,
                    "exit_reason": "partial_tp",
                    "partial_pct": self.partial_first_tp_pct,
                }

        # --- Phase 2: trail remaining with ATR ---
        if position.partial_closed:
            atr = self._get_atr(df_history)
            if atr is not None and atr > 0:
                if position.is_short:
                    trail_stop = position.lowest_price_since_entry + atr * self.partial_trail_atr_mult
                    if trail_stop < position.stop_loss:
                        position.stop_loss = trail_stop
                else:
                    trail_stop = position.highest_price_since_entry - atr * self.partial_trail_atr_mult
                    if trail_stop > position.stop_loss:
                        position.stop_loss = trail_stop

            if position.is_short:
                if high >= position.stop_loss:
                    return {
                        "exit_price": position.stop_loss,
                        "exit_reason": "partial_trail_stop",
                        "partial_pct": position.remaining_size_pct,
                    }
            else:
                if low <= position.stop_loss:
                    return {
                        "exit_price": position.stop_loss,
                        "exit_reason": "partial_trail_stop",
                        "partial_pct": position.remaining_size_pct,
                    }

        return None

    def _check_volume_fade(
        self,
        position: Position,
        current_bar: pd.Series,
        df_history: pd.DataFrame,
    ) -> Optional[dict]:
        """Exit when volume drops below SMA * fade_ratio after a surge.

        A *surge* is detected if at any bar during the trade the volume
        exceeded the SMA.  Once the surge has occurred, we watch for the
        volume to fade.
        """
        if len(df_history) < self.volume_fade_lookback:
            return None

        vol_window = df_history["volume"].iloc[-self.volume_fade_lookback:]
        vol_sma = float(vol_window.mean())

        if vol_sma <= 0:
            return None

        current_volume = float(current_bar["volume"])

        # Track whether a volume surge occurred during the trade lifetime
        surge_key = "_volume_surge_seen"
        if not position.metadata.get(surge_key, False):
            if current_volume > vol_sma:
                position.metadata[surge_key] = True
            return None

        # After surge, check for fade
        threshold = vol_sma * self.volume_fade_ratio
        if current_volume < threshold:
            close = float(current_bar["close"])
            logger.info(
                "Volume fade exit: vol={:.0f} < threshold={:.0f} for {}",
                current_volume,
                threshold,
                position.strategy_name,
            )
            return {"exit_price": close, "exit_reason": "volume_fade"}

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_atr(df_history: pd.DataFrame, period: int = 14) -> Optional[float]:
        """Return the latest ATR value from *df_history*.

        If an ``atr`` or ``atr_14`` column already exists it is used directly;
        otherwise ATR is computed on the fly.
        """
        for col in ("atr", f"atr_{period}"):
            if col in df_history.columns:
                val = df_history[col].iloc[-1]
                if pd.notna(val):
                    return float(val)

        if len(df_history) < period + 1:
            return None

        highs = df_history["high"].iloc[-(period + 1):]
        lows = df_history["low"].iloc[-(period + 1):]
        closes = df_history["close"].iloc[-(period + 1):]

        tr = pd.concat(
            [
                highs - lows,
                (highs - closes.shift(1)).abs(),
                (lows - closes.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr_val = float(tr.iloc[-period:].mean())
        return atr_val if atr_val > 0 else None
