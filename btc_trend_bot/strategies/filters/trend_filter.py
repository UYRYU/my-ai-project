"""
Trend Filters for Strategy Signal Validation
=============================================
Filters that can be applied to any strategy's signals to reduce false entries.
"""

from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from btc_trend_bot.indicators.trend import calc_atr, calc_ema, calc_adx, calc_volume_sma


class TrendFilter:
    """Collection of filters to validate trading signals in uptrend context."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def apply_all_filters(
        self,
        df: pd.DataFrame,
        signal_mask: pd.Series,
    ) -> pd.Series:
        """Apply all configured filters to a signal mask.

        Args:
            df: OHLCV DataFrame with indicators
            signal_mask: Boolean series where True = potential signal

        Returns:
            Filtered boolean series
        """
        filtered = signal_mask.copy()

        # 1. Must be in uptrend
        filtered = self.filter_trend_regime(df, filtered)

        # 2. Not overextended
        filtered = self.filter_overextended(df, filtered)

        # 3. Minimum volatility
        filtered = self.filter_min_volatility(df, filtered)

        # 4. Volume confirmation
        filtered = self.filter_volume(df, filtered)

        # 5. No rapid consecutive signals
        filtered = self.filter_signal_spacing(filtered)

        original_count = signal_mask.sum()
        filtered_count = filtered.sum()
        if original_count > 0:
            logger.debug(
                f"Filters: {original_count} -> {filtered_count} signals "
                f"({filtered_count/original_count*100:.0f}% passed)"
            )

        return filtered

    def filter_trend_regime(
        self, df: pd.DataFrame, mask: pd.Series
    ) -> pd.Series:
        """Only allow signals when trend regime is bullish."""
        if "trend_regime" in df.columns:
            return mask & (df["trend_regime"] == "bull")
        # Fallback: check EMA alignment
        if "ema_50" in df.columns and "ema_200" in df.columns:
            return mask & (df["ema_50"] > df["ema_200"]) & (df["close"] > df["ema_200"])
        return mask

    def filter_overextended(
        self, df: pd.DataFrame, mask: pd.Series
    ) -> pd.Series:
        """Block signals when price is too far above 200 EMA (anti-FOMO)."""
        max_dist = self.config.get("max_distance_from_ema200_pct", 15.0)
        if "ema_200" in df.columns:
            distance_pct = (df["close"] - df["ema_200"]) / df["ema_200"] * 100
            return mask & (distance_pct < max_dist)
        return mask

    def filter_min_volatility(
        self, df: pd.DataFrame, mask: pd.Series
    ) -> pd.Series:
        """Block signals when volatility is too low (dead market)."""
        min_atr_pct = self.config.get("min_atr_pct", 0.5)
        if "atr" in df.columns:
            atr_pct = df["atr"] / df["close"] * 100
            return mask & (atr_pct >= min_atr_pct)
        return mask

    def filter_volume(
        self, df: pd.DataFrame, mask: pd.Series
    ) -> pd.Series:
        """Require minimum volume activity."""
        vol_ratio = self.config.get("volume_increase_ratio", 1.0)
        if "volume_sma" in df.columns:
            return mask & (df["volume"] >= df["volume_sma"] * vol_ratio)
        return mask

    def filter_signal_spacing(
        self, mask: pd.Series, min_bars: int = 5
    ) -> pd.Series:
        """Prevent rapid-fire signals. Minimum spacing between signals."""
        min_bars = self.config.get("min_signal_spacing", min_bars)
        filtered = mask.copy()
        last_signal_idx = -min_bars - 1

        for i in range(len(filtered)):
            if filtered.iloc[i]:
                if i - last_signal_idx < min_bars:
                    filtered.iloc[i] = False
                else:
                    last_signal_idx = i

        return filtered

    def filter_no_top_chasing(
        self, df: pd.DataFrame, mask: pd.Series, lookback: int = 50
    ) -> pd.Series:
        """Avoid entering after a parabolic move up.

        If price has risen too fast in recent bars, skip the signal.
        """
        max_recent_gain = self.config.get("max_recent_gain_pct", 20.0)
        recent_return = (df["close"] / df["close"].shift(lookback) - 1) * 100
        return mask & (recent_return < max_recent_gain)
