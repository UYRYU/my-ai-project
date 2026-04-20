from src.arbitrage import scan_single_market, scan_overround
from src.polymarket import Market, MarketOutcome


def _market(asks: list[float], bids: list[float] | None = None) -> Market:
    bids = bids or [a - 0.01 for a in asks]
    outcomes = tuple(
        MarketOutcome(token_id=f"t{i}", label=f"O{i}", best_bid=b, best_ask=a)
        for i, (a, b) in enumerate(zip(asks, bids))
    )
    return Market("c", "Q?", "slug", None, "sports", outcomes)


def test_sum_under_one_detected():
    m = _market(asks=[0.45, 0.50])
    opp = scan_single_market(m, min_edge=0.01)
    assert opp is not None
    assert abs(opp.edge - 0.05) < 1e-9


def test_sum_just_under_one_below_min_edge_skipped():
    m = _market(asks=[0.499, 0.499])
    assert scan_single_market(m, min_edge=0.01) is None


def test_three_way_market_arb():
    m = _market(asks=[0.30, 0.30, 0.30])
    opp = scan_single_market(m, min_edge=0.05)
    assert opp is not None
    assert abs(opp.edge - 0.10) < 1e-9


def test_no_arb_when_sum_over_one():
    m = _market(asks=[0.55, 0.55])
    assert scan_single_market(m, min_edge=0.01) is None


def test_overround_detected_on_bid_side():
    m = _market(asks=[0.60, 0.60], bids=[0.55, 0.55])
    opp = scan_overround(m, min_edge=0.05)
    assert opp is not None
    assert abs(opp.edge - 0.10) < 1e-9


def test_skip_degenerate_prices():
    m = _market(asks=[0.0, 0.5])
    assert scan_single_market(m, min_edge=0.0) is None
    m = _market(asks=[1.0, 0.0])
    assert scan_single_market(m, min_edge=0.0) is None
