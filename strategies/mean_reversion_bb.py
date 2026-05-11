"""Bollinger Band Mean Reversion strategy.

Idea: enter against extreme moves when price closes outside the Bollinger
Band and RSI confirms the extreme, but only when the long-term EMA(200)
trend is not strongly against the trade (avoid catching falling knives
during a sustained bear, and vice versa for shorts).

Entry (long):
    close < lower band  AND  RSI <= rsi_oversold
    AND  EMA(trend) slope over the past `slope_lookback` bars >= -slope_threshold
        (flat or rising)

Entry (short): symmetric mirror with overbought + non-rising trend.

Exits (whichever fires first, checked intrabar on each holding bar):
    SL         : entry ± ATR_at_entry * sl_mult
    TP         : SMA(bb_period) touch — the mean
    Time stop  : after `time_stop_bars` bars from entry, exit at that bar's close

Signal generation at bar i close → trade executed at bar i+1 open
(no same-bar look-ahead). Intrabar exits use the *holding* bar's
high/low. SL is favoured over TP when both could trigger in the same bar.

Position is single, non-flipping: while a position is open, new entry
signals are ignored. There is no "opposite signal close" — exits are
only the three listed above.
"""

from __future__ import annotations

import math
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.fetcher import load_ohlcv


DEFAULTS = {
    "bb_period": 20,
    "bb_std": 2.0,
    "rsi_period": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "ema_trend_period": 200,
    "ema_slope_threshold": 0.001,
    "slope_lookback": 24,
    "atr_period": 14,
    "sl_mult": 2.0,
    "time_stop_bars": 24,
}

OPT_GRID = {
    "bb_std": [1.8, 2.0, 2.2],
    "rsi_oversold": [25, 30, 35],
    "sl_mult": [1.5, 2.0, 2.5],
}


def _wilder_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.fillna(50.0)  # neutral when no losses yet
    return rsi


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _expand_grid(grid: dict) -> list[dict]:
    keys = list(grid.keys())
    return [dict(zip(keys, vals)) for vals in product(*grid.values())]


class Strategy:
    def __init__(self, symbol: str, tf: str, fee: float, slippage: float) -> None:
        self.symbol = symbol
        self.tf = tf
        self.fee = fee
        self.slippage = slippage
        self.params: dict = {}

        # cached frame for the most recent period
        self._period_cached: str | None = None
        self._df_cached: pd.DataFrame | None = None

    # ---- skill contract ----------------------------------------------------

    def set_params(self, params: dict) -> None:
        self.params = dict(params or {})

    def optimize(self, is_period: str, capital: float) -> dict:
        best_combo: dict | None = None
        best_score = -math.inf
        for combo in _expand_grid(OPT_GRID):
            params = {**DEFAULTS, **combo}
            # Keep RSI thresholds symmetric around 50.
            params["rsi_overbought"] = 100 - params["rsi_oversold"]
            trades, equity = self._simulate(is_period, capital, params)
            score = self._annualised_sharpe(trades, equity, is_period)
            # Penalise tiny samples so noisy 5-trade windows don't win.
            n = len(trades)
            score -= 0.005 * max(0, 100 - n)
            if score > best_score:
                best_score = score
                best_combo = dict(combo)
        if best_combo is None:
            best_combo = {k: v[len(v) // 2] for k, v in OPT_GRID.items()}
        return best_combo

    def backtest(self, period: str, capital: float) -> tuple[list[dict], list[float]]:
        params = {**DEFAULTS, **self.params}
        if "rsi_oversold" in self.params:
            params["rsi_overbought"] = 100 - params["rsi_oversold"]
        return self._simulate(period, capital, params)

    # ---- internals ---------------------------------------------------------

    def _data(self, period: str) -> pd.DataFrame:
        if self._period_cached == period and self._df_cached is not None:
            return self._df_cached
        start, end = period.split(":")
        df = load_ohlcv(self.symbol, self.tf, start, end).reset_index(drop=True)
        self._period_cached = period
        self._df_cached = df
        return df

    def _simulate(self, period: str, capital: float,
                  params: dict) -> tuple[list[dict], list[float]]:
        df = self._data(period)
        close = df["close"]
        high = df["high"]
        low = df["low"]

        sma = close.rolling(window=params["bb_period"]).mean()
        std = close.rolling(window=params["bb_period"]).std(ddof=0)
        upper = sma + params["bb_std"] * std
        lower = sma - params["bb_std"] * std

        rsi = _wilder_rsi(close, params["rsi_period"])
        atr = _wilder_atr(high, low, close, params["atr_period"])

        ema_trend = close.ewm(span=params["ema_trend_period"], adjust=False).mean()
        slope = ema_trend.pct_change(periods=params["slope_lookback"])
        slope_th = params["ema_slope_threshold"]

        long_signal = (
            (close < lower)
            & (rsi <= params["rsi_oversold"])
            & (slope >= -slope_th)
        ).to_numpy()
        short_signal = (
            (close > upper)
            & (rsi >= params["rsi_overbought"])
            & (slope <= slope_th)
        ).to_numpy()

        # Native Python lists are noticeably faster than numpy scalar
        # indexing inside the per-bar position state machine below.
        open_arr = df["open"].to_numpy().tolist()
        high_arr = high.to_numpy().tolist()
        low_arr = low.to_numpy().tolist()
        close_arr = close.to_numpy().tolist()
        sma_arr = sma.to_numpy().tolist()
        atr_arr = atr.to_numpy().tolist()
        long_sig = long_signal.tolist()
        short_sig = short_signal.tolist()
        times = df["time"].to_numpy()
        n = len(df)

        warmup = max(
            params["bb_period"],
            params["rsi_period"],
            params["atr_period"],
            params["ema_trend_period"],
        ) + params["slope_lookback"]
        warmup = min(warmup, max(0, n - 2))

        trades: list[dict] = []
        equity: list[float] = [float(capital)]
        balance = float(capital)
        cost_rate = self.fee + self.slippage

        in_pos = False
        direction = 0
        entry_idx = -1
        entry_price = 0.0
        entry_atr = 0.0
        sl_price = 0.0
        units = 0.0
        entry_time = None

        pending_dir = 0
        pending_atr = 0.0

        for i in range(warmup, n):
            # Step 1: execute pending entry at this bar's open.
            if pending_dir != 0 and not in_pos and balance > 0:
                direction = pending_dir
                entry_price = float(open_arr[i])
                entry_atr = float(pending_atr)
                sl_price = entry_price - direction * entry_atr * params["sl_mult"]
                units = balance / entry_price
                entry_idx = i
                entry_time = times[i]
                in_pos = True
            pending_dir = 0
            pending_atr = 0.0

            # Step 2: while in position, check exits intrabar on bar i.
            if in_pos:
                bars_held = i - entry_idx
                exit_price: float | None = None
                # 2a. SL
                if direction > 0 and low_arr[i] <= sl_price:
                    exit_price = sl_price
                elif direction < 0 and high_arr[i] >= sl_price:
                    exit_price = sl_price
                # 2b. TP: SMA touch (only if SL didn't fire)
                if exit_price is None:
                    target = sma_arr[i]
                    if target == target:  # NaN-fast check (NaN != NaN)
                        if direction > 0 and high_arr[i] >= target >= low_arr[i]:
                            exit_price = target
                        elif direction < 0 and low_arr[i] <= target <= high_arr[i]:
                            exit_price = target
                # 2c. Time stop: bar at-or-past the limit exits at close
                if exit_price is None and bars_held >= params["time_stop_bars"]:
                    exit_price = float(close_arr[i])

                if exit_price is not None:
                    gross = (exit_price - entry_price) * direction * units
                    costs = (entry_price + exit_price) * units * cost_rate
                    pnl = gross - costs
                    balance += pnl
                    trades.append({
                        "entry_time": pd.Timestamp(entry_time).isoformat(),
                        "exit_time": pd.Timestamp(times[i]).isoformat(),
                        "side": "long" if direction > 0 else "short",
                        "entry_price": round(float(entry_price), 4),
                        "exit_price": round(float(exit_price), 4),
                        "pnl": round(float(pnl), 4),
                    })
                    equity.append(round(balance, 4))
                    in_pos = False
                    direction = 0

            # Step 3: signal computed at bar i's close → schedules bar i+1 entry.
            if not in_pos and pending_dir == 0:
                if long_sig[i]:
                    pending_dir = 1
                    pending_atr = atr_arr[i]
                elif short_sig[i]:
                    pending_dir = -1
                    pending_atr = atr_arr[i]

        # Force-close any open position at the last bar's close.
        if in_pos:
            exit_price = float(close_arr[-1])
            gross = (exit_price - entry_price) * direction * units
            costs = (entry_price + exit_price) * units * cost_rate
            pnl = gross - costs
            balance += pnl
            trades.append({
                "entry_time": pd.Timestamp(entry_time).isoformat(),
                "exit_time": pd.Timestamp(times[-1]).isoformat(),
                "side": "long" if direction > 0 else "short",
                "entry_price": round(float(entry_price), 4),
                "exit_price": round(float(exit_price), 4),
                "pnl": round(float(pnl), 4),
            })
            equity.append(round(balance, 4))

        return trades, equity

    @staticmethod
    def _annualised_sharpe(trades: list[dict], equity: list[float], period: str) -> float:
        n = len(trades)
        if n < 2:
            return -math.inf
        rets = []
        for i, t in enumerate(trades):
            base = equity[i] if equity[i] else 1.0
            rets.append(t["pnl"] / base)
        m = sum(rets) / n
        var = sum((r - m) ** 2 for r in rets) / (n - 1)
        sd = math.sqrt(var)
        if sd == 0:
            return -math.inf
        s, e = period.split(":")
        years = max((pd.Timestamp(e) - pd.Timestamp(s)).days / 365.25, 1e-9)
        return (m / sd) * math.sqrt(n / years)
