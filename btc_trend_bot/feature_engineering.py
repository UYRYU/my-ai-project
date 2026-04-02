"""
Feature engineering module for the BTC Trend Long Bot.

Central place that computes and attaches all technical indicators
to an OHLCV DataFrame, preparing it for downstream strategies.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from btc_trend_bot.indicators.trend import (
    calc_adx,
    calc_atr,
    calc_bollinger_bands,
    calc_ema,
    calc_higher_highs_higher_lows,
    calc_keltner_channels,
    calc_rsi,
    calc_sma,
    calc_volume_sma,
    calc_vwap,
    detect_squeeze,
)
from btc_trend_bot.indicators.trend_detector import TrendDetector

# ---------------------------------------------------------------------------
# Default feature-engineering configuration
# ---------------------------------------------------------------------------
_DEFAULTS: dict = {
    "ema_periods": [20, 50, 200],
    "sma_periods": [20, 50],
    "rsi_period": 14,
    "adx_period": 14,
    "atr_period": 14,
    "bb_period": 20,
    "bb_std": 2.0,
    "kc_period": 20,
    "kc_mult": 1.5,
    "volume_sma_period": 20,
    "hh_hl_lookback": 20,
}


class FeatureEngineer:
    """Compute all technical features required by the trading strategies.

    Parameters
    ----------
    config : dict
        Optional overrides for indicator parameters.  Missing keys are
        filled from built-in defaults.
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = dict(_DEFAULTS)
        if config:
            cfg.update(config)

        self.ema_periods: list[int] = [int(p) for p in cfg["ema_periods"]]
        self.sma_periods: list[int] = [int(p) for p in cfg["sma_periods"]]
        self.rsi_period: int = int(cfg["rsi_period"])
        self.adx_period: int = int(cfg["adx_period"])
        self.atr_period: int = int(cfg["atr_period"])
        self.bb_period: int = int(cfg["bb_period"])
        self.bb_std: float = float(cfg["bb_std"])
        self.kc_period: int = int(cfg["kc_period"])
        self.kc_mult: float = float(cfg["kc_mult"])
        self.volume_sma_period: int = int(cfg["volume_sma_period"])
        self.hh_hl_lookback: int = int(cfg["hh_hl_lookback"])

        # TrendDetector uses its own config section; forward relevant keys
        td_config: dict = {
            "ema_fast": 50,
            "ema_slow": 200,
            "adx_period": self.adx_period,
            "hh_hl_lookback": self.hh_hl_lookback,
            "volume_sma_period": self.volume_sma_period,
            "atr_period": self.atr_period,
        }
        if config:
            # Allow caller to pass trend_detection sub-dict directly
            td_config.update(config.get("trend_detection", {}))
        self._trend_detector = TrendDetector(td_config)

        logger.info(
            "FeatureEngineer initialised: ema={}, sma={}, rsi={}, adx={}, atr={}",
            self.ema_periods,
            self.sma_periods,
            self.rsi_period,
            self.adx_period,
            self.atr_period,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_all_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all technical indicators needed by strategies.

        The input DataFrame must have OHLCV columns (open, high, low,
        close, volume) and a DatetimeIndex.  The returned DataFrame
        contains all original columns plus newly computed features.

        Features added
        --------------
        - EMA 20, 50, 200
        - SMA 20, 50
        - RSI 14
        - ADX, +DI, -DI (period 14)
        - ATR 14
        - Bollinger Bands (20, 2.0)
        - Keltner Channels (20, 1.5)
        - VWAP
        - Volume SMA 20
        - Higher highs / higher lows (lookback 20)
        - Squeeze detection
        - Trend regime classification (bull / bear / sideways)
        - Trend strength (0-1)
        - Overextended flag

        Returns
        -------
        pd.DataFrame
            Original DataFrame with all new indicator columns appended.
        """
        logger.info("Adding all features to DataFrame with {} rows", len(df))
        df = df.copy()

        # --- Moving averages ---
        df = self._add_emas(df)
        df = self._add_smas(df)

        # --- Oscillators / volatility ---
        df = self._add_rsi(df)
        df = self._add_adx(df)
        df = self._add_atr(df)
        df = self._add_bollinger_bands(df)
        df = self._add_keltner_channels(df)

        # --- Volume ---
        df = self._add_vwap(df)
        df = self._add_volume_sma(df)

        # --- Market structure ---
        df = self._add_higher_highs_higher_lows(df)
        df = self._add_squeeze(df)

        # --- Trend regime & strength ---
        df = self._add_trend_regime(df)
        df = self._add_trend_strength(df)
        df = self._add_overextended(df)

        # --- Shorthand aliases used by strategies ---
        if "rsi_14" in df.columns and "rsi" not in df.columns:
            df["rsi"] = df["rsi_14"]
        if "atr_14" in df.columns and "atr" not in df.columns:
            df["atr"] = df["atr_14"]
        if "volume_sma_20" in df.columns and "volume_sma" not in df.columns:
            df["volume_sma"] = df["volume_sma_20"]
        if "ema_50" in df.columns and "ema50" not in df.columns:
            df["ema50"] = df["ema_50"]
        if "ema_200" in df.columns and "ema200" not in df.columns:
            df["ema200"] = df["ema_200"]
        if "ema_20" in df.columns and "ema20" not in df.columns:
            df["ema20"] = df["ema_20"]

        logger.info(
            "Feature engineering complete: {} columns, {} rows",
            len(df.columns),
            len(df),
        )
        return df

    # ------------------------------------------------------------------
    # Private helpers – each adds columns in-place and returns df
    # ------------------------------------------------------------------

    def _add_emas(self, df: pd.DataFrame) -> pd.DataFrame:
        for period in self.ema_periods:
            col_name = f"ema_{period}"
            df[col_name] = calc_ema(df, column="close", period=period)
            logger.debug("Added column: {}", col_name)
        return df

    def _add_smas(self, df: pd.DataFrame) -> pd.DataFrame:
        for period in self.sma_periods:
            col_name = f"sma_{period}"
            df[col_name] = calc_sma(df, column="close", period=period)
            logger.debug("Added column: {}", col_name)
        return df

    def _add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        df["rsi_14"] = calc_rsi(df, period=self.rsi_period)
        logger.debug("Added column: rsi_14")
        return df

    def _add_adx(self, df: pd.DataFrame) -> pd.DataFrame:
        adx_df = calc_adx(df, period=self.adx_period)
        df["adx"] = adx_df["ADX"]
        df["plus_di"] = adx_df["+DI"]
        df["minus_di"] = adx_df["-DI"]
        logger.debug("Added columns: adx, plus_di, minus_di")
        return df

    def _add_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        df["atr_14"] = calc_atr(df, period=self.atr_period)
        logger.debug("Added column: atr_14")
        return df

    def _add_bollinger_bands(self, df: pd.DataFrame) -> pd.DataFrame:
        bb = calc_bollinger_bands(df, period=self.bb_period, std_dev=self.bb_std)
        df["bb_upper"] = bb["upper"]
        df["bb_middle"] = bb["middle"]
        df["bb_lower"] = bb["lower"]
        logger.debug("Added columns: bb_upper, bb_middle, bb_lower")
        return df

    def _add_keltner_channels(self, df: pd.DataFrame) -> pd.DataFrame:
        kc = calc_keltner_channels(df, period=self.kc_period, mult=self.kc_mult)
        df["kc_upper"] = kc["upper"]
        df["kc_middle"] = kc["middle"]
        df["kc_lower"] = kc["lower"]
        logger.debug("Added columns: kc_upper, kc_middle, kc_lower")
        return df

    def _add_vwap(self, df: pd.DataFrame) -> pd.DataFrame:
        df["vwap"] = calc_vwap(df)
        logger.debug("Added column: vwap")
        return df

    def _add_volume_sma(self, df: pd.DataFrame) -> pd.DataFrame:
        df["volume_sma_20"] = calc_volume_sma(df, period=self.volume_sma_period)
        logger.debug("Added column: volume_sma_20")
        return df

    def _add_higher_highs_higher_lows(self, df: pd.DataFrame) -> pd.DataFrame:
        hh_hl = calc_higher_highs_higher_lows(df, lookback=self.hh_hl_lookback)
        df["higher_highs"] = hh_hl["hh"]
        df["higher_lows"] = hh_hl["hl"]
        logger.debug("Added columns: higher_highs, higher_lows")
        return df

    def _add_squeeze(self, df: pd.DataFrame) -> pd.DataFrame:
        df["squeeze"] = detect_squeeze(
            df,
            bb_period=self.bb_period,
            bb_std=self.bb_std,
            kc_period=self.kc_period,
            kc_mult=self.kc_mult,
        )
        logger.debug("Added column: squeeze")
        return df

    def _add_trend_regime(self, df: pd.DataFrame) -> pd.DataFrame:
        df["trend_regime"] = self._trend_detector.classify_regime(df)
        logger.debug("Added column: trend_regime")
        return df

    def _add_trend_strength(self, df: pd.DataFrame) -> pd.DataFrame:
        df["trend_strength"] = self._trend_detector.get_trend_strength(df)
        logger.debug("Added column: trend_strength")
        return df

    def _add_overextended(self, df: pd.DataFrame) -> pd.DataFrame:
        df["overextended"] = self._trend_detector.is_overextended(df)
        logger.debug("Added column: overextended")
        return df
