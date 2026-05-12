"""Donchian breakout + 4h-EMA trend filter + ATR volatility regime filter.

This adds an extra "regime gate" on top of the prior Breakout+HTF design:
trade only when current ATR is at least `regime_threshold` times its own
rolling baseline over the previous `regime_lookback` bars. Intent: cut
the long tail of false breakouts that happen during low-volatility chop,
where the strategy's edge has historically been weakest.

Look-ahead avoidance:

  1h side
  ─────────
  * Donchian channels:  high/low.rolling(N).max/min().shift(1)
                          → prior N bars only, never the current bar.
  * ATR baseline filter: atr.rolling(L).mean().shift(1) → prior bars only.
  * Regime baseline:    atr.rolling(R).mean().shift(1) → prior bars only.
                          regime_ratio[i] = atr[i] / regime_baseline[i].
                          atr[i] uses bar i's close (known at i's close),
                          baseline uses bars i-R..i-1. Signal is decided at
                          bar i's close → trade at bar i+1's open. Bias-free.
  * Signals → action:   computed at bar i's close, executed at bar i+1's open.
  * Trailing watermark: stop is derived from the *prior* watermark, then the
                          watermark is updated *after* the stop check on each
                          bar. The stop level never sees the same bar's
                          extremes.

  4h side (higher timeframe filter)
  ─────────────────────────────────
  * Resample 1h→4h with label='left', closed='left'.
  * EMA on 4h closes → slope = ema - ema.shift(slope_lookback).
  * Apply an extra `.shift(1)` to slope so the value at 4h index L is
    derived from the 4h bar that closed at L (i.e. the previous 4h bar's
    close). Then forward-fill onto the 1h grid.
  * Net effect: at any 1h bar T, the 4h slope used is from data that
    closed at or before time T — guaranteed bias-free with a safety lag.
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
    "entry_lookback": 40,
    "atr_period": 14,
    "atr_lookback": 50,
    "atr_filter_mult": 0.8,
    "higher_tf": "4h",
    "higher_tf_ema_period": 50,
    "higher_tf_slope_lookback": 5,
    "trail_mult": 4.0,
    "initial_sl_mult": 1.5,
    # Volatility-regime gate.
    "regime_lookback": 200,
    "regime_threshold": 1.0,
}

OPT_GRID = {
    "regime_lookback": [100, 200, 400],
    "regime_threshold": [0.9, 1.0, 1.2],
    "trail_mult": [3.0, 4.0, 5.0],
}


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([(high - low),
                    (high - prev).abs(),
                    (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _grid(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, vs)) for vs in product(*grid.values())]


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
        for combo in _grid(OPT_GRID):
            full = {**DEFAULTS, **combo}
            trades, equity = self._run(is_period, capital, full)
            score = self._sharpe(trades, equity, is_period)
            score -= 0.005 * max(0, 100 - len(trades))   # discount tiny samples
            if score > best_score:
                best_score = score
                best = dict(combo)
        if best is None:
            best = {k: v[len(v) // 2] for k, v in OPT_GRID.items()}
        return best

    def backtest(self, period: str, capital: float) -> tuple[list[dict], list[float]]:
        return self._run(period, capital, {**DEFAULTS, **self.params})

    # ---------- internals ----------

    def _data(self, period: str) -> pd.DataFrame:
        if self._df_key == period and self._df is not None:
            return self._df
        s, e = period.split(":")
        df = load_ohlcv(self.symbol, self.tf, s, e).reset_index(drop=True)
        self._df = df
        self._df_key = period
        return df

    def _htf_slope_on_1h(self, df: pd.DataFrame, htf: str, ema_period: int,
                         slope_lookback: int) -> np.ndarray:
        htf_df = (df.set_index("time")
                    .resample(htf, label="left", closed="left")
                    .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                    .dropna())
        ema = htf_df["close"].ewm(span=ema_period, adjust=False).mean()
        slope = (ema - ema.shift(slope_lookback)).shift(1)  # extra safety shift
        return slope.reindex(df["time"].values, method="ffill").to_numpy()

    def _run(self, period: str, capital: float,
             params: dict) -> tuple[list[dict], list[float]]:
        df = self._data(period)
        h = df["high"]
        l = df["low"]
        c = df["close"]

        donch_hi = h.rolling(params["entry_lookback"]).max().shift(1)
        donch_lo = l.rolling(params["entry_lookback"]).min().shift(1)

        atr = _wilder_atr(h, l, c, params["atr_period"])
        atr_base = atr.rolling(params["atr_lookback"]).mean().shift(1)
        atr_ok = (atr >= atr_base * params["atr_filter_mult"]) & atr_base.notna()

        regime_base = atr.rolling(params["regime_lookback"]).mean().shift(1)
        regime_ratio = atr / regime_base
        regime_ok = (regime_ratio >= params["regime_threshold"]) & regime_base.notna()

        htf_slope = self._htf_slope_on_1h(df, params["higher_tf"],
                                          params["higher_tf_ema_period"],
                                          params["higher_tf_slope_lookback"])
        htf_up = htf_slope > 0
        htf_dn = htf_slope < 0

        long_sig = ((c > donch_hi) & atr_ok & regime_ok).to_numpy() & htf_up
        short_sig = ((c < donch_lo) & atr_ok & regime_ok).to_numpy() & htf_dn

        opens = df["open"].to_numpy().tolist()
        highs = h.to_numpy().tolist()
        lows = l.to_numpy().tolist()
        closes = c.to_numpy().tolist()
        atr_a = atr.to_numpy().tolist()
        d_hi_a = donch_hi.to_numpy().tolist()
        d_lo_a = donch_lo.to_numpy().tolist()
        long_a = long_sig.tolist()
        short_a = short_sig.tolist()
        times = df["time"].to_numpy()
        n = len(df)

        warmup = max(params["entry_lookback"],
                     params["atr_period"] + params["atr_lookback"],
                     params["atr_period"] + params["regime_lookback"],
                     params["higher_tf_ema_period"] * 4 * 3
                     + params["higher_tf_slope_lookback"] * 4 + 4) + 2
        warmup = min(warmup, max(0, n - 2))

        trades: list[dict] = []
        equity: list[float] = [float(capital)]
        balance = float(capital)
        cost = self.fee + self.slippage

        in_pos = False
        direction = 0
        entry_p = 0.0
        entry_atr = 0.0
        units = 0.0
        initial_sl = 0.0
        wm = 0.0           # watermark — peak (long) or trough (short)
        entry_time = None

        pending_dir = 0
        pending_atr = 0.0
        pending_close = False

        def exit_at(price: float, t) -> None:
            nonlocal in_pos, direction, balance
            gross = (price - entry_p) * direction * units
            fees = (entry_p + price) * units * cost
            pnl = gross - fees
            balance += pnl
            trades.append({
                "entry_time": pd.Timestamp(entry_time).isoformat(),
                "exit_time": pd.Timestamp(t).isoformat(),
                "side": "long" if direction > 0 else "short",
                "entry_price": round(float(entry_p), 4),
                "exit_price": round(float(price), 4),
                "pnl": round(float(pnl), 4),
            })
            equity.append(round(balance, 4))
            in_pos = False
            direction = 0

        for i in range(warmup, n):
            # 1. Execute pending close at this bar's open.
            if pending_close and in_pos:
                exit_at(opens[i], times[i])
                pending_close = False

            # 2. Execute pending entry at this bar's open.
            if pending_dir != 0 and not in_pos and balance > 0:
                direction = pending_dir
                entry_p = float(opens[i])
                entry_atr = float(pending_atr)
                units = balance / entry_p
                initial_sl = entry_p - direction * entry_atr * params["initial_sl_mult"]
                wm = entry_p
                entry_time = times[i]
                in_pos = True
            pending_dir = 0
            pending_atr = 0.0

            # 3. Stop check using PRIOR watermark, then update watermark.
            if in_pos:
                trail = wm - direction * entry_atr * params["trail_mult"]
                if direction > 0:
                    stop = initial_sl if initial_sl > trail else trail
                    if lows[i] <= stop:
                        exit_at(stop, times[i])
                else:
                    stop = initial_sl if initial_sl < trail else trail
                    if highs[i] >= stop:
                        exit_at(stop, times[i])
                if in_pos:
                    if direction > 0:
                        if highs[i] > wm:
                            wm = highs[i]
                    else:
                        if lows[i] < wm:
                            wm = lows[i]

            # 4. End-of-bar signals.
            if in_pos:
                d_hi = d_hi_a[i]
                d_lo = d_lo_a[i]
                # Opposite-breakout close ignores HTF/regime filters.
                if direction > 0 and not (d_lo != d_lo) and closes[i] < d_lo:
                    pending_close = True
                elif direction < 0 and not (d_hi != d_hi) and closes[i] > d_hi:
                    pending_close = True
            elif pending_dir == 0:
                if long_a[i]:
                    pending_dir = 1
                    pending_atr = atr_a[i]
                elif short_a[i]:
                    pending_dir = -1
                    pending_atr = atr_a[i]

        if in_pos:
            exit_at(float(closes[-1]), times[-1])

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
