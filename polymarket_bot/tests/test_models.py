"""Tests for data models."""

from src.models import Market, MarketToken, OrderBookLevel, OrderBookSnapshot


class TestOrderBookSnapshot:
    def test_best_bid_ask(self):
        book = OrderBookSnapshot(
            bids=[OrderBookLevel(0.50, 100), OrderBookLevel(0.49, 200)],
            asks=[OrderBookLevel(0.52, 100), OrderBookLevel(0.53, 200)],
        )
        assert book.best_bid == 0.50
        assert book.best_ask == 0.52
        assert abs(book.spread - 0.02) < 1e-10

    def test_empty_book(self):
        book = OrderBookSnapshot()
        assert book.best_bid is None
        assert book.best_ask is None
        assert book.spread is None
        assert book.best_bid_size == 0.0

    def test_sizes(self):
        book = OrderBookSnapshot(
            bids=[OrderBookLevel(0.50, 150)],
            asks=[OrderBookLevel(0.52, 75)],
        )
        assert book.best_bid_size == 150.0
        assert book.best_ask_size == 75.0


class TestMarket:
    def test_yes_no_tokens(self):
        market = Market(
            condition_id="c1",
            question="Test?",
            slug="test",
            tokens=[
                MarketToken(token_id="t1", outcome="Yes", price=0.5),
                MarketToken(token_id="t2", outcome="No", price=0.5),
            ],
        )
        assert market.yes_token is not None
        assert market.yes_token.token_id == "t1"
        assert market.no_token is not None
        assert market.no_token.token_id == "t2"

    def test_no_tokens(self):
        market = Market(condition_id="c1", question="Test?", slug="test")
        assert market.yes_token is None
        assert market.no_token is None
