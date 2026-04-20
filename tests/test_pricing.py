"""Tests for bs_edge.pricing."""

from __future__ import annotations

import math

import pytest

from bs_edge.pricing import (
    digital_call_price,
    digital_put_price,
    implied_sigma,
    quote_edge,
)


def test_digital_call_atm_at_half():
    # At S=K with zero drift, Phi(d2) with d2 = -0.5*sigma*sqrt(T)
    # is < 0.5 but approaches 0.5 as sigma*sqrt(T) -> 0.
    # For vanishing vol*T, price -> 0.5.
    price = digital_call_price(100.0, 100.0, 1e-8, 0.5, rate=0.0)
    assert abs(price - 0.5) < 1e-3


def test_digital_call_deep_itm_near_one():
    # S >> K should price near 1.
    assert digital_call_price(200.0, 100.0, 1.0, 0.3) > 0.98


def test_digital_call_deep_otm_near_zero():
    assert digital_call_price(50.0, 100.0, 1.0, 0.3) < 0.05


def test_digital_put_complements_call():
    c = digital_call_price(110.0, 100.0, 0.25, 0.4, rate=0.01)
    p = digital_put_price(110.0, 100.0, 0.25, 0.4, rate=0.01)
    assert abs(c + p - 1.0) < 1e-9


def test_quote_edge_up_vs_down_symmetric():
    up = quote_edge("UP", 100.0, 100.0, 0.25, 0.5, market_price=0.5)
    down = quote_edge("DOWN", 100.0, 100.0, 0.25, 0.5, market_price=0.5)
    assert abs(up.model_price + down.model_price - 1.0) < 1e-9


def test_quote_edge_ev_sign_matches_edge_sign():
    # If model > market, a buy at market should have positive EV.
    q = quote_edge("UP", 101.0, 100.0, 0.1, 0.5, market_price=0.4)
    assert q.edge > 0
    assert q.expected_value > 0


def test_quote_edge_rejects_bad_market_price():
    with pytest.raises(ValueError):
        quote_edge("UP", 100, 100, 0.1, 0.5, market_price=1.5)


def test_quote_edge_rejects_unknown_side():
    with pytest.raises(ValueError):
        quote_edge("SIDEWAYS", 100, 100, 0.1, 0.5, market_price=0.5)


def test_implied_sigma_roundtrip():
    sigma_true = 0.72
    fair = digital_call_price(100.0, 100.0, 0.25, sigma_true)
    sigma_impl = implied_sigma("UP", 100.0, 100.0, 0.25, fair)
    assert sigma_impl is not None
    assert abs(sigma_impl - sigma_true) < 1e-3


def test_implied_sigma_returns_none_at_boundary():
    assert implied_sigma("UP", 100.0, 100.0, 0.25, 0.0) is None
    assert implied_sigma("UP", 100.0, 100.0, 0.25, 1.0) is None


def test_pricing_rejects_bad_inputs():
    with pytest.raises(ValueError):
        digital_call_price(0, 100, 1.0, 0.3)
    with pytest.raises(ValueError):
        digital_call_price(100, 100, 0.0, 0.3)
    with pytest.raises(ValueError):
        digital_call_price(100, 100, 1.0, 0.0)


def test_monotone_in_spot():
    t = 0.1
    sigma = 0.6
    prices = [digital_call_price(s, 100.0, t, sigma) for s in (80, 90, 100, 110, 120)]
    assert all(a < b for a, b in zip(prices, prices[1:]))
