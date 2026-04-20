"""Tests for the portfolio backtester."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from bs_edge.config import Config
from bs_edge.market_loader import UpDownMarket
from bs_edge.portfolio import run_portfolio


def _bars(n=4000, seed=3, sigma_annual=0.6, start_price=50_000.0):
    rng = np.random.default_rng(seed)
    dt = 1.0 / (365 * 24 * 60)
    shocks = rng.standard_normal(n) * sigma_annual * math.sqrt(dt)
    closes = np.exp(np.cumsum(shocks) + math.log(start_price))
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


def _make_market(bars, cid, event_id, entry_idx, ttm_minutes=30):
    open_ts = int(bars.index[entry_idx].timestamp())
    close_ts = int(bars.index[entry_idx + ttm_minutes].timestamp())
    return UpDownMarket(
        condition_id=cid, market_id=cid, event_id=event_id,
        slug=f"btc-up-or-down-{cid}", question=f"Bitcoin Up or Down {cid}",
        up_token_id="u", down_token_id="d",
        open_ts=open_ts, close_ts=close_ts,
        reference_price=float(bars["close"].iloc[entry_idx]),
    )


def _mispriced_history(bars, entry_idx, ttm_minutes, price=0.05):
    ts = bars.index[entry_idx : entry_idx + ttm_minutes]
    return pd.DataFrame({"price": [price] * len(ts)}, index=ts)


def test_portfolio_runs_baseline():
    bars = _bars()
    m1 = _make_market(bars, "c1", "ev1", 1000)
    m2 = _make_market(bars, "c2", "ev2", 1100)
    hist = {
        "c1": _mispriced_history(bars, 1000, 30),
        "c2": _mispriced_history(bars, 1100, 30),
    }
    cfg = Config(
        edge_threshold=0.05,
        exit_edge_threshold=None,
        exit_on_sign_flip=False,
        min_time_to_expiry_s=0,
        exit_min_ttm_s=0,
        max_concurrent_positions=5,
        max_notional_exposure=1000.0,
        per_event_notional_cap=500.0,
        daily_loss_limit=-10_000.0,
        flat_stake=10.0,
    )
    result = run_portfolio(
        [m1, m2], bars, hist, cfg,
        sigma_window_min=240, sigma_estimator="close_to_close",
    )
    assert len(result.trades) == 2


def test_concurrency_gate_blocks_second_entry():
    bars = _bars()
    # Two markets that would both fire at the same time; concurrency=1.
    m1 = _make_market(bars, "c1", "ev1", 1000)
    m2 = _make_market(bars, "c2", "ev2", 1000)
    hist = {
        "c1": _mispriced_history(bars, 1000, 30),
        "c2": _mispriced_history(bars, 1000, 30),
    }
    cfg = Config(
        edge_threshold=0.05,
        exit_edge_threshold=None,
        exit_on_sign_flip=False,
        max_concurrent_positions=1,
        max_notional_exposure=10_000.0,
        per_event_notional_cap=10_000.0,
        flat_stake=10.0,
    )
    result = run_portfolio(
        [m1, m2], bars, hist, cfg,
        sigma_window_min=240, sigma_estimator="close_to_close",
    )
    assert len(result.trades) == 1
    assert result.blocked_by_gate.get("concurrency", 0) >= 1


def test_per_event_cap_blocks_second_entry_in_same_event():
    bars = _bars()
    m1 = _make_market(bars, "c1", "ev-shared", 1000)
    m2 = _make_market(bars, "c2", "ev-shared", 1000)
    hist = {
        "c1": _mispriced_history(bars, 1000, 30),
        "c2": _mispriced_history(bars, 1000, 30),
    }
    cfg = Config(
        edge_threshold=0.05,
        exit_edge_threshold=None,
        exit_on_sign_flip=False,
        max_concurrent_positions=10,
        max_notional_exposure=10_000.0,
        per_event_notional_cap=15.0,  # room for one $10 stake, not two
        flat_stake=10.0,
    )
    result = run_portfolio(
        [m1, m2], bars, hist, cfg,
        sigma_window_min=240, sigma_estimator="close_to_close",
    )
    assert len(result.trades) == 1
    assert result.blocked_by_gate.get("per_event_cap", 0) >= 1


def test_notional_exposure_gate():
    bars = _bars()
    m1 = _make_market(bars, "c1", "ev1", 1000)
    m2 = _make_market(bars, "c2", "ev2", 1000)
    hist = {
        "c1": _mispriced_history(bars, 1000, 30),
        "c2": _mispriced_history(bars, 1000, 30),
    }
    cfg = Config(
        edge_threshold=0.05,
        exit_edge_threshold=None,
        exit_on_sign_flip=False,
        max_concurrent_positions=10,
        max_notional_exposure=15.0,
        per_event_notional_cap=10_000.0,
        flat_stake=10.0,
    )
    result = run_portfolio(
        [m1, m2], bars, hist, cfg,
        sigma_window_min=240, sigma_estimator="close_to_close",
    )
    assert len(result.trades) == 1
    assert result.blocked_by_gate.get("notional_exposure", 0) >= 1


def test_daily_loss_limit_halts_new_entries():
    """After realising a loss that exceeds the limit, stop entering.

    Uses a forcing resolver so the first market is guaranteed to settle
    against us, making the test deterministic regardless of the random
    BTC path.
    """
    from bs_edge.resolution import OutcomeResolver

    class _AlwaysLose(OutcomeResolver):
        def resolve(self, market):
            # We buy UP when market shows cheap UP; force DOWN outcome.
            return "DOWN"

    bars = _bars()
    m_loser = _make_market(bars, "loser", "ev_l", 1000, ttm_minutes=30)
    m_blocked = _make_market(bars, "c2", "ev_b", 1100, ttm_minutes=30)

    hist = {
        "loser": _mispriced_history(bars, 1000, 30),
        "c2": _mispriced_history(bars, 1100, 30),
    }

    cfg = Config(
        edge_threshold=0.03,
        exit_edge_threshold=None,
        exit_on_sign_flip=False,
        min_time_to_expiry_s=0,
        exit_min_ttm_s=0,
        max_concurrent_positions=10,
        max_notional_exposure=10_000.0,
        per_event_notional_cap=10_000.0,
        daily_loss_limit=-1.0,
        flat_stake=100.0,
        half_spread=0.01,
    )
    result = run_portfolio(
        [m_loser, m_blocked], bars, hist, cfg,
        sigma_window_min=240, sigma_estimator="close_to_close",
        resolver=_AlwaysLose(),
    )
    assert result.blocked_by_gate.get("daily_loss_limit", 0) >= 1
    assert len(result.trades) == 1
    assert result.trades[0].pnl < 0
