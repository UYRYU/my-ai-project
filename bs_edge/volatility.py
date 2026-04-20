"""Realised volatility estimators, annualised to match BS sigma.

All inputs are a DataFrame of 1-minute OHLCV bars with columns at least
``open, high, low, close`` indexed by UTC timestamp. ``window_min`` is the
lookback in minutes; ``minutes_per_year`` controls annualisation (defaults
to a 365d calendar to match crypto's 24/7 schedule).

We intentionally expose several estimators because the mispricing signal
varies dramatically with the vol estimate. Walk-forward should sweep them.
"""

from __future__ import annotations

import logging
import math
from typing import Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_MINUTES_PER_YEAR = 365 * 24 * 60


# ---------------------------------------------------------------------------
# Individual estimators. All return an *annualised* sigma (float).
# ---------------------------------------------------------------------------


def close_to_close(
    bars: pd.DataFrame, window_min: int, minutes_per_year: int = DEFAULT_MINUTES_PER_YEAR
) -> float:
    """Classic sample-stdev of log returns, annualised."""
    closes = _tail_closes(bars, window_min)
    if len(closes) < 3:
        raise ValueError("not enough bars for close_to_close")
    log_ret = np.diff(np.log(closes.to_numpy()))
    # ddof=1: sample stdev; the reduced bias matters on short windows.
    return float(log_ret.std(ddof=1) * math.sqrt(minutes_per_year))


def parkinson(
    bars: pd.DataFrame, window_min: int, minutes_per_year: int = DEFAULT_MINUTES_PER_YEAR
) -> float:
    """Parkinson (1980) high-low estimator. ~5x more efficient than C2C."""
    sub = _tail_window(bars, window_min)
    if len(sub) < 2:
        raise ValueError("not enough bars for parkinson")
    hl = np.log(sub["high"].to_numpy() / sub["low"].to_numpy())
    factor = 1.0 / (4.0 * math.log(2.0))
    var_per_bar = factor * np.mean(hl * hl)
    return float(math.sqrt(var_per_bar * minutes_per_year))


def garman_klass(
    bars: pd.DataFrame, window_min: int, minutes_per_year: int = DEFAULT_MINUTES_PER_YEAR
) -> float:
    """Garman-Klass estimator using OHLC. Assumes no drift and no jumps."""
    sub = _tail_window(bars, window_min)
    if len(sub) < 2:
        raise ValueError("not enough bars for garman_klass")
    hl = np.log(sub["high"].to_numpy() / sub["low"].to_numpy())
    co = np.log(sub["close"].to_numpy() / sub["open"].to_numpy())
    var_per_bar = np.mean(0.5 * hl * hl - (2.0 * math.log(2.0) - 1.0) * co * co)
    var_per_bar = max(var_per_bar, 0.0)
    return float(math.sqrt(var_per_bar * minutes_per_year))


def yang_zhang(
    bars: pd.DataFrame, window_min: int, minutes_per_year: int = DEFAULT_MINUTES_PER_YEAR
) -> float:
    """Yang-Zhang estimator. Drift-independent, handles overnight gaps.

    For 24/7 crypto the "overnight" gap is effectively 0, but the
    estimator still works and is the most efficient single estimator when
    data quality is decent.
    """
    sub = _tail_window(bars, window_min)
    n = len(sub)
    if n < 3:
        raise ValueError("not enough bars for yang_zhang")
    o = np.log(sub["open"].to_numpy())
    h = np.log(sub["high"].to_numpy())
    l = np.log(sub["low"].to_numpy())  # noqa: E741 (readability: matches paper)
    c = np.log(sub["close"].to_numpy())
    prev_c = np.roll(c, 1)
    overnight = (o - prev_c)[1:]
    open_to_close = (c - o)[1:]
    rs_term = ((h - c) * (h - o) + (l - c) * (l - o))[1:]

    sigma_o2 = overnight.var(ddof=1)
    sigma_c2 = open_to_close.var(ddof=1)
    sigma_rs2 = rs_term.mean()

    k = 0.34 / (1.34 + (n + 1.0) / (n - 1.0))
    var_per_bar = sigma_o2 + k * sigma_c2 + (1.0 - k) * sigma_rs2
    var_per_bar = max(var_per_bar, 0.0)
    return float(math.sqrt(var_per_bar * minutes_per_year))


def ewma(
    bars: pd.DataFrame,
    window_min: int,
    minutes_per_year: int = DEFAULT_MINUTES_PER_YEAR,
    lam: float = 0.94,
) -> float:
    """RiskMetrics-style EWMA of squared log returns.

    ``window_min`` bounds the lookback; the decay ``lam`` drives the
    effective sample size. Lambda 0.94 is the classic daily-data value;
    for minute data a higher value (0.97--0.99) is common -- expose it
    via config.
    """
    closes = _tail_closes(bars, window_min)
    if len(closes) < 3:
        raise ValueError("not enough bars for ewma")
    log_ret = np.diff(np.log(closes.to_numpy()))
    # Recursive update: var_t = lam * var_{t-1} + (1-lam) * r_t^2
    var = log_ret[0] ** 2
    for r in log_ret[1:]:
        var = lam * var + (1.0 - lam) * r * r
    return float(math.sqrt(var * minutes_per_year))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


ESTIMATORS: dict[str, Callable[..., float]] = {
    "close_to_close": close_to_close,
    "parkinson": parkinson,
    "garman_klass": garman_klass,
    "yang_zhang": yang_zhang,
    "ewma": ewma,
}


def estimate_sigma(
    bars: pd.DataFrame,
    window_min: int,
    estimator: str = "close_to_close",
    minutes_per_year: int = DEFAULT_MINUTES_PER_YEAR,
    sigma_floor: float = 0.0,
    **kwargs,
) -> float:
    """Public entry point used by the backtester and scanner."""
    if estimator not in ESTIMATORS:
        raise ValueError(f"unknown estimator {estimator!r}; valid: {list(ESTIMATORS)}")
    fn = ESTIMATORS[estimator]
    sigma = fn(bars, window_min=window_min, minutes_per_year=minutes_per_year, **kwargs)
    if not math.isfinite(sigma):
        raise ValueError(f"estimator {estimator} produced non-finite sigma")
    return max(sigma, sigma_floor)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tail_window(bars: pd.DataFrame, window_min: int) -> pd.DataFrame:
    if window_min <= 0:
        raise ValueError("window_min must be > 0")
    if bars.empty:
        raise ValueError("empty bars")
    return bars.iloc[-window_min:]


def _tail_closes(bars: pd.DataFrame, window_min: int) -> pd.Series:
    return _tail_window(bars, window_min)["close"]
