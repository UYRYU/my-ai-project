"""Donchian breakout with a higher-timeframe (4h) trend filter.

Idea: same Donchian breakout + ATR-trailing engine as a plain breakout, but
only take entries whose direction agrees with the *prior fully-closed*
higher-timeframe trend (slope of EMA on 4h closes). The intent is to skip
breakouts that fire against the broader regime — those are the well-known
"range-bound false breakouts" that bleed equity.

Look-ahead avoidance for the higher timeframe (critical):
    1. Resample 1h → 4h with label='left', closed='left'. Each 4h bar is
       indexed at its OPEN time and covers [t, t+4h). Its close is known
       at time t+4h.
    2. Compute EMA on 4h closes → series indexed at 4h open times. The EMA
       value at index L is fully computable only at L+4h (the bar's close).
    3. Compute slope = ema_4h - ema_4h.shift(slope_lookback).
    4. Apply ONE more `.shift(1)` to the slope so the value at index L is
       the slope as computed from the PREVIOUS 4h bar's close. That earlier
       bar closed at time L, so the value is unambiguously known at any
       1h bar whose timestamp is >= L.
    5. Reindex onto the 1h time grid with method='ffill'. At any 1h bar
       T, the slope used is the one indexed at the largest 4h open <= T —
       i.e. always derived from data closed no later than T.

The resulting 4h slope filter is at most one 4h bar "stale" — strictly
bias-free with a safety margin, never look-ahead.

Other look-ahead avoidance (1h side):
    - Donchian channel: rolling().max()/min() on prior N bars only via .shift(1)
    - ATR baseline:    rolling().mean() on prior N bars only via .shift(1)
    - Signals at 1h bar i's close → trade at bar i+1's open
    - Trailing stop: watermark is updated AFTER each bar's stop check, so
      the stop level on bar i never depends on bar i's own high/low.
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
    "entry_lookback": 30,
    "atr_period": 14,
    "atr_lookback": 50,
    "atr_filter_mult": 0.8,
    "trail_mult": 4.0,
    "initial_sl_mult": 1.5,
    "higher_tf": "4h",
    "higher_tf_ema_period": 50,
    "higher_tf_slope_lookback": 3,
}

OPT_GRID = {
    "entry_lookback": [20, 30, 40],
    "higher_tf_slope_lookback": [2, 3, 5],
    "trail_mult": [3.0, 4.0, 5.0],
}


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _grid_combos(grid: dict) -> list[dict]:
    keys = list(grid.keys())
    return [dict(zip(keys, vals)) for vals in product(*grid.values())]


class Strategy:
    def __init__(self, symbol: str, tf: str, fee: float, slippage: float) -> None:
        self.symbol = symbol
        self.tf = tf
        self.fee = fee
        self.slippage = slippage
        self.params: dict = {}
        self._df: pd.DataFrame | None = None
        self._df_key: str | None = None

    def set_params(self, params: dict) -> None:
        self.params = dict(params or {})

    def optimize(self, is_period: str, capital: float) -> dict:
        best: dict | None = None
        best_score = -math.inf
        for combo in _grid_combos(OPT_GRID):
            full = {**DEFAULTS, **combo}
            trades, equity = self._simulate(is_period, capital, full)
            score = self._sharpe(trades, equity, is_period)
            score -= 0.005 * max(0, 100 - len(trades))  # penalise tiny samples
            if score > best_score:
                best_score = score
                best = dict(combo)
        if best is None:
            best = {k: v[len(v) // 2] for k, v in OPT_GRID.items()}
        return best

    def backtest(self, period: str, capital: float) -> tuple[list[dict], list[float]]:
        return self._simulate(period, capital, {**DEFAULTS, **self.params})

    # ---- internals ---------------------------------------------------------

    def _load(self, period: str) -> pd.DataFrame:
        if self._df_key == period and self._df is not None:
            return self._df
        start, end = period.split(":")
        df = load_ohlcv(self.symbol, self.tf, start, end).reset_index(drop=True)
        self._df = df
        self._df_key = period
        return df

    def _htf_slope_on_1h(self, df_1h: pd.DataFrame, htf: str,
                         ema_period: int, slope_lookback: int) -> np.ndarray:
        """Return a numpy array, same length as df_1h, of the 4h EMA slope
        usable at each 1h bar without look-ahead. NaN where not yet defined.
        """
        df_htf = (
            df_1h.set_index("time")
            .resample(htf, label="left", closed="left")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna()
        )
        ema_htf = df_htf["close"].ewm(span=ema_period, adjust=False).mean()
        slope = ema_htf - ema_htf.shift(slope_lookback)
        # Critical safety shift: ensure slope value indexed at 4h-open L was
        # actually computable from data closed strictly at or before time L.
        slope_safe = slope.shift(1)
        # Forward-fill onto the 1h time grid (largest 4h-open <= 1h timestamp).
        aligned = slope_safe.reindex(df_1h["time"].values, method="ffill")
        return aligned.to_numpy()

    def _simulate(self, period: str, capital: float,
                  params: dict) -> tuple[list[dict], list[float]]:
        df = self._load(period)
        high = df["high"]
        low = df["low"]
        close = df["close"]

        donch_high = high.rolling(params["entry_lookback"]).max().shift(1)
        donch_low = low.rolling(params["entry_lookback"]).min().shift(1)
        atr = _wilder_atr(high, low, close, params["atr_period"])
        atr_base = atr.rolling(params["atr_lookback"]).mean().shift(1)
        atr_pass = (atr >= atr_base * params["atr_filter_mult"]) & atr_base.notna()

        htf_slope = self._htf_slope_on_1h(
            df, params["higher_tf"], params["higher_tf_ema_period"],
            params["higher_tf_slope_lookback"]
        )
        htf_up = htf_slope > 0
        htf_dn = htf_slope < 0

        long_b = ((close > donch_high) & atr_pass).to_numpy() & htf_up
        short_b = ((close < donch_low) & atr_pass).to_numpy() & htf_dn

        # Convert to native lists for the hot loop.
        open_a = df["open"].to_numpy().tolist()
        high_a = high.to_numpy().tolist()
        low_a = low.to_numpy().tolist()
        close_a = close.to_numpy().tolist()
        atr_a = atr.to_numpy().tolist()
        long_l = long_b.tolist()
        short_l = short_b.tolist()
        times = df["time"].to_numpy()
        n = len(df)

        warmup = max(params["entry_lookback"],
                     params["atr_period"] + params["atr_lookback"],
                     # Enough 1h bars to cover an HTF EMA warmup of ~3x span
                     # in 4h-bar units (each 4h = 4 1h bars):
                     params["higher_tf_ema_period"] * 4 * 3
                     + params["higher_tf_slope_lookback"] * 4
                     + 4) + 2
        warmup = min(warmup, max(0, n - 2))

        trades: list[dict] = []
        equity: list[float] = [float(capital)]
        balance = float(capital)
        cost_rate = self.fee + self.slippage

        in_pos = False
        direction = 0
        entry_price = 0.0
        entry_atr = 0.0
        units = 0.0
        initial_sl = 0.0
        watermark = 0.0
        entry_time = None
        entry_idx = -1

        pending_dir = 0
        pending_atr = 0.0
        pending_close = False

        def record_exit(exit_price: float, exit_time) -> None:
            nonlocal in_pos, direction, balance
            gross = (exit_price - entry_price) * direction * units
            costs = (entry_price + exit_price) * units * cost_rate
            pnl = gross - costs
            balance += pnl
            trades.append({
                "entry_time": pd.Timestamp(entry_time).isoformat(),
                "exit_time": pd.Timestamp(exit_time).isoformat(),
                "side": "long" if direction > 0 else "short",
                "entry_price": round(float(entry_price), 4),
                "exit_price": round(float(exit_price), 4),
                "pnl": round(float(pnl), 4),
            })
            equity.append(round(balance, 4))
            in_pos = False
            direction = 0

        for i in range(warmup, n):
            # 1. Execute pending close at this bar's open.
            if pending_close and in_pos:
                record_exit(open_a[i], times[i])
                pending_close = False
            # 2. Execute pending entry at this bar's open.
            if pending_dir != 0 and not in_pos and balance > 0:
                direction = pending_dir
                entry_price = float(open_a[i])
                entry_atr = float(pending_atr)
                units = balance / entry_price
                initial_sl = entry_price - direction * entry_atr * params["initial_sl_mult"]
                watermark = entry_price
                entry_time = times[i]
                entry_idx = i
                in_pos = True
            pending_dir = 0
            pending_atr = 0.0

            # 3. Stop check: derive effective stop from PRIOR watermark, then
            #    update watermark only after the stop check.
            if in_pos:
                trail = watermark - direction * entry_atr * params["trail_mult"]
                if direction > 0:
                    stop = initial_sl if initial_sl > trail else trail
                    if low_a[i] <= stop:
                        record_exit(stop, times[i])
                else:
                    stop = initial_sl if initial_sl < trail else trail
                    if high_a[i] >= stop:
                        record_exit(stop, times[i])
                if in_pos:
                    if direction > 0:
                        if high_a[i] > watermark:
                            watermark = high_a[i]
                    else:
                        if low_a[i] < watermark:
                            watermark = low_a[i]

            # 4. End-of-bar signals. Opposite-breakout exit ignores the HTF
            #    filter (a strong opposite move should still close the trade).
            if in_pos:
                d_hi = donch_high.iat[i]
                d_lo = donch_low.iat[i]
                if direction > 0 and not np.isnan(d_lo) and close_a[i] < d_lo:
                    pending_close = True
                elif direction < 0 and not np.isnan(d_hi) and close_a[i] > d_hi:
                    pending_close = True
            elif pending_dir == 0:
                if long_l[i]:
                    pending_dir = 1
                    pending_atr = atr_a[i]
                elif short_l[i]:
                    pending_dir = -1
                    pending_atr = atr_a[i]

        if in_pos:
            record_exit(float(close_a[-1]), times[-1])

        return trades, equity

    @staticmethod
    def _sharpe(trades: list[dict], equity: list[float], period: str) -> float:
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
