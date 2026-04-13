"""
複数戦略タイプのシグナル生成器。

EMA リテスト以外に RSI, Bollinger, EMA Cross, Breakout, Mean Reversion, MACD を実装。
全戦略は同じ Signal フォーマットを返し、既存のバックテストエンジンで評価可能。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


Side = Literal["long", "short"]


@dataclass
class Signal:
    index: int
    side: Side
    entry_index: int
    entry_price: float
    stop: float
    take: float


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _bollinger(close: pd.Series, period: int = 20, std_dev: float = 2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line


def _resolve_sl_tp(side, entry_price, h_arr, l_arr, i, swing_lookback, rr_ratio):
    lo = max(0, i - swing_lookback)
    recent_high = float(np.max(h_arr[lo:i+1]))
    recent_low = float(np.min(l_arr[lo:i+1]))
    if side == "long":
        stop = recent_low
        if stop >= entry_price: return None
        risk = entry_price - stop
        take = entry_price + rr_ratio * risk
    else:
        stop = recent_high
        if stop <= entry_price: return None
        risk = stop - entry_price
        take = entry_price - rr_ratio * risk
    return stop, take


# -----------------------------------------------------------------------
# Strategy 1: RSI Reversal
# -----------------------------------------------------------------------
def signals_rsi(df, ema_period=50, rsi_period=14, rsi_low=30, rsi_high=70,
                swing_lookback=20, rr_ratio=2.0):
    df = df.copy()
    c = df["close"]
    rsi = _rsi(c, rsi_period).to_numpy()
    trend_ema = _ema(c, ema_period).to_numpy()
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    cl = c.to_numpy()
    signals = []
    for i in range(ema_period, len(df) - 1):
        if np.isnan(rsi[i]) or np.isnan(trend_ema[i]): continue
        entry_price = float(o[i+1])
        # Long: RSI < rsi_low AND close > EMA (uptrend pullback)
        if rsi[i] < rsi_low and cl[i] > trend_ema[i]:
            res = _resolve_sl_tp("long", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "long", i+1, entry_price, res[0], res[1]))
        # Short: RSI > rsi_high AND close < EMA
        elif rsi[i] > rsi_high and cl[i] < trend_ema[i]:
            res = _resolve_sl_tp("short", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "short", i+1, entry_price, res[0], res[1]))
    return signals


# -----------------------------------------------------------------------
# Strategy 2: Bollinger Band Bounce
# -----------------------------------------------------------------------
def signals_bollinger(df, bb_period=20, bb_std=2.0, ema_period=50,
                       swing_lookback=20, rr_ratio=2.0):
    df = df.copy()
    c = df["close"]
    upper, mid, lower = _bollinger(c, bb_period, bb_std)
    trend_ema = _ema(c, ema_period).to_numpy()
    upper = upper.to_numpy(); lower = lower.to_numpy()
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); cl = c.to_numpy()
    signals = []
    for i in range(max(bb_period, ema_period), len(df) - 1):
        if np.isnan(upper[i]) or np.isnan(trend_ema[i]): continue
        entry_price = float(o[i+1])
        # Long: touched lower band AND uptrend
        if l[i] <= lower[i] and cl[i] > lower[i] and cl[i] > trend_ema[i]:
            res = _resolve_sl_tp("long", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "long", i+1, entry_price, res[0], res[1]))
        # Short: touched upper band AND downtrend
        elif h[i] >= upper[i] and cl[i] < upper[i] and cl[i] < trend_ema[i]:
            res = _resolve_sl_tp("short", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "short", i+1, entry_price, res[0], res[1]))
    return signals


# -----------------------------------------------------------------------
# Strategy 3: EMA Cross
# -----------------------------------------------------------------------
def signals_ema_cross(df, fast_ema=10, slow_ema=50,
                       swing_lookback=20, rr_ratio=2.0):
    df = df.copy()
    c = df["close"]
    fast = _ema(c, fast_ema).to_numpy()
    slow = _ema(c, slow_ema).to_numpy()
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    signals = []
    for i in range(slow_ema + 1, len(df) - 1):
        if np.isnan(fast[i]) or np.isnan(slow[i]): continue
        entry_price = float(o[i+1])
        # Golden cross
        if fast[i-1] <= slow[i-1] and fast[i] > slow[i]:
            res = _resolve_sl_tp("long", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "long", i+1, entry_price, res[0], res[1]))
        # Death cross
        elif fast[i-1] >= slow[i-1] and fast[i] < slow[i]:
            res = _resolve_sl_tp("short", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "short", i+1, entry_price, res[0], res[1]))
    return signals


# -----------------------------------------------------------------------
# Strategy 4: Breakout (N-bar high/low)
# -----------------------------------------------------------------------
def signals_breakout(df, lookback=20, swing_lookback=20, rr_ratio=2.0):
    df = df.copy()
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); c = df["close"].to_numpy()
    signals = []
    for i in range(lookback + 1, len(df) - 1):
        entry_price = float(o[i+1])
        prev_high = float(np.max(h[i-lookback:i]))
        prev_low = float(np.min(l[i-lookback:i]))
        # Breakout up
        if c[i] > prev_high and c[i-1] <= prev_high:
            res = _resolve_sl_tp("long", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "long", i+1, entry_price, res[0], res[1]))
        # Breakout down
        elif c[i] < prev_low and c[i-1] >= prev_low:
            res = _resolve_sl_tp("short", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "short", i+1, entry_price, res[0], res[1]))
    return signals


# -----------------------------------------------------------------------
# Strategy 5: MACD Cross
# -----------------------------------------------------------------------
def signals_macd(df, fast=12, slow=26, signal_period=9, ema_trend=50,
                  swing_lookback=20, rr_ratio=2.0):
    df = df.copy()
    c = df["close"]
    macd_line, signal_line = _macd(c, fast, slow, signal_period)
    trend = _ema(c, ema_trend).to_numpy()
    ml = macd_line.to_numpy(); sl_ = signal_line.to_numpy()
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); cl = c.to_numpy()
    signals = []
    for i in range(max(slow, ema_trend) + 1, len(df) - 1):
        if np.isnan(ml[i]) or np.isnan(trend[i]): continue
        entry_price = float(o[i+1])
        # Bullish MACD cross + uptrend
        if ml[i-1] <= sl_[i-1] and ml[i] > sl_[i] and cl[i] > trend[i]:
            res = _resolve_sl_tp("long", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "long", i+1, entry_price, res[0], res[1]))
        # Bearish MACD cross + downtrend
        elif ml[i-1] >= sl_[i-1] and ml[i] < sl_[i] and cl[i] < trend[i]:
            res = _resolve_sl_tp("short", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "short", i+1, entry_price, res[0], res[1]))
    return signals


# -----------------------------------------------------------------------
# Strategy 6: Mean Reversion (EMA distance)
# -----------------------------------------------------------------------
def signals_mean_reversion(df, ema_period=20, threshold_pct=1.0,
                            swing_lookback=20, rr_ratio=1.0):
    df = df.copy()
    c = df["close"]
    ema_val = _ema(c, ema_period).to_numpy()
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); cl = c.to_numpy()
    signals = []
    for i in range(ema_period, len(df) - 1):
        if np.isnan(ema_val[i]) or ema_val[i] == 0: continue
        dist_pct = (cl[i] - ema_val[i]) / ema_val[i] * 100
        entry_price = float(o[i+1])
        # Oversold: price far below EMA → long (mean reversion)
        if dist_pct < -threshold_pct:
            res = _resolve_sl_tp("long", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "long", i+1, entry_price, res[0], res[1]))
        # Overbought: price far above EMA → short
        elif dist_pct > threshold_pct:
            res = _resolve_sl_tp("short", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "short", i+1, entry_price, res[0], res[1]))
    return signals


# -----------------------------------------------------------------------
# Strategy 7: RSI + Bollinger combo
# -----------------------------------------------------------------------
def signals_rsi_bb(df, rsi_period=14, rsi_low=30, rsi_high=70,
                    bb_period=20, bb_std=2.0,
                    swing_lookback=20, rr_ratio=2.0):
    df = df.copy()
    c = df["close"]
    rsi = _rsi(c, rsi_period).to_numpy()
    upper, mid, lower = _bollinger(c, bb_period, bb_std)
    upper = upper.to_numpy(); lower = lower.to_numpy()
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); cl = c.to_numpy()
    signals = []
    start = max(rsi_period, bb_period)
    for i in range(start, len(df) - 1):
        if np.isnan(rsi[i]) or np.isnan(lower[i]): continue
        entry_price = float(o[i+1])
        # Long: RSI oversold + at lower BB
        if rsi[i] < rsi_low and l[i] <= lower[i]:
            res = _resolve_sl_tp("long", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "long", i+1, entry_price, res[0], res[1]))
        # Short: RSI overbought + at upper BB
        elif rsi[i] > rsi_high and h[i] >= upper[i]:
            res = _resolve_sl_tp("short", entry_price, h, l, i, swing_lookback, rr_ratio)
            if res: signals.append(Signal(i, "short", i+1, entry_price, res[0], res[1]))
    return signals
