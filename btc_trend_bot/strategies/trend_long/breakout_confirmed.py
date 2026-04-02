"""Breakout Confirmed Strategy -- breakout with ADX + volume double confirmation.

Enhanced breakout strategy that requires the close to break above the recent
highest high with strong ADX, directional alignment, volume surge, a solid
candle (close in upper portion of range), and a cooldown between signals
to avoid whipsaws.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal


class BreakoutConfirmedStrategy(BaseStrategy):
    """Enter long on confirmed breakouts with ADX and volume filters."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        super().__init__(name="breakout_confirmed", config=config)

        self.lookback: int = config.get("lookback", 20)
        self.volume_mult: float = config.get("volume_mult", 1.3)
        self.adx_min: float = config.get("adx_min", 22)
        self.bar_strength_min: float = config.get("bar_strength_min", 0.7)
        self.cooldown_bars: int = config.get("cooldown_bars", 5)
        self.atr_sl_mult: float = config.get("atr_sl_mult", 2.5)

    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Scan *df* for confirmed breakout entries."""

        signals: list[Signal] = []

        if df.empty or len(df) < self.lookback + 1:
            return signals

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        atr = df["atr"]
        adx = df["adx"]
        plus_di = df["plus_di"]
        minus_di = df["minus_di"]
        volume_sma = df["volume_sma"]
        trend_regime = df["trend_regime"]
        overextended = df["overextended"]

        last_signal_bar: int = -self.cooldown_bars - 1  # allow first signal

        for i in range(self.lookback, len(df)):
            # ---- Regime filter ----
            if trend_regime.iloc[i] != "bull":
                continue

            # ---- Not overextended ----
            if overextended.iloc[i]:
                continue

            # ---- Cooldown ----
            if (i - last_signal_bar) < self.cooldown_bars:
                continue

            # ---- Breakout: close above highest high of lookback period ----
            highest_high = high.iloc[i - self.lookback: i].max()
            if close.iloc[i] <= highest_high:
                continue

            # ---- Volume surge ----
            if pd.isna(volume_sma.iloc[i]) or volume.iloc[i] <= volume_sma.iloc[i] * self.volume_mult:
                continue

            # ---- ADX confirmation ----
            if pd.isna(adx.iloc[i]) or adx.iloc[i] <= self.adx_min:
                continue
            if pd.isna(plus_di.iloc[i]) or pd.isna(minus_di.iloc[i]):
                continue
            if plus_di.iloc[i] <= minus_di.iloc[i]:
                continue

            # ---- Candle range check: bar range > ATR * 0.8 ----
            bar_range = high.iloc[i] - low.iloc[i]
            if pd.isna(atr.iloc[i]) or bar_range <= atr.iloc[i] * 0.8:
                continue

            # ---- False breakout filter: close in upper portion of bar ----
            if bar_range == 0:
                continue
            bar_position = (close.iloc[i] - low.iloc[i]) / bar_range
            if bar_position < self.bar_strength_min:
                continue

            # ---- Stop loss ----
            lowest_low = low.iloc[i - self.lookback: i + 1].min()
            atr_sl = close.iloc[i] - self.atr_sl_mult * atr.iloc[i]
            stop_loss = max(lowest_low, atr_sl)

            if stop_loss >= close.iloc[i]:
                stop_loss = close.iloc[i] - atr.iloc[i]

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
                        f"Confirmed breakout above {self.lookback}-bar high "
                        f"({highest_high:.2f}), ADX={adx.iloc[i]:.1f}, "
                        f"+DI>{minus_di.iloc[i]:.1f}, volume {volume.iloc[i] / volume_sma.iloc[i]:.1f}x avg, "
                        f"bar strength={bar_position:.2f}"
                    ),
                    "adx": round(float(adx.iloc[i]), 2),
                    "bar_strength": round(bar_position, 4),
                    "atr": round(float(atr.iloc[i]), 2),
                },
            )
            signals.append(signal)
            logger.info(
                "BreakoutConfirmed signal at {}: entry={:.2f}, sl={:.2f}, ADX={:.1f}",
                ts,
                close.iloc[i],
                stop_loss,
                adx.iloc[i],
            )
            last_signal_bar = i

        return signals

    # ------------------------------------------------------------------
    def get_param_space(self) -> dict:
        """Return optimizable parameter ranges."""
        return {
            "lookback": (10, 40),
            "volume_mult": (1.0, 2.0),
            "adx_min": (18, 30),
            "bar_strength_min": (0.5, 0.9),
            "atr_sl_mult": (1.5, 3.5),
        }
