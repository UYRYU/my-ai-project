from src.config import Config
from src.positions import Book
from src.risk import DailyCounters, check


def _cfg(**overrides) -> Config:
    base = dict(
        anthropic_api_key="",
        polymarket_private_key="",
        polymarket_funder="",
        polymarket_host="",
        polymarket_api_key="",
        polymarket_api_secret="",
        polymarket_api_passphrase="",
        sports_tags=("nba",),
        min_edge=0.003,
        max_position_usd=50.0,
        bankroll_usd=500.0,
        poll_seconds=2.0,
        dry_run=True,
        mock=True,
        once=True,
    )
    base.update(overrides)
    return Config(**base)


def test_allow_normal_basket():
    d = check(20.0, 2, _cfg(), Book(), DailyCounters())
    assert d.allow


def test_reject_oversized_basket():
    d = check(60.0, 2, _cfg(), Book(), DailyCounters())
    assert not d.allow
    assert "max_position" in d.reason


def test_reject_zero_legs():
    d = check(20.0, 0, _cfg(), Book(), DailyCounters())
    assert not d.allow


def test_reject_daily_loss_cap():
    counters = DailyCounters()
    counters.realized_pnl_today = -100.0
    d = check(20.0, 2, _cfg(), Book(), counters, max_daily_loss_usd=100.0)
    assert not d.allow
    assert "daily loss" in d.reason


def test_reject_basket_count_cap():
    counters = DailyCounters()
    counters.baskets_today = 200
    d = check(20.0, 2, _cfg(), Book(), counters, max_baskets_per_day=200)
    assert not d.allow
    assert "daily basket" in d.reason


def test_reject_gross_exposure_cap():
    book = Book()
    # Exceed 10x max_position_usd = $500
    book.record_fill("t", shares=1000, price=0.51)  # $510 cost basis
    d = check(20.0, 2, _cfg(max_position_usd=50.0), book, DailyCounters())
    assert not d.allow
    assert "gross exposure" in d.reason
