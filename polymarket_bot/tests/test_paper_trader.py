"""Tests for the paper trader."""

from datetime import datetime, timedelta

from src.config import Config
from src.models import (
    Market,
    MarketToken,
    OrderBookLevel,
    OrderBookSnapshot,
    PositionStatus,
    SignalResult,
    TradeAction,
)
from src.paper_trader import PaperTrader


def make_config(**overrides) -> Config:
    defaults = {
        "gamma_api": "https://gamma-api.polymarket.com",
        "clob_api": "https://clob.polymarket.com",
        "ws_url": "wss://example.com/ws",
        "paper_trade_size": 10.0,
        "paper_take_profit": 0.05,
        "paper_stop_loss": 0.03,
        "paper_timeout_sec": 300,
        "paper_max_positions": 3,
    }
    defaults.update(overrides)
    return Config(**defaults)


def make_market_and_signal(
    yes_bid=0.50, yes_ask=0.52, no_bid=0.48, no_ask=0.50,
    size=100.0, action=TradeAction.BUY_YES, edge=0.02,
) -> tuple[Market, SignalResult]:
    market = Market(
        condition_id="cond-1",
        question="BTC 5min test",
        slug="btc-test",
        tokens=[
            MarketToken(
                token_id="yes-1",
                outcome="Yes",
                price=yes_bid,
                order_book=OrderBookSnapshot(
                    bids=[OrderBookLevel(price=yes_bid, size=size)],
                    asks=[OrderBookLevel(price=yes_ask, size=size)],
                ),
            ),
            MarketToken(
                token_id="no-1",
                outcome="No",
                price=no_bid,
                order_book=OrderBookSnapshot(
                    bids=[OrderBookLevel(price=no_bid, size=size)],
                    asks=[OrderBookLevel(price=no_ask, size=size)],
                ),
            ),
        ],
    )
    signal = SignalResult(
        market=market,
        confidence_score=80.0,
        recommended_action=action,
        expected_edge=edge,
    )
    return market, signal


class TestPaperTrader:
    def test_enter_position(self):
        trader = PaperTrader(make_config())
        market, signal = make_market_and_signal()
        pos = trader.enter(signal)
        assert pos is not None
        assert pos.entry_price == 0.52  # yes_ask for BUY_YES
        assert pos.status == PositionStatus.OPEN
        assert trader.position_count == 1

    def test_max_positions(self):
        trader = PaperTrader(make_config(paper_max_positions=1))
        _, sig1 = make_market_and_signal()
        _, sig2 = make_market_and_signal()
        pos1 = trader.enter(sig1)
        pos2 = trader.enter(sig2)
        assert pos1 is not None
        assert pos2 is None

    def test_take_profit_exit(self):
        trader = PaperTrader(make_config(paper_take_profit=0.05))
        market, signal = make_market_and_signal(yes_ask=0.50)
        pos = trader.enter(signal)
        assert pos is not None

        # Update market price to trigger TP
        # entry = 0.50, TP = 0.05 * 10 = 0.50 pnl needed
        # current_bid needs to be >= 0.50 + 0.05 = 0.55
        market.tokens[0].order_book = OrderBookSnapshot(
            bids=[OrderBookLevel(price=0.56, size=100)],
            asks=[OrderBookLevel(price=0.57, size=100)],
        )
        closed = trader.check_exits(market)
        assert len(closed) == 1
        assert closed[0].status == PositionStatus.CLOSED_TP
        assert closed[0].pnl > 0

    def test_stop_loss_exit(self):
        trader = PaperTrader(make_config(paper_stop_loss=0.03))
        market, signal = make_market_and_signal(yes_ask=0.50)
        pos = trader.enter(signal)
        assert pos is not None

        # Update price to trigger SL
        market.tokens[0].order_book = OrderBookSnapshot(
            bids=[OrderBookLevel(price=0.46, size=100)],
            asks=[OrderBookLevel(price=0.47, size=100)],
        )
        closed = trader.check_exits(market)
        assert len(closed) == 1
        assert closed[0].status == PositionStatus.CLOSED_SL
        assert closed[0].pnl < 0

    def test_timeout_exit(self):
        trader = PaperTrader(make_config(paper_timeout_sec=0))  # Immediate timeout
        market, signal = make_market_and_signal(yes_ask=0.50)
        pos = trader.enter(signal)
        assert pos is not None

        closed = trader.check_exits(market)
        assert len(closed) == 1
        assert closed[0].status == PositionStatus.CLOSED_TIMEOUT

    def test_close_all(self):
        trader = PaperTrader(make_config(paper_max_positions=5))
        market, signal = make_market_and_signal()
        trader.enter(signal)
        trader.enter(signal)

        closed = trader.close_all(market)
        assert len(closed) == 2
        assert trader.position_count == 0
