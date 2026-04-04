"""Executorのテスト。"""

import pytest
from datetime import datetime, timezone

from src.execution.executor import Executor
from src.execution.models import OrderStatus, TradingMode
from src.execution.paper_broker import PaperBroker
from src.execution.risk_manager import RiskManager
from src.processor.signal_detector import Signal


def _make_signal(market_id: str = "m1", is_strong: bool = True) -> Signal:
    now = datetime.now(timezone.utc)
    return Signal(
        market_id=market_id,
        market_title="Test Market",
        direction="Buy-Yes",
        wallets=["w1", "w2", "w3"],
        total_amount_usdc=2000.0,
        avg_price=0.65,
        first_trade_time=now,
        last_trade_time=now,
        is_strong=is_strong,
    )


@pytest.mark.asyncio
async def test_paper_mode_fills():
    rm = RiskManager(max_order_usd=100, min_signal_level="STRONG")
    executor = Executor(
        mode=TradingMode.PAPER,
        risk_manager=rm,
        paper_broker=PaperBroker(),
        order_amount_usd=50,
    )
    orders = await executor.process_signals([_make_signal()])
    assert len(orders) == 1
    assert orders[0].status == OrderStatus.FILLED
    assert executor.stats["total_fills"] == 1


@pytest.mark.asyncio
async def test_dry_run_does_not_fill():
    rm = RiskManager(max_order_usd=100, min_signal_level="STRONG")
    executor = Executor(
        mode=TradingMode.DRY_RUN,
        risk_manager=rm,
        order_amount_usd=50,
    )
    orders = await executor.process_signals([_make_signal()])
    assert len(orders) == 1
    assert orders[0].status == OrderStatus.CANCELLED
    assert "DRY-RUN" in orders[0].reject_reason


@pytest.mark.asyncio
async def test_live_blocked_without_allow():
    rm = RiskManager(max_order_usd=100, min_signal_level="STRONG")
    executor = Executor(
        mode=TradingMode.LIVE,
        risk_manager=rm,
        allow_live=False,
        order_amount_usd=50,
    )
    orders = await executor.process_signals([_make_signal()])
    assert len(orders) == 1
    assert orders[0].status == OrderStatus.REJECTED
    assert "ALLOW_LIVE_TRADING" in orders[0].reject_reason


@pytest.mark.asyncio
async def test_weak_signal_rejected():
    rm = RiskManager(max_order_usd=100, min_signal_level="STRONG")
    executor = Executor(
        mode=TradingMode.PAPER,
        risk_manager=rm,
        order_amount_usd=50,
    )
    orders = await executor.process_signals([_make_signal(is_strong=False)])
    assert len(orders) == 1
    assert orders[0].status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_stats_tracking():
    rm = RiskManager(max_order_usd=100, min_signal_level="NORMAL")
    executor = Executor(
        mode=TradingMode.PAPER,
        risk_manager=rm,
        order_amount_usd=50,
    )
    await executor.process_signals([
        _make_signal("m1"),
        _make_signal("m2"),
    ])
    stats = executor.stats
    assert stats["total_orders"] == 2
    assert stats["mode"] == "PAPER"
