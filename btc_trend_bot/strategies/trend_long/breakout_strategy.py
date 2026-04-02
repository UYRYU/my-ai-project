"""Breakout Continuation Strategy -- enters long on high-volume breakouts above
recent consolidation ranges during confirmed bull trends.

Requires a prior consolidation period (low ATR), a close above the highest
high of the lookback window, and elevated volume. Stop-loss is placed at the
bottom of the consolidation range or ATR-based distance.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal
from btc_trend_bot.indicators.trend import (
    calc_atr,
    calc_volume_sma,
)


class BreakoutStrategy(BaseStrategy):
    """Buy breakouts above consolidation in a confirmed bull trend."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        super().__init__(name="breakout", config=config)

        self.lookback: int = config.get("lookback", 20)
        self.volume_mult: float = config.get("volume_mult", 1.2)
        self.consolidation_bars: int = config.get("consolidation_bars", 5)
        self.atr_period: int = config.get("atr_period", 14)
        self.atr_sl_mult: float = config.get("atr_sl_mult", 2.0)
        self.volume_sma_period: int = config.get("volume_sma_period", 20)
        self.consolidation_atr_pct: float = config.get("consolidation_atr_pct", 0.85)
        self.min_atr_threshold_pct: float = config.get("min_atr_threshold_pct", 0.3)

    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Scan *df* for breakout setups in bull regime bars."""

        signals: list[Signal] = []

        if df.empty:
            return signals

        # Pre-compute indicators if missing
        if "atr" not in df.columns:
            df = df.copy()
            df["atr"] = calc_atr(df, period=self.atr_period)
        if "volume_sma" not in df.columns:
            df = df.copy()
            df["volume_sma"] = calc_volume_sma(df, period=self.volume_sma_period)

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        atr = df["atr"]
        volume_sma = df["volume_sma"]
        trend_regime = df.get("trend_regime")

        min_bars = max(self.lookback, self.consolidation_bars) + 1

        for i in range(min_bars, len(df)):
            # Only trade in bull regime
            if trend_regime is not None and trend_regime.iloc[i] != "bull":
                continue

            # ATR must be above minimum threshold (avoid dead markets)
            current_atr = atr.iloc[i]
            if pd.isna(current_atr) or current_atr <= 0:
                continue
            atr_pct = current_atr / close.iloc[i]
            if atr_pct < self.min_atr_threshold_pct / 100.0:
                continue

            # Highest high of lookback window (excluding current bar)
            lookback_start = i - self.lookback
            highest_high = high.iloc[lookback_start:i].max()

            # False breakout filter: close must be above the level (not just wick)
            if close.iloc[i] <= highest_high:
                continue

            # Volume must be elevated
            vol_threshold = volume_sma.iloc[i] * self.volume_mult
            if pd.isna(volume_sma.iloc[i]) or volume.iloc[i] <= vol_threshold:
                continue

            # Consolidation filter: ATR in prior bars should be relatively low
            consol_start = i - self.consolidation_bars
            consol_atr_avg = atr.iloc[consol_start:i].mean()
            overall_atr_avg = atr.iloc[max(0, i - self.lookback) : i].mean()
            if pd.isna(consol_atr_avg) or pd.isna(overall_atr_avg):
                continue
            if consol_atr_avg > overall_atr_avg * self.consolidation_atr_pct:
                continue

            # Stop loss: bottom of consolidation range or ATR-based
            consol_low = low.iloc[consol_start:i].min()
            atr_sl = close.iloc[i] - self.atr_sl_mult * current_atr
            stop_loss = max(consol_low, atr_sl)

            # Ensure SL is below entry
            if stop_loss >= close.iloc[i]:
                stop_loss = close.iloc[i] - current_atr

            ts = df.index[i] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now()

            signal = Signal(
                timestamp=ts,
                direction="long",
                entry_price=close.iloc[i],
                stop_loss=stop_loss,
                take_profit=None,
                size_pct=100.0,
                strategy_name=self.name,
                metadata={
                    "reason": (
                        f"Breakout above {self.lookback}-bar high "
                        f"({highest_high:.2f}) with volume "
                        f"{volume.iloc[i]:.0f} > {vol_threshold:.0f}, "
                        f"prior consolidation detected"
                    ),
                    "breakout_level": round(highest_high, 2),
                    "volume_ratio": round(volume.iloc[i] / volume_sma.iloc[i], 2),
                    "consolidation_atr": round(consol_atr_avg, 2),
                    "atr": round(current_atr, 2),
                },
            )
            signals.append(signal)
            logger.info(
                "Breakout signal at {}: entry={:.2f}, sl={:.2f}, breakout_level={:.2f}",
                ts,
                close.iloc[i],
                stop_loss,
                highest_high,
            )

        return signals

    # ------------------------------------------------------------------
    def get_param_space(self) -> dict:
        """Return optimizable parameter ranges."""
        return {
            "lookback": (10, 40),
            "volume_mult": (1.2, 2.5),
            "consolidation_bars": (3, 10),
        }
