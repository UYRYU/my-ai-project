from datetime import datetime, timedelta, timezone

from src.market_filter import is_tradeable, filter_tradeable
from src.polymarket import Market, MarketOutcome


def _m(bid_a=0.48, ask_a=0.50, bid_b=0.48, ask_b=0.50, end=None, slug="nba-a-vs-b") -> Market:
    return Market(
        condition_id="c", question="Q", slug=slug, end_date=end, category="sports",
        outcomes=(
            MarketOutcome("t0", "A", bid_a, ask_a),
            MarketOutcome("t1", "B", bid_b, ask_b),
        ),
    )


def test_healthy_market_passes():
    end = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    ok, reason = is_tradeable(_m(end=end))
    assert ok, reason


def test_wide_spread_rejected():
    ok, reason = is_tradeable(_m(bid_a=0.30, ask_a=0.50), max_spread=0.05)
    assert not ok
    assert "spread" in reason


def test_near_boundary_rejected():
    ok, reason = is_tradeable(_m(bid_a=0.98, ask_a=0.99))
    assert not ok
    assert "boundary" in reason


def test_zero_quote_rejected():
    ok, reason = is_tradeable(_m(bid_a=0.0, ask_a=0.50))
    assert not ok


def test_too_close_to_resolution_rejected():
    end = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    ok, reason = is_tradeable(_m(end=end), min_hours_to_close=0.25)
    assert not ok
    assert "closes in" in reason


def test_too_far_from_resolution_rejected():
    end = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat().replace("+00:00", "Z")
    ok, reason = is_tradeable(_m(end=end), max_hours_to_close=72)
    assert not ok


def test_filter_tradeable_counts_rejections():
    end_good = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    end_bad = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    markets = [
        _m(end=end_good),
        _m(bid_a=0.30, ask_a=0.50, end=end_good),  # wide spread
        _m(end=end_bad),  # too close
    ]
    kept, rejected = filter_tradeable(markets)
    assert len(kept) == 1
    assert sum(rejected.values()) == 2
