"""Quick smoke tests — invariants the engine must satisfy."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from strategy import Params, atr, backtest, ema, prepare, rsi


def _fake_df(n: int = 1000, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.001, n)
    close = 60_000 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.0005, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.0005, n)))
    open_ = np.r_[close[0], close[:-1]]
    idx = pd.date_range("2025-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        dict(open=open_, high=high, low=low, close=close, volume=1.0), index=idx
    )


def test_indicators_basic():
    df = _fake_df(500)
    e = ema(df["close"], 20)
    assert len(e) == len(df) and not e.isna().all()
    r = rsi(df["close"], 14)
    assert ((r >= 0) & (r <= 100)).all()
    a = atr(df, 14)
    assert (a.dropna() >= 0).all()


def test_more_fees_means_lower_pnl():
    """同じシグナルなら手数料が高いほど純益は悪化するはず."""
    df = _fake_df(2000, seed=7)
    base = dict(ema_fast=9, ema_slow=34, tp_atr_mult=4, sl_atr_mult=1)
    m_low = backtest(df, Params(**base, fee_rt_pct=0.0, slippage_pct=0.0)).metrics()
    m_hi  = backtest(df, Params(**base, fee_rt_pct=0.5, slippage_pct=0.05)).metrics()
    if m_low["n"] > 0 and m_hi["n"] > 0:
        assert m_hi["ret"] <= m_low["ret"] + 1e-6, (m_low, m_hi)


def test_no_position_double_open():
    """同時に複数ポジは取らない (バックテスト中、open_trade は常に <=1)."""
    df = _fake_df(2000, seed=3)
    res = backtest(df, Params())
    # 各取引が時系列で重ならない
    last_exit = pd.Timestamp.min.tz_localize("UTC")
    for t in res.trades:
        assert t.entry_time >= last_exit, (t.entry_time, last_exit)
        assert t.exit_time is not None
        last_exit = t.exit_time


def test_metrics_shape():
    df = _fake_df(1500, seed=9)
    res = backtest(df, Params(ema_fast=9, ema_slow=21))
    m = res.metrics()
    for k in ("n", "pf", "win", "ret", "max_dd", "sharpe"):
        assert k in m


if __name__ == "__main__":
    test_indicators_basic()
    test_more_fees_means_lower_pnl()
    test_no_position_double_open()
    test_metrics_shape()
    print("OK")
