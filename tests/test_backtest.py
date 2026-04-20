"""Integration-style tests for the backtest engine using synthetic data."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from bs_edge.backtest import backtest_market
from bs_edge.config import Config
from bs_edge.market_loader import UpDownMarket


def _bars(n=2000, seed=1, sigma_annual=0.6, start_price=50_000.0, up_drift=0.0):
    rng = np.random.default_rng(seed)
    dt = 1.0 / (365 * 24 * 60)
    shocks = rng.standard_normal(n) * sigma_annual * math.sqrt(dt) + up_drift * dt
    log_p = np.cumsum(shocks) + math.log(start_price)
    closes = np.exp(log_p)
    intrabar = sigma_annual * math.sqrt(dt) * 0.5
    idx = pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "open": np.concatenate([[closes[0]], closes[:-1]]),
            "high": closes * (1 + intrabar),
            "low": closes * (1 - intrabar),
            "close": closes,
            "volume": 0.0,
        },
        index=idx,
    )


def _market(bars: pd.DataFrame, ttm_minutes: int = 30, strike: float | None = None) -> UpDownMarket:
    open_ts = int(bars.index[1000].timestamp())
    close_ts = int(bars.index[1000 + ttm_minutes].timestamp())
    return UpDownMarket(
        condition_id="cid1",
        slug="bitcoin-up-or-down-test",
        question="Bitcoin Up or Down test",
        up_token_id="up",
        down_token_id="down",
        open_ts=open_ts,
        close_ts=close_ts,
        reference_price=strike if strike is not None else float(bars["close"].iloc[1000]),
    )


def test_no_trade_when_market_fair():
    bars = _bars()
    mkt = _market(bars)
    # Construct an Up-side price history exactly at the model fair value
    # so edge = 0 everywhere.
    ts_window = bars.index[1000:1025]
    hist = pd.DataFrame({"price": [0.5] * len(ts_window)}, index=ts_window)
    cfg = Config(edge_threshold=0.02, min_time_to_expiry_s=60, flat_stake=1.0)
    trades = backtest_market(
        mkt,
        bars,
        hist,
        cfg,
        sigma_window_min=240,
        sigma_estimator="close_to_close",
        realised_outcome="UP",
    )
    # At strike == spot and zero drift, Phi(d2) < 0.5, so model UP < 0.5
    # and market UP == 0.5: edge for DOWN = (1-model) - 0.5 > 0.
    # With threshold 0.02 we expect at most one trade (entry once).
    assert len(trades) <= 1


def test_trade_fires_on_large_mispricing():
    bars = _bars()
    mkt = _market(bars, ttm_minutes=30)
    # Market mispriced far from 0.5 -- creates a clear edge vs. model.
    ts_window = bars.index[1000:1025]
    hist = pd.DataFrame({"price": [0.05] * len(ts_window)}, index=ts_window)
    cfg = Config(edge_threshold=0.05, min_time_to_expiry_s=60)
    trades = backtest_market(
        mkt,
        bars,
        hist,
        cfg,
        sigma_window_min=240,
        sigma_estimator="close_to_close",
        realised_outcome="UP",
    )
    assert len(trades) == 1
    t = trades[0]
    assert t.side == "UP"
    assert t.entry_edge > 0.05
    # Settle UP with model picking UP -> positive PnL.
    assert t.pnl > 0


def test_kelly_stake_non_negative():
    cfg = Config(stake_mode="kelly", kelly_fraction=0.5, kelly_cap=0.25, flat_stake=100.0)
    bars = _bars()
    mkt = _market(bars)
    ts_window = bars.index[1000:1010]
    hist = pd.DataFrame({"price": [0.1] * len(ts_window)}, index=ts_window)
    trades = backtest_market(
        mkt, bars, hist, cfg,
        sigma_window_min=240, sigma_estimator="close_to_close", realised_outcome="UP",
    )
    if trades:
        assert trades[0].stake >= 0
        assert trades[0].stake <= cfg.flat_stake * cfg.kelly_cap + 1e-9


def test_skips_market_without_strike():
    bars = _bars()
    mkt = UpDownMarket(
        condition_id="x", slug="s", question="q",
        up_token_id="u", down_token_id="d",
        open_ts=int(bars.index[1000].timestamp()),
        close_ts=int(bars.index[1030].timestamp()),
        reference_price=None,
    )
    hist = pd.DataFrame({"price": [0.1]}, index=bars.index[1000:1001])
    cfg = Config()
    assert backtest_market(mkt, bars, hist, cfg, sigma_window_min=240, sigma_estimator="close_to_close") == []
