"""Tests for metrics collection."""

from datetime import datetime

from src.metrics import MetricsCollector
from src.models import (
    Market,
    MarketToken,
    PaperPosition,
    PositionStatus,
    TradeAction,
)


def make_position(pnl: float = 0.1, status: PositionStatus = PositionStatus.CLOSED_TP) -> PaperPosition:
    market = Market(condition_id="c1", question="Test", slug="test",
                    tokens=[MarketToken("t1", "Yes"), MarketToken("t2", "No")])
    return PaperPosition(
        position_id="p1",
        market=market,
        action=TradeAction.BUY_YES,
        entry_price=0.50,
        size=10.0,
        entry_time=datetime.utcnow(),
        status=status,
        exit_price=0.51,
        exit_time=datetime.utcnow(),
        pnl=pnl,
    )


class TestMetrics:
    def test_daily_summary(self):
        collector = MetricsCollector(data_dir="/tmp/polymarket_test_data")
        collector.record_position(make_position(pnl=0.5))
        collector.record_position(make_position(pnl=-0.2, status=PositionStatus.CLOSED_SL))
        collector.record_position(make_position(pnl=0.3))

        summary = collector.generate_daily_summary()
        assert summary.total_trades == 3
        assert summary.winning_trades == 2
        assert summary.losing_trades == 1
        assert abs(summary.total_pnl - 0.6) < 0.001
        assert summary.win_rate > 60

    def test_empty_summary(self):
        collector = MetricsCollector(data_dir="/tmp/polymarket_test_data")
        summary = collector.generate_daily_summary("2099-01-01")
        assert summary.total_trades == 0
        assert summary.win_rate == 0
