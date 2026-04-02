"""Reacceleration Quality Strategy -- squeeze release with trend quality check.

Detects Bollinger-Keltner squeeze releases that occur within an already
established uptrend.  Requires ADX to be rising, directional alignment,
and enough energy on the release bar to filter out weak range breaks.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal


class ReaccelerationQualityStrategy(BaseStrategy):
    """Enter long on quality squeeze releases within established uptrends."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        super().__init__(name="reacceleration_quality", config=config)

        self.squeeze_lookback: int = config.get("squeeze_lookback", 5)
        self.adx_rise_bars: int = config.get("adx_rise_bars", 3)
        self.adx_min: float = config.get("adx_min", 20)
        self.trend_strength_min: float = config.get("trend_strength_min", 0.4)
        self.range_break_pct: float = config.get("range_break_pct", 0.5)
        self.atr_sl_mult: float = config.get("atr_sl_mult", 2.0)
        self.pre_trend_bars: int = config.get("pre_trend_bars", 20)

    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Scan *df* for quality squeeze-release entries."""

        signals: list[Signal] = []

        min_history = self.pre_trend_bars + self.squeeze_lookback + 1
        if df.empty or len(df) < min_history:
            return signals

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        atr = df["atr"]
        adx = df["adx"]
        plus_di = df["plus_di"]
        minus_di = df["minus_di"]
        ema20 = df["ema20"]
        ema50 = df["ema50"]
        ema200 = df["ema200"]
        volume_sma = df["volume_sma"]
        squeeze = df["squeeze"]
        kc_lower = df["kc_lower"]
        trend_regime = df["trend_regime"]
        trend_strength = df["trend_strength"]
        overextended = df["overextended"]

        for i in range(min_history, len(df)):
            # ---- Regime filter ----
            if trend_regime.iloc[i] != "bull":
                continue

            if pd.isna(trend_strength.iloc[i]) or trend_strength.iloc[i] <= self.trend_strength_min:
                continue

            # ---- Not overextended ----
            if overextended.iloc[i]:
                continue

            # ---- Squeeze release detection ----
            # Current bar must NOT be in squeeze
            if squeeze.iloc[i]:
                continue

            # One of the previous squeeze_lookback bars must have been in squeeze
            squeeze_window = squeeze.iloc[max(0, i - self.squeeze_lookback): i]
            if not squeeze_window.any():
                continue

            # ---- Pre-squeeze trend quality: EMA50 > EMA200 for pre_trend_bars ----
            # Find the start of the squeeze period
            squeeze_start = i - self.squeeze_lookback
            pre_start = max(0, squeeze_start - self.pre_trend_bars)
            pre_window_ema50 = ema50.iloc[pre_start: squeeze_start]
            pre_window_ema200 = ema200.iloc[pre_start: squeeze_start]

            if pre_window_ema50.empty or pre_window_ema200.empty:
                continue
            if not (pre_window_ema50 > pre_window_ema200).all():
                continue

            # ---- ADX rising ----
            if pd.isna(adx.iloc[i]) or pd.isna(adx.iloc[max(0, i - self.adx_rise_bars)]):
                continue
            if adx.iloc[i] <= adx.iloc[i - self.adx_rise_bars]:
                continue

            # ---- ADX minimum ----
            if adx.iloc[i] <= self.adx_min:
                continue

            # ---- Directional alignment ----
            if pd.isna(plus_di.iloc[i]) or pd.isna(minus_di.iloc[i]):
                continue
            if plus_di.iloc[i] <= minus_di.iloc[i]:
                continue

            # ---- Price above EMA20 ----
            if pd.isna(ema20.iloc[i]) or close.iloc[i] <= ema20.iloc[i]:
                continue

            # ---- Volume confirmation on release bar ----
            if pd.isna(volume_sma.iloc[i]) or volume.iloc[i] <= volume_sma.iloc[i]:
                continue

            # ---- Weak range break filter ----
            # Compute the squeeze range (max high - min low during the squeeze window)
            squeeze_high = high.iloc[max(0, i - self.squeeze_lookback): i].max()
            squeeze_low = low.iloc[max(0, i - self.squeeze_lookback): i].min()
            squeeze_range = squeeze_high - squeeze_low

            # The break must exceed the squeeze range by range_break_pct * ATR
            if pd.isna(atr.iloc[i]):
                continue
            break_amount = close.iloc[i] - squeeze_high
            if break_amount < self.range_break_pct * atr.iloc[i]:
                continue

            # ---- Stop loss ----
            kc_sl = kc_lower.iloc[i] if not pd.isna(kc_lower.iloc[i]) else close.iloc[i] - self.atr_sl_mult * atr.iloc[i]
            atr_sl = close.iloc[i] - self.atr_sl_mult * atr.iloc[i]
            stop_loss = min(kc_sl, atr_sl)

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
                        f"Squeeze release with quality trend: ADX={adx.iloc[i]:.1f} (rising), "
                        f"+DI={plus_di.iloc[i]:.1f} > -DI={minus_di.iloc[i]:.1f}, "
                        f"break above squeeze range by {break_amount:.2f}, "
                        f"trend_strength={trend_strength.iloc[i]:.2f}"
                    ),
                    "adx": round(float(adx.iloc[i]), 2),
                    "squeeze_range": round(float(squeeze_range), 2),
                    "break_amount": round(float(break_amount), 2),
                    "trend_strength": round(float(trend_strength.iloc[i]), 4),
                    "atr": round(float(atr.iloc[i]), 2),
                },
            )
            signals.append(signal)
            logger.info(
                "ReaccelerationQuality signal at {}: entry={:.2f}, sl={:.2f}, ADX={:.1f}",
                ts,
                close.iloc[i],
                stop_loss,
                adx.iloc[i],
            )

        return signals

    # ------------------------------------------------------------------
    def get_param_space(self) -> dict:
        """Return optimizable parameter ranges."""
        return {
            "squeeze_lookback": (3, 8),
            "adx_rise_bars": (2, 5),
            "adx_min": (15, 30),
            "trend_strength_min": (0.3, 0.6),
            "atr_sl_mult": (1.5, 3.0),
        }
