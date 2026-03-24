"""Tests for the signal engine."""

import pytest

from src.config import Config
from src.models import Market, MarketToken, OrderBookLevel, OrderBookSnapshot
from src.signal_engine import PriceHistory, SignalEngine


def make_config(**overrides) -> Config:
    defaults = {
        "api_base": "https://clob.polymarket.com",
        "ws_url": "wss://example.com/ws",
        "mispricing_threshold": 0.02,
        "spread_max": 0.10,
        "liquidity_min_size": 50.0,
        "momentum_window_sec": 60,
        "momentum_max_change": 0.05,
        "confidence_threshold": 60.0,
        "weight_mispricing": 0.40,
        "weight_spread": 0.25,
        "weight_liquidity": 0.20,
        "weight_momentum": 0.15,
    }
    defaults.update(overrides)
    return Config(**defaults)


def make_market(
    yes_bid: float = 0.50,
    yes_ask: float = 0.52,
    no_bid: float = 0.48,
    no_ask: float = 0.50,
    bid_size: float = 100.0,
    ask_size: float = 100.0,
) -> Market:
    return Market(
        condition_id="test-condition-123",
        question="Will BTC be above $100k in 5 minutes?",
        slug="btc-5min-test",
        tokens=[
            MarketToken(
                token_id="yes-token-1",
                outcome="Yes",
                price=yes_bid,
                order_book=OrderBookSnapshot(
                    bids=[OrderBookLevel(price=yes_bid, size=bid_size)],
                    asks=[OrderBookLevel(price=yes_ask, size=ask_size)],
                ),
            ),
            MarketToken(
                token_id="no-token-1",
                outcome="No",
                price=no_bid,
                order_book=OrderBookSnapshot(
                    bids=[OrderBookLevel(price=no_bid, size=bid_size)],
                    asks=[OrderBookLevel(price=no_ask, size=ask_size)],
                ),
            ),
        ],
    )


class TestMispricing:
    def test_fair_market(self):
        """ask_sum = 1.0 should have mispricing ~0."""
        engine = SignalEngine(make_config())
        score = engine._calc_mispricing(0.49, 0.51, 0.49, 0.49)
        assert score >= 0

    def test_underpriced_market(self):
        """ask_sum < 1.0 should show positive mispricing."""
        engine = SignalEngine(make_config())
        # yes_ask=0.45, no_ask=0.45 => sum=0.90, deviation=0.10
        score = engine._calc_mispricing(0.44, 0.45, 0.44, 0.45)
        assert score >= 0.08

    def test_overpriced_market(self):
        """ask_sum > 1.0 should also show deviation."""
        engine = SignalEngine(make_config())
        score = engine._calc_mispricing(0.55, 0.56, 0.55, 0.56)
        assert score > 0.10


class TestSpreadScore:
    def test_tight_spread(self):
        engine = SignalEngine(make_config())
        score = engine._calc_spread_score(0.01, 0.01)
        assert score is not None
        assert score > 0.8

    def test_wide_spread(self):
        engine = SignalEngine(make_config(spread_max=0.10))
        score = engine._calc_spread_score(0.09, 0.09)
        assert score is not None
        assert score < 0.2


class TestLiquidity:
    def test_deep_liquidity(self):
        engine = SignalEngine(make_config(liquidity_min_size=50.0))
        score = engine._calc_liquidity_score(500, 500, 500, 500)
        assert score >= 0.9

    def test_thin_liquidity(self):
        engine = SignalEngine(make_config(liquidity_min_size=50.0))
        score = engine._calc_liquidity_score(10, 10, 10, 10)
        assert score < 0.1


class TestEvaluate:
    def test_excluded_by_spread(self):
        """Market with wide spread should be excluded."""
        engine = SignalEngine(make_config(spread_max=0.05))
        market = make_market(yes_bid=0.40, yes_ask=0.52, no_bid=0.40, no_ask=0.52)
        result = engine.evaluate(market)
        assert result is None

    def test_excluded_by_liquidity(self):
        """Market with thin liquidity should be excluded."""
        engine = SignalEngine(make_config(liquidity_min_size=200.0))
        market = make_market(bid_size=10.0, ask_size=10.0)
        result = engine.evaluate(market)
        assert result is None

    def test_signal_detected(self):
        """Underpriced market with good liquidity should produce a signal."""
        engine = SignalEngine(make_config(
            confidence_threshold=10.0,  # Low threshold for test
            liquidity_min_size=10.0,
        ))
        # ask_sum = 0.90, big mispricing
        market = make_market(
            yes_bid=0.44, yes_ask=0.45,
            no_bid=0.44, no_ask=0.45,
            bid_size=200, ask_size=200,
        )
        result = engine.evaluate(market)
        assert result is not None
        assert result.mispricing_score > 0.05
        assert result.confidence_score > 0

    def test_no_signal_fair_market(self):
        """Fair market should not produce high confidence."""
        engine = SignalEngine(make_config(confidence_threshold=90.0))
        market = make_market(
            yes_bid=0.49, yes_ask=0.51,
            no_bid=0.49, no_ask=0.49,
        )
        result = engine.evaluate(market)
        # Result may exist but confidence should be below 90
        if result:
            assert result.confidence_score < 90


class TestPriceHistory:
    def test_record_and_retrieve(self):
        ph = PriceHistory(window_sec=60)
        ph.record("token-1", 0.50)
        ph.record("token-1", 0.52)
        change = ph.get_change_rate("token-1")
        assert change is not None
        assert abs(change - 0.04) < 0.001

    def test_no_data(self):
        ph = PriceHistory(window_sec=60)
        assert ph.get_change_rate("unknown") is None
