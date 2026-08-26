from types import SimpleNamespace

from src.executor import ExecutionLeg, _build_execution_legs, _dry_run_fill
from src.orderbook import FillQuote


def test_execution_uses_equal_shares_and_worst_consumed_prices():
    opp = SimpleNamespace(legs=(("yes", 0.40), ("no", 0.50)))
    cfg = SimpleNamespace(max_position_usd=50.0)
    quotes = [
        FillQuote("yes", 0.41, 50.0, 2, limit_price=0.42),
        FillQuote("no", 0.51, 50.0, 2, limit_price=0.52),
    ]

    legs = _build_execution_legs(opp, cfg, quotes)

    assert [leg.size for leg in legs] == [50.0, 50.0]
    assert [leg.limit_price for leg in legs] == [0.42, 0.52]


def test_dry_run_records_the_same_share_count_for_every_outcome():
    fills = []
    book = SimpleNamespace(
        record_fill=lambda token_id, shares, price: fills.append(
            (token_id, shares, price)
        )
    )
    legs = [
        ExecutionLeg("yes", 0.42, 50.0, 0.41),
        ExecutionLeg("no", 0.52, 50.0, 0.51),
    ]

    _dry_run_fill(legs, book)

    assert [fill[1] for fill in fills] == [50.0, 50.0]
