"""Dual EMA Cross + ATR Filter strategy.

Entry:
  Fast/Slow EMA crossover. Long on fast crossing above slow; short on
  fast crossing below slow. Trade is taken only when ATR(period) >=
  rolling-mean(ATR, lookback) * filter_mult, i.e. when current
  volatility is at least `filter_mult` of its recent baseline. The
  rolling mean is computed over the *prior* `lookback` bars (shift(1))
  to keep the filter bias-free.

Exit:
  Bracket order around the entry price:
    long  : TP = entry + ATR_at_entry * tp_mult
            SL = entry - ATR_at_entry * sl_mult
    short : TP = entry - ATR_at_entry * tp_mult
            SL = entry + ATR_at_entry * sl_mult
  TP/SL is checked intrabar on the position's holding bars. If both
  would hit in the same bar the SL is taken (conservative).
  An opposite-direction cross also force-closes at the next open;
  if the ATR filter passes, a new position is opened in that opposite
  direction in the same step.

Execution model:
  Signal computed at bar i's close, executed at bar (i+1)'s open
  (no same-bar look-ahead). Intrabar exits use bar i+1's high/low.
  Fees and slippage are deducted from both legs.
"""

from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

# Make `data.fetcher` importable regardless of CWD.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.fetcher import load_ohlcv


DEFAULTS = {
    "ema_fast": 20,
    "ema_slow": 50,
    "atr_period": 14,
    "atr_filter_lookback": 50,
    "atr_filter_mult": 0.8,
    "tp_mult": 2.0,
    "sl_mult": 1.5,
}

OPT_GRID = {
    "ema_fast": [10, 20, 30],
    "ema_slow": [40, 50, 60],
    "tp_mult": [1.5, 2.0, 2.5],
}


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


class Strategy:
    def __init__(self, symbol: str, tf: str, fee: float, slippage: float) -> None:
        self.symbol = symbol
        self.tf = tf
        self.fee = fee
        self.slippage = slippage
        self.params: dict = {}
        self._df_cache: pd.DataFrame | None = None
        self._df_cache_key: tuple | None = None

    def set_params(self, params: dict) -> None:
        self.params = dict(params or {})

    def optimize(self, is_period: str, capital: float) -> dict:
        best_params: dict | None = None
        best_score = -math.inf
        for combo in (dict(zip(OPT_GRID.keys(), values))
                      for values in itertools.product(*OPT_GRID.values())):
            if combo["ema_fast"] >= combo["ema_slow"]:
                continue
            params = {**DEFAULTS, **combo}
            trades, equity = self._run(is_period, capital, params)
            score = self._sharpe(trades, equity, is_period)
            # Tie-break: prefer more trades to avoid tiny samples winning by noise.
            score_adj = score - 0.001 * max(0, 100 - len(trades))
            if score_adj > best_score:
                best_score = score_adj
                best_params = params
        if best_params is None:
            best_params = dict(DEFAULTS)
        return {k: best_params[k] for k in OPT_GRID.keys()}

    def backtest(self, period: str, capital: float) -> tuple[list[dict], list[float]]:
        params = {**DEFAULTS, **self.params}
        return self._run(period, capital, params)

    def _load(self, period: str) -> pd.DataFrame:
        start, end = period.split(":")
        key = (self.symbol, self.tf, start, end)
        if self._df_cache_key == key and self._df_cache is not None:
            return self._df_cache
        df = load_ohlcv(self.symbol, self.tf, start, end)
        self._df_cache = df
        self._df_cache_key = key
        return df

    def _run(self, period: str, capital: float,
             params: dict) -> tuple[list[dict], list[float]]:
        df = self._load(period)
        ema_fast = df["close"].ewm(span=params["ema_fast"], adjust=False).mean()
        ema_slow = df["close"].ewm(span=params["ema_slow"], adjust=False).mean()
        atr = _wilder_atr(df["high"], df["low"], df["close"], params["atr_period"])
        atr_ma = atr.rolling(window=params["atr_filter_lookback"]).mean().shift(1)

        diff = (ema_fast - ema_slow).values
        prev_diff = np.concatenate([[np.nan], diff[:-1]])
        cross_up = (prev_diff <= 0) & (diff > 0)
        cross_down = (prev_diff >= 0) & (diff < 0)
        filter_pass = (atr.values >= atr_ma.values * params["atr_filter_mult"]) & np.isfinite(atr_ma.values)

        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        times = df["time"].values
        atr_arr = atr.values
        n = len(df)

        warmup = max(params["ema_slow"] * 3, params["atr_period"] + params["atr_filter_lookback"] + 1)
        warmup = min(warmup, n - 2)

        trades: list[dict] = []
        equity: list[float] = [float(capital)]
        balance = float(capital)
        cost_rate = self.fee + self.slippage

        in_pos = False
        direction = 0
        entry_price = 0.0
        entry_atr = 0.0
        entry_units = 0.0
        entry_time = None
        tp = 0.0
        sl = 0.0

        pending_close = False
        pending_enter = 0  # +1 long, -1 short, 0 none
        pending_atr = 0.0

        def close_pos(exit_price: float, exit_time) -> None:
            nonlocal in_pos, direction, balance, entry_price, entry_atr, entry_units, entry_time
            gross = (exit_price - entry_price) * direction * entry_units
            costs = (entry_price + exit_price) * entry_units * cost_rate
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
            # 1. Execute pending actions at this bar's open.
            if pending_close and in_pos:
                close_pos(opens[i], times[i])
                pending_close = False
            if pending_enter != 0 and not in_pos and balance > 0:
                direction = pending_enter
                entry_price = float(opens[i])
                entry_atr = float(pending_atr)
                entry_units = balance / entry_price
                entry_time = times[i]
                tp = entry_price + direction * entry_atr * params["tp_mult"]
                sl = entry_price - direction * entry_atr * params["sl_mult"]
                in_pos = True
            pending_enter = 0
            pending_atr = 0.0

            # 2. Intrabar SL/TP check on this bar's high/low.
            if in_pos:
                if direction > 0:
                    sl_hit = lows[i] <= sl
                    tp_hit = highs[i] >= tp
                else:
                    sl_hit = highs[i] >= sl
                    tp_hit = lows[i] <= tp
                if sl_hit and tp_hit:
                    close_pos(sl, times[i])  # conservative: SL first
                elif sl_hit:
                    close_pos(sl, times[i])
                elif tp_hit:
                    close_pos(tp, times[i])

            # 3. End-of-bar signal generation for next bar.
            if cross_up[i]:
                if in_pos and direction < 0:
                    pending_close = True
                if filter_pass[i] and (not in_pos or direction < 0):
                    pending_enter = 1
                    pending_atr = atr_arr[i]
            elif cross_down[i]:
                if in_pos and direction > 0:
                    pending_close = True
                if filter_pass[i] and (not in_pos or direction > 0):
                    pending_enter = -1
                    pending_atr = atr_arr[i]

        # Force-close any open position at the last bar's close.
        if in_pos:
            close_pos(df["close"].iloc[-1], times[-1])

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
        mean_r = sum(rets) / n
        var = sum((r - mean_r) ** 2 for r in rets) / (n - 1)
        std_r = math.sqrt(var)
        if std_r == 0:
            return -math.inf
        start_str, end_str = period.split(":")
        start = pd.Timestamp(start_str)
        end = pd.Timestamp(end_str)
        years = max((end - start).days / 365.25, 1e-9)
        trades_per_year = n / years
        return (mean_r / std_r) * math.sqrt(trades_per_year)
