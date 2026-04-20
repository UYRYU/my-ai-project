from src.edge_calc import assess, kelly_size
from src.orderbook import FillQuote


def _q(price: float) -> FillQuote:
    return FillQuote(token_id="t", avg_price=price, filled_size=50, levels_used=1)


def test_healthy_arb_passes():
    # 0.45 + 0.50 = 0.95, payout 50 → raw edge $2.50
    a = assess([_q(0.45), _q(0.50)], target_payout_usd=50.0)
    assert a.recommend_trade
    assert a.raw_edge_usd == 2.5
    assert a.fee_adjusted_edge_usd < a.raw_edge_usd  # fees eat some
    assert a.net_edge_pct > 0.002


def test_thin_edge_rejected_after_fees():
    # 0.498 + 0.499 = 0.997 → raw edge $0.15. After fees likely negative
    a = assess([_q(0.498), _q(0.499)], target_payout_usd=50.0)
    assert not a.recommend_trade


def test_kelly_sizes_scale_with_edge():
    small = kelly_size(1000, edge_pct=0.003)
    big = kelly_size(1000, edge_pct=0.02)
    assert big > small
    assert small > 0


def test_kelly_caps_at_max_pct():
    # Huge edge but cap should kick in at 10% of bankroll
    size = kelly_size(1000, edge_pct=1.0)
    assert size <= 100.0  # 10% cap


def test_kelly_zero_on_negative_edge():
    assert kelly_size(1000, edge_pct=-0.01) == 0
    assert kelly_size(0, edge_pct=0.01) == 0
