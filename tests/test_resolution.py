"""Tests for resolver composition."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from bs_edge.market_loader import UpDownMarket
from bs_edge.resolution import (
    BinanceCloseResolver,
    ChainedResolver,
    OutcomeResolver,
    PolymarketNativeResolver,
)


def _bars(n=100, start=50_000.0, final=50_500.0):
    closes = np.linspace(start, final, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0},
        index=idx,
    )


def _market(strike: float, close_ts: int, **kw) -> UpDownMarket:
    return UpDownMarket(
        condition_id="c", market_id="m", event_id="e",
        slug="s", question="q",
        up_token_id="u", down_token_id="d",
        open_ts=close_ts - 3600, close_ts=close_ts,
        reference_price=strike, **kw,
    )


def test_polymarket_resolver_uses_cached_outcome():
    bars = _bars()
    m = _market(
        50_000.0,
        int(bars.index[50].timestamp()),
        resolved=True,
        resolved_outcome="DOWN",
    )
    r = PolymarketNativeResolver(client=None)
    assert r.resolve(m) == "DOWN"


def test_polymarket_resolver_returns_none_without_data():
    m = _market(50_000.0, 1_700_000_000)
    r = PolymarketNativeResolver(client=None)
    assert r.resolve(m) is None


def test_binance_resolver_up():
    bars = _bars(start=50_000.0, final=50_500.0)
    m = _market(50_000.0, int(bars.index[50].timestamp()))
    assert BinanceCloseResolver(bars).resolve(m) == "UP"


def test_binance_resolver_down():
    bars = _bars(start=50_000.0, final=49_500.0)
    m = _market(50_250.0, int(bars.index[50].timestamp()))
    assert BinanceCloseResolver(bars).resolve(m) == "DOWN"


def test_binance_resolver_empty_when_no_strike():
    bars = _bars()
    m = _market(None, int(bars.index[50].timestamp()))  # type: ignore[arg-type]
    assert BinanceCloseResolver(bars).resolve(m) is None


def test_chained_falls_back_on_none():
    bars = _bars()
    m = _market(50_000.0, int(bars.index[50].timestamp()))

    class _Null(OutcomeResolver):
        def resolve(self, market):
            return None

    chained = ChainedResolver([_Null(), BinanceCloseResolver(bars)])
    assert chained.resolve(m) == "UP"


def test_chained_short_circuits():
    bars = _bars(start=50_000.0, final=49_500.0)
    m = _market(
        50_250.0,
        int(bars.index[50].timestamp()),
        resolved=True,
        resolved_outcome="UP",
    )
    # Native says UP; Binance would say DOWN. Native wins because it's first.
    chained = ChainedResolver([PolymarketNativeResolver(None), BinanceCloseResolver(bars)])
    assert chained.resolve(m) == "UP"
