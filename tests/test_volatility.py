"""Tests for bs_edge.volatility.

Uses a deterministic synthetic GBM path so estimators recover a sigma in
the right ballpark regardless of seed-dependent noise.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from bs_edge.volatility import ESTIMATORS, estimate_sigma


def _synthetic_bars(
    sigma_annual: float = 0.6, n: int = 2000, seed: int = 7, substeps: int = 60
) -> pd.DataFrame:
    """Brownian bars with realistic OHLC: substep a GBM and take max/min."""
    rng = np.random.default_rng(seed)
    dt = 1.0 / (365 * 24 * 60)  # 1 minute in years
    sub_dt = dt / substeps
    opens = np.empty(n)
    highs = np.empty(n)
    lows = np.empty(n)
    closes = np.empty(n)
    log_p = math.log(50_000.0)
    for i in range(n):
        opens[i] = math.exp(log_p)
        shocks = rng.standard_normal(substeps) * sigma_annual * math.sqrt(sub_dt)
        path = np.cumsum(shocks) + log_p
        highs[i] = math.exp(path.max())
        lows[i] = math.exp(path.min())
        log_p = float(path[-1])
        closes[i] = math.exp(log_p)
    idx = pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 0.0},
        index=idx,
    )


@pytest.mark.parametrize("estimator", list(ESTIMATORS.keys()))
def test_estimator_recovers_synthetic_sigma(estimator):
    bars = _synthetic_bars(sigma_annual=0.6, n=2000)
    sigma = estimate_sigma(bars, window_min=1440, estimator=estimator)
    # All estimators should be within 40% of truth on 1440 minutes of data.
    assert 0.6 * 0.6 < sigma < 0.6 * 1.4


def test_rejects_unknown_estimator():
    bars = _synthetic_bars(n=100)
    with pytest.raises(ValueError):
        estimate_sigma(bars, window_min=60, estimator="nope")


def test_sigma_floor_enforced():
    # Constant price -> zero realised vol -> floor kicks in.
    idx = pd.date_range("2025-01-01", periods=200, freq="1min", tz="UTC")
    flat = pd.DataFrame(
        {"open": 50_000.0, "high": 50_000.0, "low": 50_000.0, "close": 50_000.0, "volume": 0.0},
        index=idx,
    )
    sigma = estimate_sigma(flat, window_min=60, estimator="close_to_close", sigma_floor=0.1)
    assert sigma >= 0.1


def test_window_too_small_raises():
    bars = _synthetic_bars(n=10)
    with pytest.raises(ValueError):
        estimate_sigma(bars, window_min=2, estimator="yang_zhang")
