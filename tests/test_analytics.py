"""src/analytics.py のテスト。"""

from src.analytics import (
    build_equity_curve,
    by_direction,
    by_hour,
    by_market,
    by_signal_strength,
    compute_max_drawdown,
    compute_summary,
    recent_n,
)


def _make_trades() -> list[dict]:
    """テスト用の取引リストを生成する。"""
    return [
        {
            "trade_id": "t1", "signal_time": "2024-01-01T10:00:00Z",
            "market_id": "m1", "market_title": "Market A",
            "direction": "Buy-Yes", "entry_price": 0.60,
            "entry_amount_usd": 50.0, "exit_price": 0.70,
            "pnl_usd": 8.33, "holding_minutes": 30.0, "result": "win",
        },
        {
            "trade_id": "t2", "signal_time": "2024-01-01T14:00:00Z",
            "market_id": "m1", "market_title": "Market A",
            "direction": "Buy-Yes", "entry_price": 0.65,
            "entry_amount_usd": 50.0, "exit_price": 0.55,
            "pnl_usd": -7.69, "holding_minutes": 45.0, "result": "loss",
        },
        {
            "trade_id": "t3", "signal_time": "2024-01-02T10:30:00Z",
            "market_id": "m2", "market_title": "Market B",
            "direction": "Sell-No", "entry_price": 0.40,
            "entry_amount_usd": 50.0, "exit_price": 0.30,
            "pnl_usd": 12.50, "holding_minutes": 60.0, "result": "win",
        },
        {
            "trade_id": "t4", "signal_time": "2024-01-02T14:15:00Z",
            "market_id": "m2", "market_title": "Market B",
            "direction": "Sell-No", "entry_price": 0.45,
            "entry_amount_usd": 50.0, "exit_price": 0.50,
            "pnl_usd": -5.56, "holding_minutes": 20.0, "result": "loss",
        },
    ]


def test_compute_summary_basic():
    trades = _make_trades()
    s = compute_summary(trades)
    assert s["count"] == 4
    assert s["wins"] == 2
    assert s["losses"] == 2
    assert s["win_rate"] == 50.0
    assert s["max_consecutive_losses"] == 1
    assert s["profit_factor"] > 0


def test_compute_summary_empty():
    s = compute_summary([])
    assert s["count"] == 0
    assert s["max_drawdown"] == 0.0
    assert s["profit_factor"] == 0.0


def test_build_equity_curve():
    trades = _make_trades()
    curve = build_equity_curve(trades)
    assert len(curve) == 4
    assert curve[0]["trade_no"] == 1
    assert curve[0]["cumulative_pnl"] == round(8.33, 2)
    assert curve[1]["cumulative_pnl"] == round(8.33 + (-7.69), 2)


def test_compute_max_drawdown():
    curve = [
        {"cumulative_pnl": 10.0},
        {"cumulative_pnl": 5.0},
        {"cumulative_pnl": 15.0},
        {"cumulative_pnl": 8.0},
    ]
    dd_abs, dd_pct = compute_max_drawdown(curve)
    assert dd_abs == 7.0  # peak 15 - trough 8
    assert dd_pct > 0


def test_compute_max_drawdown_empty():
    dd_abs, dd_pct = compute_max_drawdown([])
    assert dd_abs == 0.0
    assert dd_pct == 0.0


def test_by_market():
    trades = _make_trades()
    result = by_market(trades)
    assert "Market A" in result
    assert "Market B" in result
    assert result["Market A"]["count"] == 2
    assert result["Market B"]["count"] == 2


def test_by_direction():
    trades = _make_trades()
    result = by_direction(trades)
    assert "Buy-Yes" in result
    assert "Sell-No" in result
    assert result["Buy-Yes"]["count"] == 2
    assert result["Sell-No"]["count"] == 2


def test_by_hour():
    trades = _make_trades()
    result = by_hour(trades)
    assert "10:00" in result
    assert "14:00" in result


def test_by_signal_strength_default():
    trades = _make_trades()
    result = by_signal_strength(trades)
    # デフォルトでは全てSTRONG
    assert "STRONG" in result
    assert result["STRONG"]["count"] == 4


def test_by_signal_strength_with_signals():
    trades = _make_trades()
    signals = [
        {"market_id": "m1", "direction": "Buy-Yes", "is_strong": 1, "total_amount_usdc": 6000},
        {"market_id": "m2", "direction": "Sell-No", "is_strong": 0, "total_amount_usdc": 1000},
    ]
    result = by_signal_strength(trades, signals)
    assert "STRONG+" in result
    assert "NORMAL" in result
    assert result["STRONG+"]["count"] == 2
    assert result["NORMAL"]["count"] == 2


def test_recent_n():
    trades = _make_trades()
    result = recent_n(trades, 2)
    assert result["count"] == 2


def test_recent_n_empty():
    result = recent_n([], 20)
    assert result["count"] == 0
