"""
TrendDetector -- combines multiple technical indicators to classify
the market regime for the BTC Trend Long Bot.

Consumes raw OHLCV DataFrames and returns per-bar trend signals,
regime labels, and strength scores.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from btc_trend_bot.indicators.trend import (
    calc_adx,
    calc_atr,
    calc_ema,
    calc_higher_highs_higher_lows,
    calc_volume_sma,
)

# ---------------------------------------------------------------------------
# Default configuration values (mirrors settings.yaml trend_detection section)
# ---------------------------------------------------------------------------
_DEFAULTS: dict = {
    "ema_fast": 50,
    "ema_slow": 200,
    "adx_period": 14,
    "adx_threshold": 25,
    "hh_hl_lookback": 20,
    "volume_sma_period": 20,
    "volume_increase_ratio": 1.2,
    "atr_period": 14,
    "min_atr_pct": 0.5,
    "max_distance_from_ema200_pct": 15.0,
}


class TrendDetector:
    """Aggregate trend detector that fuses several indicator patterns
    into a single market-regime classification.

    Parameters
    ----------
    config : dict
        Configuration dictionary -- typically the ``trend_detection``
        section of ``settings.yaml``.  Missing keys are filled from
        built-in defaults.
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = dict(_DEFAULTS)
        if config:
            cfg.update(config)

        self.ema_fast: int = int(cfg["ema_fast"])
        self.ema_slow: int = int(cfg["ema_slow"])
        self.adx_period: int = int(cfg["adx_period"])
        self.adx_threshold: float = float(cfg["adx_threshold"])
        self.hh_hl_lookback: int = int(cfg["hh_hl_lookback"])
        self.volume_sma_period: int = int(cfg["volume_sma_period"])
        self.volume_increase_ratio: float = float(cfg["volume_increase_ratio"])
        self.atr_period: int = int(cfg["atr_period"])
        self.min_atr_pct: float = float(cfg["min_atr_pct"])
        self.max_distance_from_ema200_pct: float = float(
            cfg["max_distance_from_ema200_pct"]
        )

        logger.info(
            "TrendDetector initialised: ema_fast={}, ema_slow={}, adx_threshold={}",
            self.ema_fast,
            self.ema_slow,
            self.adx_threshold,
        )

    # ------------------------------------------------------------------
    # Individual uptrend detectors
    # ------------------------------------------------------------------

    def detect_uptrend_ema(self, df: pd.DataFrame) -> pd.Series:
        """EMA-based uptrend: price above slow EMA **and** fast EMA > slow EMA.

        Returns a boolean Series aligned with *df*.
        """
        ema_fast = calc_ema(df, column="close", period=self.ema_fast)
        ema_slow = calc_ema(df, column="close", period=self.ema_slow)

        signal = (df["close"] > ema_slow) & (ema_fast > ema_slow)
        logger.debug("EMA uptrend: {} / {} bars", signal.sum(), len(df))
        return signal

    def detect_uptrend_adx(self, df: pd.DataFrame) -> pd.Series:
        """ADX-based uptrend: ADX above threshold **and** +DI > -DI.

        Returns a boolean Series.
        """
        adx_df = calc_adx(df, period=self.adx_period)

        signal = (adx_df["ADX"] > self.adx_threshold) & (
            adx_df["+DI"] > adx_df["-DI"]
        )
        logger.debug("ADX uptrend: {} / {} bars", signal.sum(), len(df))
        return signal

    def detect_uptrend_structure(self, df: pd.DataFrame) -> pd.Series:
        """Market-structure uptrend: higher highs **and** higher lows.

        Returns a boolean Series.
        """
        hh_hl = calc_higher_highs_higher_lows(df, lookback=self.hh_hl_lookback)

        signal = hh_hl["hh"] & hh_hl["hl"]
        logger.debug("Structure uptrend: {} / {} bars", signal.sum(), len(df))
        return signal

    def detect_uptrend_volume(self, df: pd.DataFrame) -> pd.Series:
        """Volume-confirmed uptrend: volume above its SMA (scaled by
        ``volume_increase_ratio``) while price is rising over the
        look-back window.

        Returns a boolean Series.
        """
        vol_sma = calc_volume_sma(df, period=self.volume_sma_period)
        vol_threshold = vol_sma * self.volume_increase_ratio

        price_rising = df["close"] > df["close"].shift(self.volume_sma_period)
        volume_strong = df["volume"] > vol_threshold

        signal = price_rising & volume_strong
        logger.debug("Volume uptrend: {} / {} bars", signal.sum(), len(df))
        return signal

    # ------------------------------------------------------------------
    # Composite uptrend
    # ------------------------------------------------------------------

    def detect_uptrend_composite(self, df: pd.DataFrame) -> pd.Series:
        """Composite uptrend: at least 3 of the 4 individual detectors
        must agree for the bar to be classified as an uptrend.

        Returns a boolean Series.
        """
        ema_sig = self.detect_uptrend_ema(df).astype(int)
        adx_sig = self.detect_uptrend_adx(df).astype(int)
        struct_sig = self.detect_uptrend_structure(df).astype(int)
        vol_sig = self.detect_uptrend_volume(df).astype(int)

        agreement = ema_sig + adx_sig + struct_sig + vol_sig
        signal = agreement >= 3

        logger.info(
            "Composite uptrend: {} / {} bars (>=3 of 4 agree)",
            signal.sum(),
            len(df),
        )
        return signal

    # ------------------------------------------------------------------
    # Regime classification
    # ------------------------------------------------------------------

    def classify_regime(self, df: pd.DataFrame) -> pd.Series:
        """Classify each bar as ``'bull'``, ``'bear'``, or ``'sideways'``.

        Logic:
        * **bull** -- composite uptrend is True.
        * **bear** -- price below slow EMA, fast EMA below slow EMA,
          and ADX shows a directional move with -DI > +DI.
        * **sideways** -- everything else (low ADX, mixed signals).

        Returns a string Series.
        """
        bull = self.detect_uptrend_composite(df)

        # Bear detection
        ema_fast = calc_ema(df, column="close", period=self.ema_fast)
        ema_slow = calc_ema(df, column="close", period=self.ema_slow)
        adx_df = calc_adx(df, period=self.adx_period)

        bear = (
            (df["close"] < ema_slow)
            & (ema_fast < ema_slow)
            & (adx_df["ADX"] > self.adx_threshold)
            & (adx_df["-DI"] > adx_df["+DI"])
        )

        regime = pd.Series("sideways", index=df.index)
        regime[bull] = "bull"
        regime[bear & ~bull] = "bear"

        counts = regime.value_counts()
        logger.info("Regime classification: {}", counts.to_dict())
        return regime

    # ------------------------------------------------------------------
    # Risk / filter helpers
    # ------------------------------------------------------------------

    def is_overextended(self, df: pd.DataFrame) -> pd.Series:
        """Anti-FOMO filter: True when close is more than
        ``max_distance_from_ema200_pct`` percent above the slow EMA.

        Returns a boolean Series.
        """
        ema_slow = calc_ema(df, column="close", period=self.ema_slow)
        distance_pct = ((df["close"] - ema_slow) / ema_slow) * 100.0

        signal = distance_pct > self.max_distance_from_ema200_pct
        logger.debug(
            "Overextended bars: {} / {} (>{:.1f}%)",
            signal.sum(),
            len(df),
            self.max_distance_from_ema200_pct,
        )
        return signal

    def get_trend_strength(self, df: pd.DataFrame) -> pd.Series:
        """Compute a normalised trend-strength score in [0, 1].

        The score is the average of four component scores:

        1. **EMA alignment** -- how far the fast EMA is above the slow
           EMA, capped and scaled.
        2. **ADX strength** -- ADX / 100, clipped to [0, 1].
        3. **Structure** -- 1 when HH+HL, 0.5 for one, 0 for neither.
        4. **Volume conviction** -- current volume / (SMA * ratio),
           clipped to [0, 1].

        Returns a float Series in [0, 1].
        """
        # 1. EMA alignment score
        ema_fast = calc_ema(df, column="close", period=self.ema_fast)
        ema_slow = calc_ema(df, column="close", period=self.ema_slow)
        ema_spread_pct = ((ema_fast - ema_slow) / ema_slow) * 100.0
        # Cap at max_distance_from_ema200_pct and normalise
        ema_score = (ema_spread_pct / self.max_distance_from_ema200_pct).clip(0.0, 1.0)

        # 2. ADX score
        adx_df = calc_adx(df, period=self.adx_period)
        # Only count bullish direction; bearish ADX contributes 0
        directional_mask = (adx_df["+DI"] > adx_df["-DI"]).astype(float)
        adx_score = (adx_df["ADX"] / 100.0).clip(0.0, 1.0) * directional_mask

        # 3. Structure score
        hh_hl = calc_higher_highs_higher_lows(df, lookback=self.hh_hl_lookback)
        struct_score = (hh_hl["hh"].astype(float) + hh_hl["hl"].astype(float)) / 2.0

        # 4. Volume conviction score
        vol_sma = calc_volume_sma(df, period=self.volume_sma_period)
        vol_threshold = vol_sma * self.volume_increase_ratio
        vol_score = (df["volume"] / vol_threshold).clip(0.0, 1.0)
        vol_score = vol_score.replace([np.inf, -np.inf], np.nan).fillna(0.0)

        strength = (ema_score + adx_score + struct_score + vol_score) / 4.0
        strength = strength.clip(0.0, 1.0)

        logger.debug(
            "Trend strength -- mean={:.3f}, max={:.3f}",
            strength.mean(),
            strength.max(),
        )
        return strength
