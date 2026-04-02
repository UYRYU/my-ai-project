"""Multi-Timeframe Strategy -- aligns a higher timeframe bull trend with
lower timeframe entry signals (pullback or breakout) for precise long entries.

Takes two DataFrames: a higher timeframe (e.g. 4h) for trend confirmation
and an entry timeframe (e.g. 15m) for signal generation. The higher TF must
show a bull regime before any entry-level signals are considered.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from loguru import logger

from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal
from btc_trend_bot.indicators.trend import (
    calc_atr,
    calc_ema,
    calc_rsi,
    calc_volume_sma,
)


class MultiTFStrategy(BaseStrategy):
    """Align higher-TF trend with lower-TF entry signals for long entries."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        super().__init__(name="multi_tf", config=config)

        # Higher timeframe parameters
        self.higher_tf_ema: int = config.get("higher_tf_ema", 200)
        self.higher_tf_ema_fast: int = config.get("higher_tf_ema_fast", 50)

        # Entry timeframe parameters
        self.rsi_period: int = config.get("rsi_period", 14)
        self.rsi_entry: int = config.get("rsi_entry", 35)
        self.rsi_recovery: int = config.get("rsi_recovery", 50)
        self.ema_entry_period: int = config.get("ema_entry_period", 21)
        self.breakout_lookback: int = config.get("breakout_lookback", 15)
        self.volume_sma_period: int = config.get("volume_sma_period", 20)
        self.volume_mult: float = config.get("volume_mult", 1.3)
        self.atr_period: int = config.get("atr_period", 14)
        self.atr_sl_mult: float = config.get("atr_sl_mult", 2.0)

        # Higher TF data set externally before calling generate_signals
        self.higher_tf_df: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------
    def set_higher_tf_data(self, higher_tf_df: pd.DataFrame) -> None:
        """Set the higher timeframe DataFrame before generating signals.

        Args:
            higher_tf_df: OHLCV DataFrame at higher timeframe (e.g. 4h)
                          with optional 'trend_regime' column.
        """
        self.higher_tf_df = higher_tf_df

    # ------------------------------------------------------------------
    def _is_higher_tf_bullish(self, entry_timestamp: pd.Timestamp) -> bool:
        """Check if the higher timeframe trend is bullish at the given time.

        Finds the most recent higher-TF bar at or before *entry_timestamp*
        and checks its trend regime and EMA alignment.
        """
        if self.higher_tf_df is None or self.higher_tf_df.empty:
            return False

        htf = self.higher_tf_df

        # Ensure EMAs are computed on higher TF
        if "ema_slow" not in htf.columns:
            htf = htf.copy()
            htf["ema_slow"] = calc_ema(htf, column="close", period=self.higher_tf_ema)
            htf["ema_fast"] = calc_ema(htf, column="close", period=self.higher_tf_ema_fast)
            self.higher_tf_df = htf

        # Find the latest higher-TF bar at or before entry_timestamp
        if isinstance(htf.index, pd.DatetimeIndex):
            mask = htf.index <= entry_timestamp
            if not mask.any():
                return False
            idx = htf.index[mask][-1]
            row = htf.loc[idx]
        else:
            # Fall back to last row if index is not datetime
            row = htf.iloc[-1]

        # Check explicit trend_regime if available
        trend_regime = htf.get("trend_regime")
        if trend_regime is not None:
            regime_val = row.get("trend_regime") if isinstance(row, pd.Series) else None
            if regime_val is not None and regime_val == "bull":
                return True
            if regime_val is not None and regime_val != "bull":
                return False

        # Fallback: EMA alignment (fast > slow and price above both)
        close_val = row["close"] if isinstance(row, pd.Series) else row
        ema_fast_val = row.get("ema_fast", None) if isinstance(row, pd.Series) else None
        ema_slow_val = row.get("ema_slow", None) if isinstance(row, pd.Series) else None

        if ema_fast_val is None or ema_slow_val is None:
            return False
        if pd.isna(ema_fast_val) or pd.isna(ema_slow_val):
            return False

        return float(close_val) > float(ema_slow_val) and float(ema_fast_val) > float(ema_slow_val)

    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Generate entry signals on the entry timeframe, filtered by higher TF trend.

        Args:
            df: Entry-timeframe OHLCV DataFrame (e.g. 15m bars).

        Returns:
            List of long signals where higher TF confirms bull trend.
        """
        signals: list[Signal] = []

        if df.empty:
            return signals

        if self.higher_tf_df is None:
            logger.warning("MultiTFStrategy: higher_tf_df not set, no signals generated")
            return signals

        # Pre-compute entry-TF indicators if missing
        if "rsi" not in df.columns:
            df = df.copy()
            df["rsi"] = calc_rsi(df, period=self.rsi_period)
        if "ema_entry" not in df.columns:
            df = df.copy()
            df["ema_entry"] = calc_ema(df, column="close", period=self.ema_entry_period)
        if "atr" not in df.columns:
            df = df.copy()
            df["atr"] = calc_atr(df, period=self.atr_period)
        if "volume_sma" not in df.columns:
            df = df.copy()
            df["volume_sma"] = calc_volume_sma(df, period=self.volume_sma_period)

        rsi = df["rsi"]
        close = df["close"]
        high = df["high"]
        volume = df["volume"]
        atr = df["atr"]
        ema_entry = df["ema_entry"]
        volume_sma = df["volume_sma"]

        # Track RSI dip state for pullback detection
        dipped = False

        min_bars = max(self.breakout_lookback, 2) + 1

        for i in range(min_bars, len(df)):
            ts = df.index[i] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now()

            # Higher TF must be bullish
            if not self._is_higher_tf_bullish(ts):
                dipped = False
                continue

            current_rsi = rsi.iloc[i]
            prev_rsi = rsi.iloc[i - 1]
            current_atr = atr.iloc[i]

            if pd.isna(current_rsi) or pd.isna(current_atr) or current_atr <= 0:
                continue

            entry_triggered = False
            reason_parts: list[str] = []

            # --- Signal Type 1: Pullback on entry TF ---
            if current_rsi < self.rsi_entry:
                dipped = True

            if dipped and prev_rsi < self.rsi_recovery and current_rsi >= self.rsi_recovery:
                if close.iloc[i] > ema_entry.iloc[i]:
                    entry_triggered = True
                    reason_parts.append(
                        f"Entry-TF pullback: RSI dipped below {self.rsi_entry} "
                        f"then recovered above {self.rsi_recovery} "
                        f"(RSI={current_rsi:.1f}), price above EMA{self.ema_entry_period}"
                    )
                    dipped = False

            # --- Signal Type 2: Breakout on entry TF ---
            if not entry_triggered:
                lookback_start = i - self.breakout_lookback
                highest_high = high.iloc[lookback_start:i].max()

                if close.iloc[i] > highest_high:
                    vol_threshold = volume_sma.iloc[i] * self.volume_mult
                    if not pd.isna(volume_sma.iloc[i]) and volume.iloc[i] > vol_threshold:
                        entry_triggered = True
                        reason_parts.append(
                            f"Entry-TF breakout: close above {self.breakout_lookback}-bar "
                            f"high ({highest_high:.2f}), volume "
                            f"{volume.iloc[i]:.0f} > {vol_threshold:.0f}"
                        )

            if not entry_triggered:
                continue

            # Calculate ATR-based stop loss on entry timeframe
            stop_loss = close.iloc[i] - self.atr_sl_mult * current_atr

            # Ensure SL is below entry
            if stop_loss >= close.iloc[i]:
                stop_loss = close.iloc[i] - current_atr

            reason = "Multi-TF alignment (higher TF bull). " + "; ".join(reason_parts)

            signal = Signal(
                timestamp=ts,
                direction="long",
                entry_price=close.iloc[i],
                stop_loss=stop_loss,
                take_profit=None,
                size_pct=100.0,
                strategy_name=self.name,
                metadata={
                    "reason": reason,
                    "rsi": round(current_rsi, 2),
                    "atr": round(current_atr, 2),
                    "ema_entry": round(ema_entry.iloc[i], 2),
                },
            )
            signals.append(signal)
            logger.info(
                "Multi-TF signal at {}: entry={:.2f}, sl={:.2f}, RSI={:.1f}",
                ts,
                close.iloc[i],
                stop_loss,
                current_rsi,
            )

        return signals

    # ------------------------------------------------------------------
    def get_param_space(self) -> dict:
        """Return optimizable parameter ranges."""
        return {
            "higher_tf_ema": (150, 250),
            "rsi_entry": (30, 45),
        }
