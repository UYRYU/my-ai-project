"""Tests for slippage models."""

from __future__ import annotations

import math

import pytest

from bs_edge.config import Config
from bs_edge.slippage import (
    BookSnapshot,
    BookWalkSlippage,
    ConstantSpread,
    LinearImpact,
    SnapshotStore,
    SqrtImpact,
    build_from_config,
)


def test_constant_spread_symmetric():
    s = ConstantSpread(half_spread=0.02)
    assert abs(s.buy_price(0.5, 100) - 0.52) < 1e-12
    assert abs(s.sell_price(0.5, 100) - 0.48) < 1e-12


def test_constant_spread_clips_to_unit_interval():
    s = ConstantSpread(half_spread=0.2)
    assert s.buy_price(0.9, 0) == pytest.approx(1.0)
    assert s.sell_price(0.1, 0) == pytest.approx(0.0)


def test_linear_impact_scales_with_size():
    s = LinearImpact(half_spread=0.01, impact_per_dollar=1e-5)
    small = s.buy_price(0.5, 100)
    big = s.buy_price(0.5, 1_000)
    assert big > small
    assert abs(small - (0.5 + 0.01 + 1e-5 * 100)) < 1e-12
    assert abs(big - (0.5 + 0.01 + 1e-5 * 1_000)) < 1e-12


def test_sqrt_impact_is_concave():
    s = SqrtImpact(half_spread=0.0, k=0.01)
    a = s.buy_price(0.5, 100) - 0.5
    b = s.buy_price(0.5, 400) - 0.5
    # Doubling size at sqrt should multiply impact by sqrt(4) = 2.
    assert math.isclose(b / a, 2.0, rel_tol=1e-9)


def test_sell_impact_is_negative_side():
    s = LinearImpact(half_spread=0.01, impact_per_dollar=1e-4)
    buy = s.buy_price(0.5, 1_000)
    sell = s.sell_price(0.5, 1_000)
    assert buy > 0.5 > sell
    assert abs((buy - 0.5) - (0.5 - sell)) < 1e-12


def test_factory_from_config():
    cfg = Config(slippage_model="linear", half_spread=0.005, impact_per_dollar=1e-4)
    s = build_from_config(cfg)
    assert isinstance(s, LinearImpact)
    assert s.half_spread == 0.005
    assert s.impact_per_dollar == 1e-4

    cfg2 = Config(slippage_model="sqrt", impact_sqrt_k=3e-4)
    s2 = build_from_config(cfg2)
    assert isinstance(s2, SqrtImpact)
    assert s2.k == 3e-4


def test_factory_rejects_unknown_model():
    with pytest.raises(ValueError):
        Config(slippage_model="nonsense")


def test_book_walk_single_level_full_fill():
    book = BookSnapshot(bids=[(0.48, 100.0)], asks=[(0.52, 100.0)])
    store = SnapshotStore({1000: book})
    s = BookWalkSlippage(store.at)
    # Buy $10 at 0.52 -- fully within level.
    fill = s.buy_price(0.5, 10.0, ts=1000)
    assert abs(fill - 0.52) < 1e-9


def test_book_walk_sweeps_multiple_levels():
    book = BookSnapshot(
        bids=[(0.48, 10.0), (0.40, 100.0)],
        asks=[(0.52, 10.0), (0.60, 100.0)],
    )
    store = SnapshotStore({1000: book})
    s = BookWalkSlippage(store.at)
    # Ask[0]: 10 contracts * 0.52 = $5.20 notional. Buy $10.00 -> must
    # sweep into ask[1] at 0.60.
    fill = s.buy_price(0.5, 10.0, ts=1000)
    assert fill > 0.52
    assert fill < 0.60


def test_book_walk_falls_back_without_snapshot():
    s = BookWalkSlippage(lambda ts: None, fallback=ConstantSpread(half_spread=0.03))
    assert abs(s.buy_price(0.5, 100) - 0.53) < 1e-12


def test_snapshot_store_returns_most_recent_at_or_before():
    store = SnapshotStore()
    a = BookSnapshot(bids=[], asks=[(0.50, 1)])
    b = BookSnapshot(bids=[], asks=[(0.55, 1)])
    store.add(100, a)
    store.add(200, b)
    assert store.at(150) is a
    assert store.at(250) is b
    assert store.at(50) is None
