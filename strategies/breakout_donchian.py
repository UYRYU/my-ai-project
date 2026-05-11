"""Donchian Channel breakout strategy with ATR trailing stop.

Entry (long):
    close[i] > max(high) of the previous `entry_lookback` bars
    (Donchian channel high, prior bars only — does *not* include bar i)
    AND  ATR(period) >= rolling-mean(ATR, atr_lookback) * atr_filter_mult
        (where the rolling mean is taken over the *prior* atr_lookback
         bars to keep the filter bias-free)

Entry (short): symmetric on the Donchian channel low.

Exit (whichever triggers first on a holding bar):
    1. Effective stop:
         - Long  : max(initial_sl, peak  - entry_atr * trail_mult)
                   where peak    is the high-water-mark of the held trade
                   *as of the previous bar's close*.
         - Short : min(initial_sl, trough + entry_atr * trail_mult)
       Intrabar trigger uses the current bar's low (long) or high (short).
    2. Opposite-direction breakout at this bar's close → close at next bar's open.

Position is single, non-flipping (opposite breakout only closes — no
immediate re-entry in the opposite direction).

Execution model:
    Signals computed at bar i's close → executed at bar (i+1)'s open
    (no same-bar look-ahead). Intrabar stop hits use the holding bar's
    high/low. The trailing watermark used at bar i is the watermark
    computed up through bar (i-1) — so the stop level does NOT depend
    on the current bar's high/low (avoids the classic trailing-stop
    look-ahead bug). Watermark is updated *after* the stop check.
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
    "entry_lookback": 20,
    "atr_period": 14,
    "atr_lookback": 50,
    "atr_filter_mult": 0.8,
    "trail_mult": 3.0,
    "initial_sl_mult": 2.0,
}

OPT_GRID = {
    "entry_lookback": [10, 20, 30],
    "trail_mult": [2.0, 3.0, 4.0],
    "initial_sl_mult": [1.5, 2.0, 2.5],
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

    # ---- skill contract ----------------------------------------------------

    def set_params(self, params: dict) -> None:
        self.params = dict(params or {})

    def optimize(self, is_period: str, capital: float) -> dict:
        best: dict | None = None
        best_score = -math.inf
        for combo in _grid_combos(OPT_GRID):
            full = {**DEFAULTS, **combo}
            trades, equity = self._simulate(is_period, capital, full)
            score = self._sharpe(trades, equity, is_period)
            # Penalise tiny samples so a 5-trade window can't win on noise.
            score -= 0.005 * max(0, 100 - len(trades))
            if score > best_score:
                best_score = score
                best = dict(combo)
        if best is None:
            best = {k: v[len(v) // 2] for k, v in OPT_GRID.items()}
        return best

    def backtest(self, period: str, capital: float) -> tuple[list[dict], list[float]]:
        params = {**DEFAULTS, **self.params}
        return self._simulate(period, capital, params)

    # ---- internals ---------------------------------------------------------

    def _load(self, period: str) -> pd.DataFrame:
        if self._df_key == period and self._df is not None:
            return self._df
        start, end = period.split(":")
        df = load_ohlcv(self.symbol, self.tf, start, end).reset_index(drop=True)
        self._df = df
        self._df_key = period
        return df

    def _simulate(self, period: str, capital: float,
                  params: dict) -> tuple[list[dict], list[float]]:
        df = self._load(period)
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # Donchian channel, prior N bars only (shift(1) avoids look-ahead).
        donch_high = high.rolling(window=params["entry_lookback"]).max().shift(1)
        donch_low = low.rolling(window=params["entry_lookback"]).min().shift(1)

        atr = _wilder_atr(high, low, close, params["atr_period"])
        atr_baseline = atr.rolling(window=params["atr_lookback"]).mean().shift(1)
        atr_filter = (atr >= atr_baseline * params["atr_filter_mult"]) & atr_baseline.notna()

        long_break = (close > donch_high).fillna(False)
        short_break = (close < donch_low).fillna(False)

        # Convert all per-bar series to native Python lists for speed inside
        # the state-machine loop (numpy scalar indexing is significantly
        # slower than list indexing in pure-Python hot loops).
        open_a = df["open"].to_numpy().tolist()
        high_a = high.to_numpy().tolist()
        low_a = low.to_numpy().tolist()
        close_a = close.to_numpy().tolist()
        atr_a = atr.to_numpy().tolist()
        long_b = long_break.to_numpy().tolist()
        short_b = short_break.to_numpy().tolist()
        filt = atr_filter.to_numpy().tolist()
        times = df["time"].to_numpy()
        n = len(df)

        warmup = max(params["entry_lookback"],
                     params["atr_period"] + params["atr_lookback"]) + 2
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
        watermark = 0.0   # peak for long, trough for short
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

            # 3. While in position, derive effective stop from the *prior*
            #    watermark (does not include this bar's high/low), then
            #    check intrabar trigger using this bar's high/low.
            if in_pos:
                trail = watermark - direction * entry_atr * params["trail_mult"]
                if direction > 0:
                    effective_stop = initial_sl if initial_sl > trail else trail
                    if low_a[i] <= effective_stop:
                        record_exit(effective_stop, times[i])
                else:
                    effective_stop = initial_sl if initial_sl < trail else trail
                    if high_a[i] >= effective_stop:
                        record_exit(effective_stop, times[i])

                # If still in pos, update the watermark *after* the stop check.
                if in_pos:
                    if direction > 0:
                        if high_a[i] > watermark:
                            watermark = high_a[i]
                    else:
                        if low_a[i] < watermark:
                            watermark = low_a[i]

            # 4. End-of-bar signal generation.
            if in_pos:
                if direction > 0 and short_b[i]:
                    pending_close = True
                elif direction < 0 and long_b[i]:
                    pending_close = True
            else:
                if pending_dir == 0 and filt[i]:
                    if long_b[i]:
                        pending_dir = 1
                        pending_atr = atr_a[i]
                    elif short_b[i]:
                        pending_dir = -1
                        pending_atr = atr_a[i]

        # Force-close any open position at the last bar's close.
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
