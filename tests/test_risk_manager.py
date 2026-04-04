"""リスクマネージャーのテスト。"""

from datetime import datetime, timezone

from src.execution.risk_manager import RiskManager
from src.processor.signal_detector import Signal


def _make_signal(
    market_id: str = "m1", is_strong: bool = True, amount: float = 500.0
) -> Signal:
    now = datetime.now(timezone.utc)
    return Signal(
        market_id=market_id,
        market_title="Test Market",
        direction="Buy-Yes",
        wallets=["w1", "w2", "w3"],
        total_amount_usdc=amount,
        avg_price=0.65,
        first_trade_time=now,
        last_trade_time=now,
        is_strong=is_strong,
    )


def test_allows_valid_order():
    rm = RiskManager(max_order_usd=100, max_daily_loss_usd=500, min_signal_level="STRONG")
    allowed, reason = rm.evaluate(_make_signal(), 50)
    assert allowed is True
    assert reason == "OK"


def test_rejects_weak_signal():
    rm = RiskManager(min_signal_level="STRONG")
    allowed, reason = rm.evaluate(_make_signal(is_strong=False), 50)
    assert allowed is False
    assert "シグナルレベル不足" in reason


def test_rejects_over_max_order():
    rm = RiskManager(max_order_usd=30)
    allowed, reason = rm.evaluate(_make_signal(), 50)
    assert allowed is False
    assert "上限" in reason


def test_rejects_over_position_limit():
    rm = RiskManager(max_order_usd=100, max_position_usd=80)
    rm.record_order("m1", 50)
    allowed, reason = rm.evaluate(_make_signal(market_id="m1"), 50)
    assert allowed is False
    assert "ポジション上限" in reason


def test_daily_loss_halts():
    rm = RiskManager(max_daily_loss_usd=100)
    rm.record_loss(100)
    assert rm.is_halted is True
    allowed, reason = rm.evaluate(_make_signal(), 10)
    assert allowed is False


def test_kill_switch_env():
    rm = RiskManager(kill_switch_env=True)
    allowed, reason = rm.evaluate(_make_signal(), 10)
    assert allowed is False
    assert "KILL_SWITCH" in reason


def test_cooldown():
    rm = RiskManager(max_order_usd=100, cooldown_sec=600)
    rm.record_order("m1", 10)
    allowed, reason = rm.evaluate(_make_signal(market_id="m1"), 10)
    assert allowed is False
    assert "クールダウン" in reason


def test_different_market_no_cooldown():
    rm = RiskManager(max_order_usd=100, cooldown_sec=600)
    rm.record_order("m1", 10)
    allowed, reason = rm.evaluate(_make_signal(market_id="m2"), 10)
    assert allowed is True
