"""Evaluation metrics for Polymarket digital-edge backtests.

All functions accept a DataFrame of trades as produced by
``backtest.BacktestResult.to_frame`` or an equivalent schema.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd


@dataclass
class Summary:
    n_trades: int
    win_rate: float
    avg_edge: float
    total_pnl: float
    avg_pnl: float
    profit_factor: float
    sharpe: float
    max_drawdown: float
    brier: float
    calibration_mae: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def summarise(trades: pd.DataFrame) -> Summary:
    if trades.empty:
        return Summary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    pnl = trades["pnl"].to_numpy(dtype="float64")
    wins = (pnl > 0).sum()
    n = len(pnl)
    avg = pnl.mean()
    total = pnl.sum()
    std = pnl.std(ddof=1) if n > 1 else 0.0
    sharpe = 0.0 if std == 0 else (avg / std) * math.sqrt(n)
    pos = pnl[pnl > 0].sum()
    neg = -pnl[pnl < 0].sum()
    pf = pos / neg if neg > 0 else math.inf if pos > 0 else 0.0
    equity = np.cumsum(pnl)
    peak = np.maximum.accumulate(equity)
    mdd = float((equity - peak).min()) if len(equity) else 0.0
    return Summary(
        n_trades=int(n),
        win_rate=float(wins / n),
        avg_edge=float(trades["entry_edge"].mean()),
        total_pnl=float(total),
        avg_pnl=float(avg),
        profit_factor=float(pf),
        sharpe=float(sharpe),
        max_drawdown=float(mdd),
        brier=brier_score(trades),
        calibration_mae=calibration_mae(trades),
    )


def brier_score(trades: pd.DataFrame) -> float:
    """Brier score on the model's probability vs. realised outcome.

    Uses ``entry_model_price`` for the chosen side and ``settle_price``
    (1.0 if side won). Lower is better; 0.25 is a coin-flip baseline.
    """
    if trades.empty:
        return 0.0
    p = trades["entry_model_price"].to_numpy(dtype="float64")
    y = trades["settle_price"].to_numpy(dtype="float64")
    return float(np.mean((p - y) ** 2))


def calibration_mae(trades: pd.DataFrame, bins: int = 10) -> float:
    """Mean absolute calibration error across probability bins."""
    if trades.empty:
        return 0.0
    p = trades["entry_model_price"].to_numpy(dtype="float64")
    y = trades["settle_price"].to_numpy(dtype="float64")
    edges = np.linspace(0.0, 1.0, bins + 1)
    errs = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < hi) if hi < 1.0 else (p >= lo) & (p <= hi)
        if mask.sum() == 0:
            continue
        errs.append(abs(p[mask].mean() - y[mask].mean()))
    return float(np.mean(errs)) if errs else 0.0


def equity_curve(trades: pd.DataFrame) -> pd.Series:
    if trades.empty:
        return pd.Series(dtype="float64")
    ordered = trades.sort_values("entry_ts")
    idx = pd.to_datetime(ordered["entry_ts"], unit="s", utc=True)
    return pd.Series(ordered["pnl"].cumsum().to_numpy(), index=idx, name="equity")
