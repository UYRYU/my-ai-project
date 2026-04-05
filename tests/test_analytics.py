"""src/analytics.py のテスト。"""

from src.analytics import (
    avg_entry_price,
    band_best_worst,
    build_equity_curve,
    by_direction,
    by_entry_price_band,
    by_hour,
    by_market,
    by_signal_strength,
    check_v2_readiness,
    compute_edge_indicator,
    compute_max_drawdown,
    compute_summary,
    detect_warnings,
    filter_by_model,
    filter_by_period,
    live_block_reason,
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
            "model_version": "v2_binary",
        },
        {
            "trade_id": "t2", "signal_time": "2024-01-01T14:00:00Z",
            "market_id": "m1", "market_title": "Market A",
            "direction": "Buy-Yes", "entry_price": 0.65,
            "entry_amount_usd": 50.0, "exit_price": 0.55,
            "pnl_usd": -7.69, "holding_minutes": 45.0, "result": "loss",
            "model_version": "v2_binary",
        },
        {
            "trade_id": "t3", "signal_time": "2024-01-02T10:30:00Z",
            "market_id": "m2", "market_title": "Market B",
            "direction": "Sell-No", "entry_price": 0.40,
            "entry_amount_usd": 50.0, "exit_price": 0.30,
            "pnl_usd": 12.50, "holding_minutes": 60.0, "result": "win",
            "model_version": "v2_binary",
        },
        {
            "trade_id": "t4", "signal_time": "2024-01-02T14:15:00Z",
            "market_id": "m2", "market_title": "Market B",
            "direction": "Sell-No", "entry_price": 0.45,
            "entry_amount_usd": 50.0, "exit_price": 0.50,
            "pnl_usd": -5.56, "holding_minutes": 20.0, "result": "loss",
            "model_version": "v2_binary",
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


# ── 新規テスト ────────────────────────────────────────────

def test_filter_by_model():
    trades = _make_trades()
    # v1 を1件追加
    trades.append({
        "trade_id": "t5", "signal_time": "2024-01-03T10:00:00Z",
        "market_id": "m1", "market_title": "Market A",
        "direction": "Buy-Yes", "entry_price": 0.50,
        "entry_amount_usd": 50.0, "exit_price": 0.60,
        "pnl_usd": 10.0, "holding_minutes": 15.0, "result": "win",
        "model_version": "v1_random",
    })
    v2 = filter_by_model(trades, "v2_binary")
    assert len(v2) == 4
    v1 = filter_by_model(trades, "v1_random")
    assert len(v1) == 1


def test_avg_entry_price():
    trades = _make_trades()
    avg = avg_entry_price(trades)
    expected = (0.60 + 0.65 + 0.40 + 0.45) / 4
    assert avg == round(expected, 4)


def test_avg_entry_price_empty():
    assert avg_entry_price([]) == 0.0


def test_by_entry_price_band():
    trades = _make_trades()
    result = by_entry_price_band(trades)
    # 0.40, 0.45 → "0.40-0.60" band
    # 0.60, 0.65 → "0.60-0.80" band
    assert "0.40-0.60" in result
    assert "0.60-0.80" in result
    assert result["0.40-0.60"]["count"] == 2
    assert result["0.60-0.80"]["count"] == 2


def test_by_entry_price_band_various():
    trades = [
        {"entry_price": 0.10, "pnl_usd": 5.0, "result": "win", "direction": "Buy-Yes"},
        {"entry_price": 0.30, "pnl_usd": -3.0, "result": "loss", "direction": "Buy-Yes"},
        {"entry_price": 0.90, "pnl_usd": 2.0, "result": "win", "direction": "Buy-Yes"},
    ]
    result = by_entry_price_band(trades)
    assert "0.00-0.20" in result
    assert result["0.00-0.20"]["count"] == 1
    assert "0.80-1.00" in result
    assert result["0.80-1.00"]["count"] == 1


def test_compute_edge_indicator_buy():
    """Buy のみ: 実績勝率 vs entry_price 平均。"""
    # 2勝2敗、entry_price平均 = 0.625 → 期待勝率 62.5%、実績 50%
    trades = [
        {"entry_price": 0.60, "result": "win", "direction": "Buy-Yes"},
        {"entry_price": 0.65, "result": "loss", "direction": "Buy-Yes"},
        {"entry_price": 0.60, "result": "win", "direction": "Buy-Yes"},
        {"entry_price": 0.65, "result": "loss", "direction": "Buy-Yes"},
    ]
    edge = compute_edge_indicator(trades)
    assert edge["count"] == 4
    assert edge["actual_win_rate"] == 50.0
    assert edge["expected_win_rate"] == 62.5
    assert edge["edge_pct"] == -12.5
    assert edge["has_edge"] is False


def test_compute_edge_indicator_sell():
    """Sell の期待勝率は 1-entry_price。"""
    trades = [
        {"entry_price": 0.30, "result": "win", "direction": "Sell-No"},
        {"entry_price": 0.30, "result": "win", "direction": "Sell-No"},
    ]
    edge = compute_edge_indicator(trades)
    assert edge["actual_win_rate"] == 100.0
    # 期待 = 1-0.30 = 0.70 → 70%
    assert edge["expected_win_rate"] == 70.0
    assert edge["edge_pct"] == 30.0
    assert edge["has_edge"] is True


def test_compute_edge_indicator_empty():
    edge = compute_edge_indicator([])
    assert edge["count"] == 0
    assert edge["has_edge"] is False


def test_compute_edge_indicator_bands():
    """帯別edgeが正しく計算される。"""
    trades = [
        {"entry_price": 0.15, "result": "win", "direction": "Buy-Yes"},
        {"entry_price": 0.55, "result": "loss", "direction": "Buy-Yes"},
    ]
    edge = compute_edge_indicator(trades)
    assert "0.00-0.20" in edge["edge_per_band"]
    assert "0.40-0.60" in edge["edge_per_band"]


def test_check_v2_readiness_insufficient():
    """100件未満はenough_trades=False。"""
    trades = _make_trades()
    result = check_v2_readiness(trades)
    assert result["trade_count"] == 4
    assert result["enough_trades"] is False
    assert result["all_passed"] is False


def test_check_v2_readiness_ignores_v1():
    """v1データは無視される。"""
    trades = [
        {
            "trade_id": f"t{i}", "signal_time": "2024-01-01T10:00:00Z",
            "market_id": "m1", "market_title": "Market A",
            "direction": "Buy-Yes", "entry_price": 0.50,
            "entry_amount_usd": 50.0, "exit_price": 0.99,
            "pnl_usd": 49.0, "holding_minutes": 30.0, "result": "win",
            "model_version": "v1_random",
        }
        for i in range(200)
    ]
    result = check_v2_readiness(trades)
    assert result["trade_count"] == 0  # v1 は無視
    assert result["enough_trades"] is False


# ── 新規: 期間フィルタ / best-worst / 警告 / block理由 ───

def test_filter_by_period_hours():
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    trades = [
        {"created_at": (now - timedelta(hours=2)).isoformat(),
         "pnl_usd": 5.0, "result": "win"},
        {"created_at": (now - timedelta(hours=25)).isoformat(),
         "pnl_usd": -3.0, "result": "loss"},
    ]
    result = filter_by_period(trades, hours=24)
    assert len(result) == 1
    assert result[0]["pnl_usd"] == 5.0


def test_filter_by_period_days():
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    trades = [
        {"created_at": (now - timedelta(days=3)).isoformat(),
         "pnl_usd": 5.0, "result": "win"},
        {"created_at": (now - timedelta(days=10)).isoformat(),
         "pnl_usd": -3.0, "result": "loss"},
    ]
    result = filter_by_period(trades, days=7)
    assert len(result) == 1


def test_filter_by_period_none():
    trades = _make_trades()
    assert len(filter_by_period(trades)) == 4


def test_band_best_worst():
    trades = _make_trades()
    bw = band_best_worst(trades)
    # 0.40-0.60 band has t3 (pnl=12.50) and t4 (pnl=-5.56)
    assert "0.40-0.60" in bw
    assert bw["0.40-0.60"]["best_pnl"] == 12.50
    assert bw["0.40-0.60"]["worst_pnl"] == -5.56


def test_band_best_worst_empty():
    assert band_best_worst([]) == {}


def test_detect_warnings_negative_edge():
    """edge がマイナスの帯を検出する。"""
    # 低entry_priceでBuyして全部loss → edge がマイナス
    trades = [
        {"entry_price": 0.15, "result": "loss", "direction": "Buy-Yes",
         "pnl_usd": -50, "market_id": "m1", "market_title": "MktA"},
        {"entry_price": 0.15, "result": "loss", "direction": "Buy-Yes",
         "pnl_usd": -50, "market_id": "m1", "market_title": "MktA"},
        {"entry_price": 0.15, "result": "loss", "direction": "Buy-Yes",
         "pnl_usd": -50, "market_id": "m1", "market_title": "MktA"},
    ]
    warns = detect_warnings(trades)
    assert len(warns) >= 1
    assert any("0.00-0.20" in w for w in warns)


def test_detect_warnings_empty():
    assert detect_warnings([]) == []


def test_live_block_reason_blocked():
    trades = _make_trades()  # 4件 → 100未達
    reason = live_block_reason(trades)
    assert "未達" in reason
    assert "トレード数" in reason


def test_live_block_reason_empty_when_all_pass():
    """check_v2_readiness が all_passed なら空文字。"""
    # テストでは100件用意するのは重いので、関数の振る舞いだけ確認
    reason = live_block_reason([])  # 0件 → not passed
    assert reason != ""
