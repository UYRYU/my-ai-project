"""Pullback Strict Strategy -- stricter pullback with anti-FOMO filter.

Enhanced version of PullbackStrategy designed for real data.  Requires bull
regime *and* sufficient trend strength, filters out FOMO chases by rejecting
entries after large recent runs, and demands VWAP confirmation plus volume
surge on the recovery bar.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal


class PullbackStrictStrategy(BaseStrategy):
    """Buy pullbacks in a confirmed bull trend with strict anti-FOMO filters."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        super().__init__(name="pullback_strict", config=config)

        self.rsi_oversold: int = config.get("rsi_oversold", 48)
        self.rsi_recovery: int = config.get("rsi_recovery", 55)
        self.anti_fomo_pct: float = config.get("anti_fomo_pct", 8.0)
        self.anti_fomo_bars: int = config.get("anti_fomo_bars", 20)
        self.trend_strength_min: float = config.get("trend_strength_min", 0.5)
        self.atr_sl_mult: float = config.get("atr_sl_mult", 2.0)
        self.swing_low_lookback: int = config.get("swing_low_lookback", 10)

    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Scan *df* for strict pullback buy setups."""

        signals: list[Signal] = []

        if df.empty or len(df) < self.anti_fomo_bars + 1:
            return signals

        close = df["close"]
        open_ = df["open"]
        low = df["low"]
        volume = df["volume"]
        rsi = df["rsi"]
        atr = df["atr"]
        ema20 = df["ema20"]
        ema50 = df["ema50"]
        vwap = df["vwap"]
        volume_sma = df["volume_sma"]
        trend_regime = df["trend_regime"]
        trend_strength = df["trend_strength"]
        overextended = df["overextended"]

        dipped = False

        for i in range(self.anti_fomo_bars, len(df)):
            # ---- Regime filter ----
            if trend_regime.iloc[i] != "bull":
                dipped = False
                continue

            if pd.isna(trend_strength.iloc[i]) or trend_strength.iloc[i] <= self.trend_strength_min:
                dipped = False
                continue

            # ---- Anti-FOMO: reject if price rallied too much recently ----
            ref_close = close.iloc[i - self.anti_fomo_bars]
            if ref_close > 0 and (close.iloc[i] - ref_close) / ref_close * 100 > self.anti_fomo_pct:
                dipped = False
                continue

            # ---- RSI dip detection ----
            current_rsi = rsi.iloc[i]
            prev_rsi = rsi.iloc[i - 1]

            if pd.isna(current_rsi) or pd.isna(prev_rsi):
                continue

            if current_rsi < self.rsi_oversold:
                dipped = True
                continue

            if not dipped:
                continue

            # ---- RSI recovery crossing ----
            if not (prev_rsi < self.rsi_recovery and current_rsi >= self.rsi_recovery):
                continue

            # ---- Price above EMA20 and EMA50 ----
            if pd.isna(ema20.iloc[i]) or pd.isna(ema50.iloc[i]):
                continue
            if close.iloc[i] <= ema20.iloc[i] or close.iloc[i] <= ema50.iloc[i]:
                continue

            # ---- Close above VWAP ----
            if pd.isna(vwap.iloc[i]) or close.iloc[i] <= vwap.iloc[i]:
                continue

            # ---- Volume confirmation (recovery bar volume > volume_sma * 1.1) ----
            if pd.isna(volume_sma.iloc[i]) or volume.iloc[i] <= volume_sma.iloc[i] * 1.1:
                continue

            # ---- Bullish candle check ----
            prev_bullish = close.iloc[i - 1] > open_.iloc[i - 1]
            curr_strongly_bullish = (close.iloc[i] - open_.iloc[i]) > atr.iloc[i] * 0.5
            if not (prev_bullish or curr_strongly_bullish):
                continue

            # ---- Not overextended ----
            if overextended.iloc[i]:
                continue

            # ---- Stop loss ----
            swing_start = max(0, i - self.swing_low_lookback)
            swing_low = low.iloc[swing_start: i + 1].min()
            atr_sl = close.iloc[i] - self.atr_sl_mult * atr.iloc[i]
            stop_loss = max(swing_low, atr_sl)

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
                        f"Strict pullback recovery: RSI dipped below {self.rsi_oversold} "
                        f"then recovered above {self.rsi_recovery} "
                        f"(RSI={current_rsi:.1f}), above EMA20/EMA50/VWAP, "
                        f"volume confirmed, anti-FOMO passed"
                    ),
                    "rsi": round(current_rsi, 2),
                    "trend_strength": round(float(trend_strength.iloc[i]), 4),
                    "atr": round(float(atr.iloc[i]), 2),
                },
            )
            signals.append(signal)
            logger.info(
                "PullbackStrict signal at {}: entry={:.2f}, sl={:.2f}, RSI={:.1f}",
                ts,
                close.iloc[i],
                stop_loss,
                current_rsi,
            )
            dipped = False

        return signals

    # ------------------------------------------------------------------
    def get_param_space(self) -> dict:
        """Return optimizable parameter ranges."""
        return {
            "rsi_oversold": (38, 52),
            "rsi_recovery": (50, 65),
            "anti_fomo_pct": (5.0, 15.0),
            "trend_strength_min": (0.3, 0.7),
            "atr_sl_mult": (1.5, 3.0),
        }
