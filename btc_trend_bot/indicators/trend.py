"""
Technical indicator calculation functions for the BTC Trend Long Bot.

All functions accept a pandas DataFrame with OHLCV columns
(open, high, low, close, volume) and return computed indicator values.
Uses only numpy and pandas -- no external TA library dependency.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger


def calc_ema(df: pd.DataFrame, column: str = "close", period: int = 20) -> pd.Series:
    """Calculate Exponential Moving Average.

    Args:
        df: OHLCV DataFrame.
        column: Column name to compute EMA on.
        period: Look-back period.

    Returns:
        Series with EMA values.
    """
    logger.debug("Calculating EMA({}): period={}", column, period)
    return df[column].ewm(span=period, adjust=False).mean()


def calc_sma(df: pd.DataFrame, column: str = "close", period: int = 20) -> pd.Series:
    """Calculate Simple Moving Average.

    Args:
        df: OHLCV DataFrame.
        column: Column name to compute SMA on.
        period: Look-back period.

    Returns:
        Series with SMA values.
    """
    logger.debug("Calculating SMA({}): period={}", column, period)
    return df[column].rolling(window=period).mean()


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculate Average Directional Index with +DI and -DI.

    Uses Wilder's smoothing method.

    Args:
        df: OHLCV DataFrame.
        period: Look-back period.

    Returns:
        DataFrame with columns 'ADX', '+DI', '-DI'.
    """
    logger.debug("Calculating ADX: period={}", period)

    high = df["high"]
    low = df["low"]
    close = df["close"]

    # True Range
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    # Wilder's smoothing (equivalent to EMA with alpha = 1/period)
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=alpha, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=alpha, adjust=False).mean()

    # Directional Indicators
    plus_di = 100.0 * plus_dm_smooth / atr
    minus_di = 100.0 * minus_dm_smooth / atr

    # ADX
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    dx = dx.replace([np.inf, -np.inf], np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    return pd.DataFrame({"ADX": adx, "+DI": plus_di, "-DI": minus_di}, index=df.index)


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range using Wilder's smoothing.

    Args:
        df: OHLCV DataFrame.
        period: Look-back period.

    Returns:
        Series with ATR values.
    """
    logger.debug("Calculating ATR: period={}", period)

    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    alpha = 1.0 / period
    return tr.ewm(alpha=alpha, adjust=False).mean()


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index.

    Uses Wilder's smoothing for average gains/losses.

    Args:
        df: OHLCV DataFrame.
        period: Look-back period.

    Returns:
        Series with RSI values (0-100).
    """
    logger.debug("Calculating RSI: period={}", period)

    delta = df["close"].diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)

    alpha = 1.0 / period
    avg_gain = gains.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = losses.ewm(alpha=alpha, adjust=False).mean()

    rs = avg_gain / avg_loss
    rs = rs.replace([np.inf, -np.inf], np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def calc_bollinger_bands(
    df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
) -> pd.DataFrame:
    """Calculate Bollinger Bands.

    Args:
        df: OHLCV DataFrame.
        period: Look-back period for the middle SMA.
        std_dev: Number of standard deviations for the bands.

    Returns:
        DataFrame with columns 'upper', 'middle', 'lower'.
    """
    logger.debug("Calculating Bollinger Bands: period={}, std_dev={}", period, std_dev)

    middle = df["close"].rolling(window=period).mean()
    rolling_std = df["close"].rolling(window=period).std(ddof=0)
    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std

    return pd.DataFrame(
        {"upper": upper, "middle": middle, "lower": lower}, index=df.index
    )


def calc_keltner_channels(
    df: pd.DataFrame, period: int = 20, mult: float = 1.5
) -> pd.DataFrame:
    """Calculate Keltner Channels.

    Middle line is EMA of close; bands offset by ATR * multiplier.

    Args:
        df: OHLCV DataFrame.
        period: Look-back period.
        mult: ATR multiplier for upper/lower bands.

    Returns:
        DataFrame with columns 'upper', 'middle', 'lower'.
    """
    logger.debug("Calculating Keltner Channels: period={}, mult={}", period, mult)

    middle = calc_ema(df, column="close", period=period)
    atr = calc_atr(df, period=period)
    upper = middle + mult * atr
    lower = middle - mult * atr

    return pd.DataFrame(
        {"upper": upper, "middle": middle, "lower": lower}, index=df.index
    )


def calc_vwap(df: pd.DataFrame) -> pd.Series:
    """Calculate a rolling session VWAP (Volume Weighted Average Price).

    Assumes the DataFrame index is a DatetimeIndex. VWAP resets at
    the start of each calendar day. If the index is not datetime-based
    the calculation runs over the entire frame without resets.

    Args:
        df: OHLCV DataFrame.

    Returns:
        Series with VWAP values.
    """
    logger.debug("Calculating VWAP")

    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_vol = typical_price * df["volume"]

    if isinstance(df.index, pd.DatetimeIndex):
        # Group by calendar date to reset VWAP each session
        date_groups = df.index.date
        cum_tp_vol = tp_vol.groupby(date_groups).cumsum()
        cum_vol = df["volume"].groupby(date_groups).cumsum()
    else:
        cum_tp_vol = tp_vol.cumsum()
        cum_vol = df["volume"].cumsum()

    vwap = cum_tp_vol / cum_vol
    vwap = vwap.replace([np.inf, -np.inf], np.nan)
    return vwap


def calc_volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Calculate Simple Moving Average of volume.

    Args:
        df: OHLCV DataFrame.
        period: Look-back period.

    Returns:
        Series with volume SMA values.
    """
    logger.debug("Calculating Volume SMA: period={}", period)
    return df["volume"].rolling(window=period).mean()


def calc_higher_highs_higher_lows(
    df: pd.DataFrame, lookback: int = 20
) -> pd.DataFrame:
    """Detect higher-highs and higher-lows structure.

    For each bar, compares the rolling max of highs and rolling min of
    lows over the look-back window with the preceding window of the
    same length.

    Args:
        df: OHLCV DataFrame.
        lookback: Window size for structural comparison.

    Returns:
        DataFrame with boolean columns 'hh' (higher highs) and
        'hl' (higher lows).
    """
    logger.debug("Calculating HH/HL: lookback={}", lookback)

    rolling_high = df["high"].rolling(window=lookback).max()
    rolling_low = df["low"].rolling(window=lookback).min()

    prev_rolling_high = rolling_high.shift(lookback)
    prev_rolling_low = rolling_low.shift(lookback)

    hh = rolling_high > prev_rolling_high
    hl = rolling_low > prev_rolling_low

    return pd.DataFrame({"hh": hh, "hl": hl}, index=df.index)


def detect_squeeze(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    kc_period: int = 20,
    kc_mult: float = 1.5,
) -> pd.Series:
    """Detect Bollinger Band squeeze (BB inside Keltner Channel).

    A squeeze occurs when both Bollinger Bands are inside the
    corresponding Keltner Channel bands, indicating low volatility
    that often precedes a breakout.

    Args:
        df: OHLCV DataFrame.
        bb_period: Bollinger Band period.
        bb_std: Bollinger Band standard deviation multiplier.
        kc_period: Keltner Channel period.
        kc_mult: Keltner Channel ATR multiplier.

    Returns:
        Boolean Series -- True where a squeeze is active.
    """
    logger.debug(
        "Detecting squeeze: bb_period={}, bb_std={}, kc_period={}, kc_mult={}",
        bb_period,
        bb_std,
        kc_period,
        kc_mult,
    )

    bb = calc_bollinger_bands(df, period=bb_period, std_dev=bb_std)
    kc = calc_keltner_channels(df, period=kc_period, mult=kc_mult)

    squeeze = (bb["lower"] > kc["lower"]) & (bb["upper"] < kc["upper"])
    return squeeze
