"""
バックテスト本体。

同時ポジションは 1 つのみ (シグナル発生時にポジション保有中ならスキップ)。
1 本のローソク内で TP/SL 両方にヒットした場合は安全側に寄せて損切優先。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

import numpy as np
import pandas as pd

from .strategy import Signal, generate_signals


@dataclass
class Trade:
    side: Literal["long", "short"]
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    stop: float
    take: float
    result: Literal["tp", "sl", "eod"]
    pnl: float        # 価格差分 (通貨単位)
    pnl_r: float      # リスク (|entry-stop|) に対する倍率 = R倍

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entry_time"] = str(self.entry_time)
        d["exit_time"] = str(self.exit_time)
        return d


def _simulate_trade(
    df: pd.DataFrame,
    signal: Signal,
    max_bars: int = 500,
) -> Trade | None:
    """
    1 シグナルを 1 トレードとしてバーを前進させながら決済をシミュレート。
    """
    n = len(df)
    i0 = signal.entry_index
    if i0 >= n:
        return None

    entry_price = signal.entry_price
    stop = signal.stop
    take = signal.take
    entry_time = df.index[i0]

    # エントリー足を含めて max_bars 本まで監視
    end = min(n, i0 + max_bars)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()

    for j in range(i0, end):
        hi = high[j]
        lo = low[j]
        if signal.side == "long":
            hit_sl = lo <= stop
            hit_tp = hi >= take
            if hit_sl and hit_tp:
                exit_price = stop  # 保守的
                result = "sl"
            elif hit_sl:
                exit_price = stop
                result = "sl"
            elif hit_tp:
                exit_price = take
                result = "tp"
            else:
                continue
        else:  # short
            hit_sl = hi >= stop
            hit_tp = lo <= take
            if hit_sl and hit_tp:
                exit_price = stop
                result = "sl"
            elif hit_sl:
                exit_price = stop
                result = "sl"
            elif hit_tp:
                exit_price = take
                result = "tp"
            else:
                continue

        pnl = (exit_price - entry_price) if signal.side == "long" else (entry_price - exit_price)
        risk = abs(entry_price - stop)
        pnl_r = pnl / risk if risk > 0 else 0.0
        return Trade(
            side=signal.side,
            entry_time=entry_time,
            entry_price=entry_price,
            exit_time=df.index[j],
            exit_price=exit_price,
            stop=stop,
            take=take,
            result=result,
            pnl=pnl,
            pnl_r=pnl_r,
        )

    # タイムアウト: 最終足の終値で強制決済
    last = end - 1
    exit_price = float(df["close"].iloc[last])
    pnl = (exit_price - entry_price) if signal.side == "long" else (entry_price - exit_price)
    risk = abs(entry_price - stop)
    pnl_r = pnl / risk if risk > 0 else 0.0
    return Trade(
        side=signal.side,
        entry_time=entry_time,
        entry_price=entry_price,
        exit_time=df.index[last],
        exit_price=exit_price,
        stop=stop,
        take=take,
        result="eod",
        pnl=pnl,
        pnl_r=pnl_r,
    )


def run_backtest(
    df: pd.DataFrame,
    ema_period: int = 10,
    swing_lookback: int = 20,
    max_bars_per_trade: int = 500,
) -> tuple[list[Trade], dict]:
    """
    Parameters
    ----------
    df : DataFrame
        15分足 OHLC (index は Datetime)。列: open/high/low/close。
    """
    signals = generate_signals(df, ema_period=ema_period, swing_lookback=swing_lookback)

    trades: list[Trade] = []
    in_position_until: int = -1  # このインデックスまでポジション保有中
    for sig in signals:
        if sig.entry_index <= in_position_until:
            continue  # ポジション保有中はスキップ
        trade = _simulate_trade(df, sig, max_bars=max_bars_per_trade)
        if trade is None:
            continue
        trades.append(trade)
        # 決済足のインデックスを探す
        exit_idx = df.index.get_loc(trade.exit_time)
        if isinstance(exit_idx, slice):
            exit_idx = exit_idx.stop - 1
        in_position_until = int(exit_idx)

    stats = _summarize(trades)
    return trades, stats


def _summarize(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "total_r": 0.0,
            "avg_r": 0.0,
            "max_dd_r": 0.0,
            "profit_factor": 0.0,
        }
    pnl_r = np.array([t.pnl_r for t in trades])
    wins = int((pnl_r > 0).sum())
    losses = int((pnl_r <= 0).sum())
    total_r = float(pnl_r.sum())
    total_pnl = float(sum(t.pnl for t in trades))

    equity = np.cumsum(pnl_r)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    max_dd = float(dd.max()) if len(dd) > 0 else 0.0

    gross_profit = float(pnl_r[pnl_r > 0].sum())
    gross_loss = float(-pnl_r[pnl_r < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(trades),
        "total_pnl": total_pnl,
        "total_r": total_r,
        "avg_r": float(pnl_r.mean()),
        "max_dd_r": max_dd,
        "profit_factor": profit_factor,
    }
