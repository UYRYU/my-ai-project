"""Trend Reacceleration Strategy -- enters long when a volatility squeeze releases
and ADX is rising, signaling renewed momentum in a bull trend.

Detects Bollinger Band squeeze (BB inside Keltner Channel) ending, combined
with rising ADX and a price breakout above the short-term range. Stop-loss
is placed at the lower Keltner Channel or ATR-based distance.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from btc_trend_bot.strategies.base_strategy import BaseStrategy, Signal
from btc_trend_bot.indicators.trend import (
    calc_adx,
    calc_atr,
    calc_keltner_channels,
    detect_squeeze,
)


class ReaccelerationStrategy(BaseStrategy):
    """Buy squeeze releases with rising ADX in a confirmed bull trend."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        super().__init__(name="reacceleration", config=config)

        self.adx_rise_bars: int = config.get("adx_rise_bars", 3)
        self.adx_min: float = config.get("adx_min", 20.0)
        self.adx_period: int = config.get("adx_period", 14)
        self.range_break_lookback: int = config.get("range_break_lookback", 10)
        self.atr_period: int = config.get("atr_period", 14)
        self.atr_sl_mult: float = config.get("atr_sl_mult", 2.0)
        self.bb_period: int = config.get("bb_period", 20)
        self.bb_std: float = config.get("bb_std", 2.0)
        self.kc_period: int = config.get("kc_period", 20)
        self.kc_mult: float = config.get("kc_mult", 1.5)

    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Scan *df* for squeeze-release reacceleration setups."""

        signals: list[Signal] = []

        if df.empty:
            return signals

        # Pre-compute indicators if missing
        if "squeeze" not in df.columns:
            df = df.copy()
            df["squeeze"] = detect_squeeze(
                df,
                bb_period=self.bb_period,
                bb_std=self.bb_std,
                kc_period=self.kc_period,
                kc_mult=self.kc_mult,
            )

        if "ADX" not in df.columns:
            df = df.copy()
            adx_df = calc_adx(df, period=self.adx_period)
            df["ADX"] = adx_df["ADX"]
            df["+DI"] = adx_df["+DI"]
            df["-DI"] = adx_df["-DI"]

        if "atr" not in df.columns:
            df = df.copy()
            df["atr"] = calc_atr(df, period=self.atr_period)

        # Compute Keltner Channel for SL reference
        kc = calc_keltner_channels(df, period=self.kc_period, mult=self.kc_mult)

        squeeze = df["squeeze"]
        adx = df["ADX"]
        close = df["close"]
        high = df["high"]
        atr = df["atr"]
        trend_regime = df.get("trend_regime")

        min_bars = max(self.adx_rise_bars, self.range_break_lookback) + 1

        for i in range(min_bars, len(df)):
            # Only trade in bull regime
            if trend_regime is not None and trend_regime.iloc[i] != "bull":
                continue

            # Squeeze release: was in squeeze, now not
            if not squeeze.iloc[i - 1] or squeeze.iloc[i]:
                continue

            # ADX must be above minimum
            current_adx = adx.iloc[i]
            if pd.isna(current_adx) or current_adx < self.adx_min:
                continue

            # ADX must be rising for N consecutive bars
            adx_rising = True
            for j in range(1, self.adx_rise_bars + 1):
                idx = i - j
                if idx < 0 or pd.isna(adx.iloc[idx + 1]) or pd.isna(adx.iloc[idx]):
                    adx_rising = False
                    break
                if adx.iloc[idx + 1] <= adx.iloc[idx]:
                    adx_rising = False
                    break
            if not adx_rising:
                continue

            # Confirm trend continuation: +DI above -DI (bullish directional bias)
            if df["+DI"].iloc[i] <= df["-DI"].iloc[i]:
                continue

            # Price must break above short-term range high
            range_start = i - self.range_break_lookback
            range_high = high.iloc[range_start:i].max()
            if close.iloc[i] <= range_high:
                continue

            # Stop loss: lower Keltner Channel or ATR-based
            kc_lower = kc["lower"].iloc[i]
            atr_sl = close.iloc[i] - self.atr_sl_mult * atr.iloc[i]
            stop_loss = max(kc_lower, atr_sl)

            # Ensure SL is below entry
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
                        f"Squeeze release with ADX rising for {self.adx_rise_bars} bars "
                        f"(ADX={current_adx:.1f}), close broke above "
                        f"{self.range_break_lookback}-bar range high ({range_high:.2f})"
                    ),
                    "adx": round(current_adx, 2),
                    "range_high": round(range_high, 2),
                    "kc_lower": round(kc_lower, 2),
                    "atr": round(atr.iloc[i], 2),
                },
            )
            signals.append(signal)
            logger.info(
                "Reacceleration signal at {}: entry={:.2f}, sl={:.2f}, ADX={:.1f}",
                ts,
                close.iloc[i],
                stop_loss,
                current_adx,
            )

        return signals

    # ------------------------------------------------------------------
    def get_param_space(self) -> dict:
        """Return optimizable parameter ranges."""
        return {
            "adx_rise_bars": (2, 5),
            "adx_min": (15, 30),
            "range_break_lookback": (5, 20),
        }
